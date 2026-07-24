from __future__ import annotations

import time
from datetime import UTC, datetime
from statistics import mean
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.mobius import MobiusClient
from app.models import AnalysisResult
from app.store import SessionStore
from app.topology import ANALYTICS_AE


LIGHT_COMMANDS: dict[str, dict[str, int]] = {
    "NORMAL": {"red": 0, "green": 255, "blue": 0, "transition_ms": 1000},
    "STRETCH_WARNING": {"red": 255, "green": 0, "blue": 0, "transition_ms": 5000},
    "TURTLE_NECK": {"red": 255, "green": 0, "blue": 0, "transition_ms": 1000},
    "DESK_UP": {"red": 0, "green": 255, "blue": 0, "transition_ms": 1000},
}

RAISE_POSTURE_STATES = {"STRETCH_WARNING", "TURTLE_NECK"}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def calculate_posture_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    samples: list[tuple[datetime, float | None, bool]] = []
    sample_count = 0
    for event in events:
        if event.get("type") != "postureSamples" and event.get("source") != "postureCamera/postureSamples":
            continue
        sample_count += 1
        content = event.get("content")
        if not isinstance(content, dict):
            continue
        if content.get("valid") is False:
            continue
        if content.get("detected") is False:
            continue
        if content.get("landmarks_valid") is False:
            continue

        neck_forward = content.get("neck_forward")
        if not isinstance(neck_forward, bool):
            continue

        measured_at = _parse_time(
            content.get("captured_at")
            or content.get("measured_at")
            or content.get("timestamp")
            or event.get("created_at")
        )
        if not measured_at:
            continue

        mcra: float | None
        try:
            mcra = float(content.get("mCRA"))
        except (TypeError, ValueError):
            mcra = None
        samples.append((measured_at, mcra, neck_forward))

    samples.sort(key=lambda item: item[0])
    if not samples:
        return {
            "sample_count": sample_count,
            "valid_sample_count": 0,
            "average_mcra": None,
            "max_mcra": None,
            "forward_sample_ratio": 0.0,
            "forward_duration_seconds": 0.0,
            "longest_forward_seconds": 0.0,
            "forward_episode_count": 0,
            "recent_forward_ratio": 0.0,
            "recent_60s_valid_count": 0,
            "recent_60s_neck_forward_count": 0,
            "recent_60s_neck_forward_ratio": 0.0,
            "consecutive_neck_forward_seconds": 0.0,
        }

    forward_count = sum(1 for _, _, forward in samples if forward)
    episodes = 0
    previous_forward = False
    for _, _, forward in samples:
        if forward and not previous_forward:
            episodes += 1
        previous_forward = forward

    latest_at = samples[-1][0]
    recent_cutoff = samples[-1][0].timestamp() - 60
    recent = [sample for sample in samples if sample[0].timestamp() >= recent_cutoff]
    recent_neck_count = sum(1 for _, _, forward in recent if forward)
    recent_ratio = recent_neck_count / len(recent) if recent else 0.0

    consecutive_seconds = 0.0
    if samples[-1][2]:
        consecutive_start = latest_at
        for measured_at, _, forward in reversed(samples):
            if not forward:
                break
            consecutive_start = measured_at
        consecutive_seconds = max(0.0, (latest_at - consecutive_start).total_seconds())

    values = [mcra for _, mcra, _ in samples if mcra is not None]
    return {
        "sample_count": sample_count,
        "valid_sample_count": len(samples),
        "average_mcra": round(mean(values), 1) if values else None,
        "max_mcra": round(max(values), 1) if values else None,
        "forward_sample_ratio": round(forward_count / len(samples), 3),
        "forward_duration_seconds": round(consecutive_seconds, 1),
        "longest_forward_seconds": round(consecutive_seconds, 1),
        "forward_episode_count": episodes,
        "recent_forward_ratio": round(recent_ratio, 3),
        "recent_60s_valid_count": len(recent),
        "recent_60s_neck_forward_count": recent_neck_count,
        "recent_60s_neck_forward_ratio": round(recent_ratio, 3),
        "consecutive_neck_forward_seconds": round(consecutive_seconds, 1),
    }


class SuggestionEngine:
    def __init__(self, settings: Settings, store: SessionStore, mobius: MobiusClient):
        self.settings = settings
        self.store = store
        self.mobius = mobius
        self._last_evaluation: dict[str, float] = {}
        self._last_lcd_state: dict[str, str] = {}
        self._last_light_state: dict[str, str] = {}
        self._last_posture_state: dict[str, str] = {}
        self._desk_positions: dict[str, str] = {}
        self._processed_button_events: set[str] = set()

    async def analyze(
        self, session_id: str, *, automatic: bool = False, deliver: bool = True
    ) -> tuple[AnalysisResult, dict[str, Any] | None]:
        if automatic:
            now = time.monotonic()
            previous = self._last_evaluation.get(session_id, 0.0)
            if now - previous < self.settings.posture_analysis_interval_seconds:
                return self._empty_result("Automatic analysis is waiting."), None
            self._last_evaluation[session_id] = now

        events = await self.store.list_events(session_id, 5000)
        metrics = calculate_posture_metrics(events)
        result, candidate = self._decide(metrics)
        posture_state = self._posture_state(candidate)
        print(
            "POSTURE AGGREGATE "
            f"session={session_id} "
            f"valid_count={metrics.get('valid_sample_count', 0)} "
            f"consecutive_seconds={metrics.get('consecutive_neck_forward_seconds', 0.0)} "
            f"recent60_valid={metrics.get('recent_60s_valid_count', 0)} "
            f"recent60_neck={metrics.get('recent_60s_neck_forward_count', 0)} "
            f"recent60_ratio={metrics.get('recent_60s_neck_forward_ratio', 0.0)} "
            f"state={posture_state}"
        )
        self._last_posture_state[session_id] = posture_state
        if (
            deliver
            and posture_state == "NORMAL"
            and metrics.get("sample_count", 0) > 0
        ):
            await self._deliver_normal_to_lcd(session_id)
        if not candidate or not deliver:
            return result, None

        recent = await self.store.find_recent_suggestion(
            session_id,
            candidate["type"],
            self.settings.posture_suggestion_cooldown_seconds,
        )
        if recent:
            if recent["content"].get("status") == "proposed":
                await self._deliver_to_lcd(recent)
                return result, recent
            return result, None

        suggestion = {
            "suggestion_id": str(uuid4()),
            "session_id": session_id,
            "status": "proposed",
            "priority": candidate["priority"],
            "title": candidate["title"],
            "message": candidate["message"],
            "reason": candidate["reason"],
            "type": candidate["type"],
            "metrics": metrics,
            "lcd": candidate["lcd"],
            "action": candidate.get("action"),
            "requires_response": bool(candidate.get("action")),
            "created_at": datetime.now(UTC).isoformat(),
            "algorithm_version": "posture-v1",
        }
        resource_name = await self.mobius.create_content_instance(
            ANALYTICS_AE, "suggestions", suggestion
        )
        suggestion_event = await self.store.add_event(
            session_id, "suggestion", suggestion, "ai", resource_name
        )
        await self._deliver_to_lcd(suggestion_event)
        return result, suggestion_event

    def _desk_position(self, session_id: str) -> str:
        if session_id in self._desk_positions:
            return self._desk_positions[session_id]
        return "DOWN" if self.settings.desk_assume_down_on_startup else "UNKNOWN"

    def desk_position_for_session(self, session_id: str) -> str | None:
        return self._desk_positions.get(session_id)

    def moving_session_ids(self) -> set[str]:
        return {
            session_id
            for session_id, position in self._desk_positions.items()
            if position in {"MOVING_UP", "MOVING_DOWN"}
        }

    def _motor_context(self, session_id: str, posture_state: str) -> dict[str, Any]:
        desk_position = self._desk_position(session_id)
        next_action = "none"
        accept_enabled = False
        target_height_cm: int | None = None
        target_position: str | None = None

        if desk_position == "DOWN" and posture_state in RAISE_POSTURE_STATES:
            next_action = "raise"
            accept_enabled = True
            target_height_cm = self.settings.desk_standing_height_cm
            target_position = "UP"
        elif desk_position == "UP":
            next_action = "lower"
            accept_enabled = True
            target_height_cm = self.settings.desk_sitting_height_cm
            target_position = "DOWN"

        return {
            "desk_position": desk_position,
            "next_motor_action": next_action,
            "accept_enabled": accept_enabled,
            "requires_response": accept_enabled,
            "target_height_cm": target_height_cm,
            "target_position": target_position,
        }

    def _lcd_lines(self, posture_state: str, context: dict[str, Any]) -> tuple[str, str]:
        desk_position = context["desk_position"]
        next_action = context["next_motor_action"]
        if desk_position == "MOVING_UP":
            return "DESK MOVING UP", "PLEASE WAIT"
        if desk_position == "MOVING_DOWN":
            return "DESK MOVING DOWN", "PLEASE WAIT"
        if desk_position == "UP":
            return "DESK IS UP", "B: SIT DOWN"
        if desk_position in {"UNKNOWN", "ERROR"}:
            return "DESK UNKNOWN", "WAIT MOTOR"
        if posture_state == "STRETCH_WARNING":
            return "STRETCH NEEDED", "B: STAND UP" if next_action == "raise" else "PLEASE STRETCH"
        if posture_state == "TURTLE_NECK":
            return "TURTLE NECK", "B: STAND UP" if next_action == "raise" else "PRESS B TO OK"
        return "ANALYZING...", "POSTURE OK"

    async def _deliver_to_lcd(self, suggestion_event: dict[str, Any]) -> None:
        suggestion = suggestion_event["content"]
        posture_state = self._posture_state(suggestion)
        self._last_posture_state[suggestion["session_id"]] = posture_state
        context = self._motor_context(suggestion["session_id"], posture_state)
        line1, line2 = self._lcd_lines(posture_state, context)
        command = {
            "command_id": str(uuid4()),
            "suggestion_id": suggestion["suggestion_id"],
            "session_id": suggestion["session_id"],
            "type": "posture_result",
            "posture_state": posture_state,
            "line1": line1,
            "line2": line2,
            "accept_enabled": context["accept_enabled"],
            "requires_response": context["requires_response"],
            "desk_position": context["desk_position"],
            "next_motor_action": context["next_motor_action"],
            "created_at": datetime.now(UTC).isoformat(),
        }
        if context["target_height_cm"] is not None:
            command["target_height_cm"] = context["target_height_cm"]
        if context["target_position"]:
            command["target_position"] = context["target_position"]
        try:
            await self.mobius.create_content_instance("deskInterface", "lcdCommand", command)
        finally:
            await self._deliver_to_light(
                session_id=suggestion["session_id"],
                posture_state=posture_state,
            )
        print(f'LCD state={posture_state} line1="{line1}"')
        self._last_lcd_state[suggestion["session_id"]] = posture_state
        suggestion["status"] = "delivered"
        await self.store.update_event_content(suggestion_event["id"], suggestion)
        suggestion_event["content"] = suggestion

    async def _deliver_normal_to_lcd(self, session_id: str) -> None:
        posture_state = "NORMAL"
        self._last_posture_state[session_id] = posture_state
        context = self._motor_context(session_id, posture_state)
        line1, line2 = self._lcd_lines(posture_state, context)
        lcd_state_key = f"{posture_state}:{context['desk_position']}:{context['next_motor_action']}"
        if self._last_lcd_state.get(session_id) == lcd_state_key:
            await self._deliver_to_light(session_id=session_id, posture_state=posture_state)
            return
        command = {
            "command_id": str(uuid4()),
            "session_id": session_id,
            "type": "posture_result",
            "posture_state": posture_state,
            "line1": line1,
            "line2": line2,
            "accept_enabled": context["accept_enabled"],
            "requires_response": context["requires_response"],
            "desk_position": context["desk_position"],
            "next_motor_action": context["next_motor_action"],
            "created_at": datetime.now(UTC).isoformat(),
        }
        if context["target_height_cm"] is not None:
            command["target_height_cm"] = context["target_height_cm"]
        if context["target_position"]:
            command["target_position"] = context["target_position"]
        try:
            await self.mobius.create_content_instance("deskInterface", "lcdCommand", command)
        finally:
            await self._deliver_to_light(session_id=session_id, posture_state=posture_state)
        print(f'LCD state={posture_state} line1="{line1}"')
        self._last_lcd_state[session_id] = lcd_state_key

    async def _deliver_motion_lcd(
        self,
        *,
        session_id: str,
        position: str,
        command_id: str | None = None,
    ) -> None:
        posture_state = self._last_posture_state.get(session_id, "NORMAL")
        context = self._motor_context(session_id, posture_state)
        line1, line2 = self._lcd_lines(posture_state, context)
        command = {
            "command_id": str(uuid4()),
            "session_id": session_id,
            "type": "motor_status",
            "posture_state": posture_state,
            "line1": line1,
            "line2": line2,
            "accept_enabled": context["accept_enabled"],
            "requires_response": context["requires_response"],
            "desk_position": position,
            "next_motor_action": context["next_motor_action"],
            "created_at": datetime.now(UTC).isoformat(),
        }
        if command_id:
            command["motor_command_id"] = command_id
        if context["target_height_cm"] is not None:
            command["target_height_cm"] = context["target_height_cm"]
        if context["target_position"]:
            command["target_position"] = context["target_position"]
        await self.mobius.create_content_instance("deskInterface", "lcdCommand", command)
        print(f'LCD state={posture_state} line1="{line1}"')
        self._last_lcd_state[session_id] = f"{posture_state}:{position}:{context['next_motor_action']}"

    async def _deliver_to_light(
        self,
        *,
        session_id: str,
        posture_state: str,
        transition_ms: int | None = None,
        force: bool = False,
    ) -> None:
        state = self._light_state_for(session_id, posture_state)
        if not state:
            print(
                f"Lighting command skipped: desk_position={self._desk_position(session_id)}, "
                f"session_id={session_id}"
            )
            return

        values = LIGHT_COMMANDS[state]
        command_transition_ms = (
            values["transition_ms"] if transition_ms is None else transition_ms
        )
        command_key = (
            f"{state}:{values['red']}:{values['green']}:"
            f"{values['blue']}:{command_transition_ms}"
        )
        previous = self._last_light_state.get(session_id)
        desk_position = self._desk_position(session_id)
        print(
            f"LIGHT DECISION posture={posture_state} "
            f"desk={desk_position} mode={state} "
            f"rgb={values['red']},{values['green']},{values['blue']} "
            f"transition={command_transition_ms}"
        )
        if previous == command_key and not force:
            print(
                f"Lighting command skipped: unchanged mode={state}, "
                f"session_id={session_id}"
            )
            return

        command_id = str(uuid4())
        command = {
            "command_id": command_id,
            "session_id": session_id,
            "state": state,
            "red": values["red"],
            "green": values["green"],
            "blue": values["blue"],
            "transition_ms": command_transition_ms,
            "issued_at": datetime.now(UTC).isoformat(),
        }

        if previous != command_key:
            print(
                f"Lighting state changed: session_id={session_id}, "
                f"previous={previous}, current={command_key}"
            )
        try:
            await self.mobius.create_content_instance("postureLight", "command", command)
        except Exception as exc:
            print(
                f"Lighting command failed: session_id={session_id}, "
                f"state={state}, error={exc}"
            )
            return

        self._last_light_state[session_id] = command_key
        print(
            f"Lighting command created: command_id={command_id}, "
            f"state={state}, rgb=({values['red']},{values['green']},{values['blue']}), "
            f"transition_ms={command_transition_ms}"
        )

    def _light_state_for(self, session_id: str, posture_state: str) -> str | None:
        desk_position = self._desk_position(session_id)
        if desk_position in {"UP", "MOVING_DOWN"}:
            return "DESK_UP"
        if desk_position == "MOVING_UP":
            return "TURTLE_NECK"
        if desk_position == "DOWN":
            return posture_state if posture_state in LIGHT_COMMANDS else "NORMAL"
        return None

    async def handle_button_event(self, content: dict[str, Any]) -> dict[str, Any] | None:
        action_name = str(content.get("action", "")).lower()
        button_name = str(content.get("button", "")).upper()
        if action_name in {"stop", "end", "close"} and button_name in {"A", "STOP", "END"}:
            return await self._handle_stop_button_event(content)
        if action_name == "start" or button_name in {"A", "START", "KICKOFF"}:
            return await self._handle_start_button_event(content)

        accepted = action_name in {
            "accept", "accepted", "agree", "toggle_desk"
        } or button_name in {"B", "ACCEPT"}
        if not accepted:
            return None
        session_id = str(content.get("session_id") or "")
        if not session_id:
            return None

        event_key = self._button_event_key(content)
        if event_key in self._processed_button_events:
            print(f"B accept ignored: duplicate event_key={event_key}")
            return None

        suggestion_id = str(content.get("suggestion_id") or "")
        suggestion_event = (
            await self.store.find_suggestion(session_id, suggestion_id)
            if suggestion_id
            else await self.store.find_latest_actionable_suggestion(session_id)
        )
        suggestion = suggestion_event["content"] if suggestion_event else None
        if suggestion:
            self._last_posture_state[session_id] = self._posture_state(suggestion)
        posture_state = self._last_posture_state.get(session_id, "NORMAL")
        desk_position = self._desk_position(session_id)
        direction: str | None = None
        target_position: str | None = None
        target_height_cm: int | None = None

        if desk_position == "DOWN" and posture_state in RAISE_POSTURE_STATES:
            direction = "up"
            target_position = "UP"
            target_height_cm = self.settings.desk_standing_height_cm
        elif desk_position == "UP":
            direction = "down"
            target_position = "DOWN"
            target_height_cm = self.settings.desk_sitting_height_cm
        else:
            print(
                f"B accept rejected: session_id={session_id}, "
                f"desk_position={desk_position}, posture_state={posture_state}"
            )
            return None

        print(
            f"B accept received: session_id={session_id}, "
            f"suggestion_id={suggestion_id}, direction={direction}"
        )
        command = {
            "command_id": str(uuid4()),
            "session_id": session_id,
            "action": "set_height",
            "direction": direction,
            "target_position": target_position,
            "target_height_cm": target_height_cm,
            "issued_at": datetime.now(UTC).isoformat(),
        }
        if suggestion_id:
            command["suggestion_id"] = suggestion_id
        try:
            await self.mobius.create_content_instance("deskMotor", "command", command)
        except Exception as exc:
            print(
                f"Motor command failed: session_id={session_id}, "
                f"suggestion_id={suggestion_id}, error={exc}"
            )
            raise

        moving_position = "MOVING_UP" if direction == "up" else "MOVING_DOWN"
        self._desk_positions[session_id] = moving_position
        self._processed_button_events.add(event_key)
        print(
            f"Motor command created: command_id={command['command_id']}, "
            f"target_height_cm={command['target_height_cm']}"
        )
        await self._deliver_motion_lcd(
            session_id=session_id,
            position=moving_position,
            command_id=command["command_id"],
        )
        await self._deliver_to_light(
            session_id=session_id,
            posture_state=posture_state,
        )
        return {"device": "deskMotor", **command}

    def _button_event_key(self, content: dict[str, Any]) -> str:
        for key in ("_mobius_resource_name", "event_id", "button_event_id"):
            value = str(content.get(key) or "")
            if value:
                return value
        return ":".join(
            str(content.get(key) or "")
            for key in (
                "session_id",
                "button",
                "action",
                "command_id",
                "requested_motor_action",
                "uptime_ms",
            )
        )

    async def _handle_start_button_event(self, content: dict[str, Any]) -> dict[str, Any] | None:
        session_id = str(content.get("session_id") or "")
        if not session_id:
            return None
        self._desk_positions.setdefault(
            session_id,
            "DOWN" if self.settings.desk_assume_down_on_startup else "UNKNOWN",
        )
        self._last_posture_state.setdefault(session_id, "NORMAL")
        command = {
            "command_id": str(uuid4()),
            "session_id": session_id,
            "action": "start",
            "source": "deskInterface/buttonEvents",
            "button": "A",
            "device_id": content.get("device_id"),
            "uptime_ms": content.get("uptime_ms"),
            "issued_at": datetime.now(UTC).isoformat(),
        }
        await self.mobius.create_content_instance("postureCamera", "command", command)
        print(f"Initial lighting command requested: session_id={session_id}, state=NORMAL")
        await self._deliver_to_light(
            session_id=session_id,
            posture_state="NORMAL",
            transition_ms=0,
        )
        return {"device": "postureCamera", **command}

    async def _handle_stop_button_event(self, content: dict[str, Any]) -> dict[str, Any] | None:
        session_id = str(content.get("session_id") or "")
        if not session_id:
            return None
        command = {
            "command_id": str(uuid4()),
            "session_id": session_id,
            "action": "stop",
            "source": "deskInterface/buttonEvents",
            "button": "A",
            "device_id": content.get("device_id"),
            "uptime_ms": content.get("uptime_ms"),
            "issued_at": datetime.now(UTC).isoformat(),
        }
        await self.mobius.create_content_instance("postureCamera", "command", command)
        print(f"Posture stop command requested: session_id={session_id}")
        return {"device": "postureCamera", **command}

    async def handle_motor_status(
        self,
        content: dict[str, Any],
        session_id: str,
    ) -> None:
        position = self._normalize_motor_position(content)
        if not position:
            return
        self._desk_positions[session_id] = position
        print(f"Motor position updated: session_id={session_id}, position={position}")
        try:
            await self._deliver_motion_lcd(
                session_id=session_id,
                position=position,
                command_id=str(content.get("command_id") or ""),
            )
            await self._deliver_to_light(
                session_id=session_id,
                posture_state=self._last_posture_state.get(session_id, "NORMAL"),
            )
        except Exception as exc:
            print(
                f"Motor LCD update failed: session_id={session_id}, "
                f"position={position}, error={exc}"
            )

    @staticmethod
    def _normalize_motor_position(content: dict[str, Any]) -> str | None:
        event = str(content.get("event") or "").lower()
        if event and event not in {"movement_started", "movement_completed", "movement_failed", "startup"}:
            return None
        if event == "movement_started":
            target = str(content.get("target_position") or content.get("target_state") or "").upper()
            if target in {"UP", "STAND"}:
                return "MOVING_UP"
            if target in {"DOWN", "SIT"}:
                return "MOVING_DOWN"
        if event == "movement_completed":
            target = str(content.get("position") or content.get("target_position") or content.get("desk_state") or "").upper()
            if target in {"UP", "STAND"}:
                return "UP"
            if target in {"DOWN", "SIT"}:
                return "DOWN"
        if event == "movement_failed":
            return "ERROR"

        candidates = [
            content.get("position"),
            content.get("desk_position"),
            content.get("state"),
            content.get("desk_state"),
            content.get("target_position"),
        ]
        for value in candidates:
            state = str(value or "").upper()
            if state in {"UP", "DOWN", "MOVING_UP", "MOVING_DOWN", "UNKNOWN", "ERROR"}:
                return state
            if state == "STAND":
                return "UP"
            if state == "SIT":
                return "DOWN"
        return None

    @staticmethod
    def _posture_state(candidate: dict[str, Any] | None) -> str:
        if not candidate:
            return "NORMAL"
        if candidate.get("type") == "DESK_HEIGHT_CHANGE":
            return "TURTLE_NECK"
        if candidate.get("type") == "POSTURE_CORRECTION":
            return "STRETCH_WARNING"
        return str(candidate.get("posture_state") or "NORMAL")

    def _decide(self, metrics: dict[str, Any]) -> tuple[AnalysisResult, dict[str, Any] | None]:
        count = metrics["valid_sample_count"]
        ratio = metrics["forward_sample_ratio"]
        recent = metrics["recent_60s_neck_forward_ratio"]
        consecutive = metrics["consecutive_neck_forward_seconds"]
        if not count:
            return self._empty_result("No valid posture samples are available."), None

        summary = (
            f"Among {count} valid samples, the forward-head ratio is {ratio * 100:.1f}% "
            f"and the current continuous forward-head segment is {consecutive:.1f} seconds."
        )
        insights = [
            f"Average mCRA {metrics['average_mcra']} degrees, max {metrics['max_mcra']} degrees",
            f"Recent 60-second forward-head ratio {recent * 100:.1f}%",
            f"Forward-head episode count {metrics['forward_episode_count']}",
        ]
        candidate = None
        if count < self.settings.posture_min_samples:
            pass
        elif consecutive >= 120:
            candidate = {
                "type": "DESK_HEIGHT_CHANGE",
                "priority": "high",
                "title": "Standing mode suggestion",
                "message": "Forward-head posture has continued for too long. Switch to standing mode.",
                "reason": f"Continuous forward-head duration is {consecutive:.1f} seconds.",
                "lcd": {"line1": "TURTLE NECK", "line2": "B: STAND UP"},
                "action": {
                    "device": "deskMotor",
                    "command": "set_height",
                    "target_height_cm": self.settings.desk_standing_height_cm,
                },
            }
        elif consecutive >= 10 or recent >= 0.5:
            candidate = {
                "type": "POSTURE_CORRECTION",
                "priority": "medium",
                "title": "Posture correction",
                "message": "Relax your neck and shoulders and correct your posture.",
                "reason": f"Recent forward-head ratio is {recent * 100:.1f}%.",
                "lcd": {"line1": "STRETCH NEEDED", "line2": "B: STAND UP"},
            }

        recommendations = [candidate["message"]] if candidate else ["Keep the current posture."]
        risk = "high" if consecutive >= 120 else "medium" if candidate else "low"
        return AnalysisResult(
            provider="local",
            model="posture-v1",
            summary=summary,
            insights=insights,
            recommendations=recommendations,
            risk_level=risk,
            raw={"metrics": metrics},
        ), candidate

    @staticmethod
    def _empty_result(message: str) -> AnalysisResult:
        return AnalysisResult(
            provider="local",
            model="posture-v1",
            summary=message,
            insights=[],
            recommendations=[],
            risk_level="low",
            raw={"metrics": {}},
        )
