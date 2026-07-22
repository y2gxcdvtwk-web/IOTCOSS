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


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def calculate_posture_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    samples: list[tuple[datetime, float, bool]] = []
    sample_count = 0
    for event in events:
        if event.get("type") != "postureSamples" and event.get("source") != "postureCamera/postureSamples":
            continue
        sample_count += 1
        content = event.get("content")
        if not isinstance(content, dict):
            continue
        try:
            mcra = float(content.get("mCRA"))
        except (TypeError, ValueError):
            continue
        if mcra <= 0:
            continue
        measured_at = _parse_time(content.get("measured_at") or event.get("created_at"))
        if measured_at:
            samples.append((measured_at, mcra, mcra >= 120.0))

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
        }

    forward_count = sum(1 for _, _, forward in samples if forward)
    forward_duration = 0.0
    longest_forward = 0.0
    current_forward = 0.0
    episodes = 0
    previous_forward = False
    for index, (_, _, forward) in enumerate(samples):
        if forward and not previous_forward:
            episodes += 1
        if index + 1 < len(samples):
            delta = max(0.0, min(5.0, (samples[index + 1][0] - samples[index][0]).total_seconds()))
        else:
            delta = 0.0
        if forward:
            forward_duration += delta
            current_forward += delta
            longest_forward = max(longest_forward, current_forward)
        else:
            current_forward = 0.0
        previous_forward = forward

    recent_cutoff = samples[-1][0].timestamp() - 60
    recent = [sample for sample in samples if sample[0].timestamp() >= recent_cutoff]
    recent_ratio = sum(1 for _, _, forward in recent if forward) / len(recent)
    values = [mcra for _, mcra, _ in samples]
    return {
        "sample_count": sample_count,
        "valid_sample_count": len(samples),
        "average_mcra": round(mean(values), 1),
        "max_mcra": round(max(values), 1),
        "forward_sample_ratio": round(forward_count / len(samples), 3),
        "forward_duration_seconds": round(forward_duration, 1),
        "longest_forward_seconds": round(longest_forward, 1),
        "forward_episode_count": episodes,
        "recent_forward_ratio": round(recent_ratio, 3),
    }


class SuggestionEngine:
    def __init__(self, settings: Settings, store: SessionStore, mobius: MobiusClient):
        self.settings = settings
        self.store = store
        self.mobius = mobius
        self._last_evaluation: dict[str, float] = {}

    async def analyze(
        self, session_id: str, *, automatic: bool = False, deliver: bool = True
    ) -> tuple[AnalysisResult, dict[str, Any] | None]:
        if automatic:
            now = time.monotonic()
            previous = self._last_evaluation.get(session_id, 0.0)
            if now - previous < self.settings.posture_analysis_interval_seconds:
                return self._empty_result("자동 분석 대기 중입니다."), None
            self._last_evaluation[session_id] = now

        events = await self.store.list_events(session_id, 5000)
        metrics = calculate_posture_metrics(events)
        result, candidate = self._decide(metrics)
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

    async def _deliver_to_lcd(self, suggestion_event: dict[str, Any]) -> None:
        suggestion = suggestion_event["content"]
        command = {
            "command_id": str(uuid4()),
            "suggestion_id": suggestion["suggestion_id"],
            "session_id": suggestion["session_id"],
            "action": "display",
            "screen": "suggestion",
            **suggestion["lcd"],
            "requires_response": suggestion["requires_response"],
            "created_at": datetime.now(UTC).isoformat(),
        }
        await self.mobius.create_content_instance("deskInterface", "lcdCommand", command)
        suggestion["status"] = "delivered"
        await self.store.update_event_content(suggestion_event["id"], suggestion)
        suggestion_event["content"] = suggestion

    async def handle_button_event(self, content: dict[str, Any]) -> dict[str, Any] | None:
        accepted = str(content.get("action", "")).lower() in {
            "accept", "accepted", "agree"
        } or str(content.get("button", "")).upper() == "B"
        if not accepted:
            return None
        session_id = str(content.get("session_id") or "")
        suggestion_id = str(content.get("suggestion_id") or "")
        if not session_id:
            return None
        suggestion_event = (
            await self.store.find_suggestion(session_id, suggestion_id)
            if suggestion_id
            else await self.store.find_latest_actionable_suggestion(session_id)
        )
        if not suggestion_event:
            return None
        suggestion = suggestion_event["content"]
        suggestion_id = suggestion["suggestion_id"]
        if suggestion.get("status") == "accepted":
            return None
        action = suggestion.get("action") if isinstance(suggestion, dict) else None
        if not isinstance(action, dict) or action.get("device") != "deskMotor":
            return None
        command = {
            "command_id": str(uuid4()),
            "suggestion_id": suggestion_id,
            "session_id": session_id,
            "action": action.get("command", "set_height"),
            "target_height_cm": action["target_height_cm"],
            "issued_at": datetime.now(UTC).isoformat(),
        }
        await self.mobius.create_content_instance("deskMotor", "command", command)
        accepted_at = datetime.now(UTC).isoformat()
        accepted_suggestion = {
            **suggestion,
            "status": "accepted",
            "accepted_at": accepted_at,
        }
        # Prevent a repeated button event from issuing the physical command again,
        # even if writing the accepted lifecycle event to Mobius fails afterward.
        await self.store.update_event_content(
            suggestion_event["id"], accepted_suggestion
        )
        await self.mobius.create_content_instance(
            ANALYTICS_AE,
            "suggestions",
            accepted_suggestion,
        )
        return command

    def _decide(self, metrics: dict[str, Any]) -> tuple[AnalysisResult, dict[str, Any] | None]:
        count = metrics["valid_sample_count"]
        ratio = metrics["forward_sample_ratio"]
        recent = metrics["recent_forward_ratio"]
        longest = metrics["longest_forward_seconds"]
        if not count:
            return self._empty_result("분석할 유효 자세 샘플이 없습니다."), None

        summary = (
            f"유효 샘플 {count}개 중 거북목 비율은 {ratio * 100:.1f}%이며, "
            f"가장 긴 연속 거북목 구간은 {longest:.1f}초입니다."
        )
        insights = [
            f"평균 mCRA {metrics['average_mcra']}도, 최대 {metrics['max_mcra']}도",
            f"최근 60초 거북목 비율 {recent * 100:.1f}%",
            f"거북목 구간 {metrics['forward_episode_count']}회",
        ]
        candidate = None
        if count >= self.settings.posture_min_samples and longest >= 120:
            candidate = {
                "type": "DESK_HEIGHT_CHANGE",
                "priority": "high",
                "title": "입식 전환 제안",
                "message": "거북목 자세가 오래 지속됐습니다. 입식 자세로 전환할까요?",
                "reason": f"연속 거북목 시간이 {longest:.1f}초입니다.",
                "lcd": {"line1": "CHANGE TO STAND?", "line2": "B: ACCEPT"},
                "action": {
                    "device": "deskMotor",
                    "command": "set_height",
                    "target_height_cm": self.settings.desk_standing_height_cm,
                },
            }
        elif count >= self.settings.posture_min_samples and (longest >= 10 or recent >= 0.5):
            candidate = {
                "type": "POSTURE_CORRECTION",
                "priority": "medium",
                "title": "자세 교정",
                "message": "목과 어깨를 펴주세요.",
                "reason": f"최근 거북목 비율이 {recent * 100:.1f}%입니다.",
                "lcd": {"line1": "POSTURE ALERT", "line2": "STRAIGHTEN NECK"},
            }

        recommendations = [candidate["message"]] if candidate else ["현재 자세를 유지하세요."]
        risk = "high" if longest >= 120 else "medium" if candidate else "low"
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
