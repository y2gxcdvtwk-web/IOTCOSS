from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config import Settings
from app.mobius import MobiusError
from app.store import SessionStore
from app.suggestions import SuggestionEngine, calculate_posture_metrics


class FakeMobius:
    def __init__(self):
        self.calls = []

    async def create_content_instance(self, ae_name, container, content):
        self.calls.append((ae_name, container, content))
        return f"cin-{len(self.calls)}"


class FailLcdOnceMobius(FakeMobius):
    def __init__(self):
        super().__init__()
        self.failed = False

    async def create_content_instance(self, ae_name, container, content):
        if container == "lcdCommand" and not self.failed:
            self.failed = True
            raise MobiusError("temporary LCD failure")
        return await super().create_content_instance(ae_name, container, content)


class FailLightMobius(FakeMobius):
    async def create_content_instance(self, ae_name, container, content):
        if ae_name == "postureLight" and container == "command":
            raise MobiusError("temporary lighting failure")
        return await super().create_content_instance(ae_name, container, content)


class FailMotorMobius(FakeMobius):
    async def create_content_instance(self, ae_name, container, content):
        if ae_name == "deskMotor" and container == "command":
            raise MobiusError("temporary motor failure")
        return await super().create_content_instance(ae_name, container, content)


async def add_samples(store, session_id, count, interval_seconds, mcra):
    started = datetime.now(UTC) - timedelta(seconds=count * interval_seconds)
    for index in range(count):
        measured_at = started + timedelta(seconds=index * interval_seconds)
        await store.add_event(
            session_id,
            "postureSamples",
            {
                "mCRA": mcra,
                "neck_forward": mcra >= 120,
                "measured_at": measured_at.isoformat(),
            },
            "postureCamera/postureSamples",
        )


def sample_event(offset_seconds, neck_forward, *, base=None, valid=True, session_id="s-1"):
    base = base or datetime(2026, 7, 24, tzinfo=UTC)
    content = {
        "session_id": session_id,
        "neck_forward": neck_forward,
        "mCRA": 125 if neck_forward else 90,
        "measured_at": (base + timedelta(seconds=offset_seconds)).isoformat(),
    }
    if valid is not None:
        content["valid"] = valid
    return {
        "type": "postureSamples",
        "source": "postureCamera/postureSamples",
        "created_at": (base + timedelta(seconds=offset_seconds)).isoformat(),
        "content": content,
    }


def decision_state(metrics):
    store = SessionStore(Path(":memory:"), 86_400)
    engine = SuggestionEngine(Settings(posture_min_samples=5), store, FakeMobius())
    _, candidate = engine._decide(metrics)
    return engine._posture_state(candidate)


def motor_commands(mobius):
    return [
        content
        for ae, container, content in mobius.calls
        if (ae, container) == ("deskMotor", "command")
    ]


def lcd_commands(mobius):
    return [
        content
        for ae, container, content in mobius.calls
        if (ae, container) == ("deskInterface", "lcdCommand")
    ]


def light_commands(mobius):
    return [
        content
        for ae, container, content in mobius.calls
        if (ae, container) == ("postureLight", "command")
    ]


def test_posture_metrics_use_120_degree_threshold():
    now = datetime.now(UTC)
    events = [
        {
            "type": "postureSamples",
            "source": "postureCamera/postureSamples",
            "created_at": (now + timedelta(seconds=index)).isoformat(),
            "content": {"mCRA": mcra, "neck_forward": mcra >= 120},
        }
        for index, mcra in enumerate((119, 120, 125))
    ]
    metrics = calculate_posture_metrics(events)
    assert metrics["valid_sample_count"] == 3
    assert metrics["forward_sample_ratio"] == pytest.approx(0.667, abs=0.001)


def test_valid_sample_count_below_minimum_is_normal():
    events = [sample_event(index, True) for index in range(4)]
    metrics = calculate_posture_metrics(events)

    assert metrics["valid_sample_count"] == 4
    assert decision_state(metrics) == "NORMAL"


def test_five_valid_samples_with_short_consecutive_and_low_recent_ratio_is_normal():
    events = []
    for index in range(51):
        events.append(sample_event(index * 0.3, False))
    for index in range(33):
        events.append(sample_event(20 + index * 0.3, True))
    events.append(sample_event(35, False))
    for index in range(16):
        events.append(sample_event(50.4 + index * 0.6, True))

    metrics = calculate_posture_metrics(events)

    assert metrics["valid_sample_count"] >= 5
    assert metrics["consecutive_neck_forward_seconds"] == pytest.approx(9.0)
    assert metrics["recent_60s_neck_forward_ratio"] < 0.5
    assert decision_state(metrics) == "NORMAL"


def test_consecutive_ten_seconds_is_stretch_warning():
    events = [sample_event(index * 2.5, True) for index in range(5)]
    metrics = calculate_posture_metrics(events)

    assert metrics["consecutive_neck_forward_seconds"] == pytest.approx(10.0)
    assert decision_state(metrics) == "STRETCH_WARNING"


def test_recent_sixty_second_ratio_half_is_stretch_warning():
    events = [
        sample_event(index, index % 2 == 0)
        for index in range(10)
    ]
    metrics = calculate_posture_metrics(events)

    assert metrics["recent_60s_valid_count"] == 10
    assert metrics["recent_60s_neck_forward_count"] == 5
    assert metrics["recent_60s_neck_forward_ratio"] == pytest.approx(0.5)
    assert decision_state(metrics) == "STRETCH_WARNING"


def test_consecutive_119_9_seconds_is_stretch_warning():
    events = [sample_event(index * 29.975, True) for index in range(5)]
    metrics = calculate_posture_metrics(events)

    assert metrics["consecutive_neck_forward_seconds"] == pytest.approx(119.9)
    assert decision_state(metrics) == "STRETCH_WARNING"


def test_consecutive_120_seconds_is_turtle_neck():
    events = [sample_event(index * 30, True) for index in range(5)]
    metrics = calculate_posture_metrics(events)

    assert metrics["consecutive_neck_forward_seconds"] == pytest.approx(120.0)
    assert decision_state(metrics) == "TURTLE_NECK"


def test_consecutive_150_seconds_is_turtle_neck():
    events = [sample_event(index * 37.5, True) for index in range(5)]
    metrics = calculate_posture_metrics(events)

    assert metrics["consecutive_neck_forward_seconds"] == pytest.approx(150.0)
    assert decision_state(metrics) == "TURTLE_NECK"


def test_turtle_neck_has_priority_over_recent_ratio():
    events = [sample_event(index * 30, index < 5) for index in range(10)]
    metrics = calculate_posture_metrics(events)
    metrics["consecutive_neck_forward_seconds"] = 120.0
    metrics["recent_60s_neck_forward_ratio"] = 0.5

    assert decision_state(metrics) == "TURTLE_NECK"


def test_invalid_samples_are_excluded_from_recent_denominator():
    events = [
        sample_event(0, True, valid=True),
        sample_event(1, False, valid=False),
        sample_event(2, True, valid=True),
        sample_event(3, False, valid=False),
        sample_event(4, True, valid=True),
    ]
    metrics = calculate_posture_metrics(events)

    assert metrics["sample_count"] == 5
    assert metrics["valid_sample_count"] == 3
    assert metrics["recent_60s_valid_count"] == 3
    assert metrics["recent_60s_neck_forward_count"] == 3


def test_posture_metrics_do_not_mix_sessions_when_events_are_session_scoped():
    session_one = [sample_event(index * 2.5, True, session_id="s-1") for index in range(5)]
    session_two = [sample_event(index, False, session_id="s-2") for index in range(20)]

    metrics_one = calculate_posture_metrics(session_one)
    metrics_two = calculate_posture_metrics(session_two)

    assert decision_state(metrics_one) == "STRETCH_WARNING"
    assert decision_state(metrics_two) == "NORMAL"


@pytest.mark.asyncio
async def test_stretch_warning_lcd_enables_stand_button(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    await add_samples(store, session["id"], 6, 3, 125)
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(posture_min_samples=5), store, mobius)

    _, suggestion_event = await engine.analyze(session["id"])

    assert suggestion_event["content"]["type"] == "POSTURE_CORRECTION"
    lcd = lcd_commands(mobius)[-1]
    assert lcd["posture_state"] == "STRETCH_WARNING"
    assert lcd["line1"] == "STRETCH NEEDED"
    assert lcd["line2"] == "B: STAND UP"
    assert lcd["accept_enabled"] is True
    assert lcd["requires_response"] is True
    assert lcd["desk_position"] == "DOWN"
    assert lcd["next_motor_action"] == "raise"


@pytest.mark.asyncio
async def test_turtle_neck_lcd_enables_stand_button(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    await add_samples(store, session["id"], 26, 5, 130)
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(posture_min_samples=5), store, mobius)

    _, suggestion_event = await engine.analyze(session["id"])

    assert suggestion_event["content"]["type"] == "DESK_HEIGHT_CHANGE"
    lcd = lcd_commands(mobius)[-1]
    assert lcd["posture_state"] == "TURTLE_NECK"
    assert lcd["line1"] == "TURTLE NECK"
    assert lcd["line2"] == "B: STAND UP"
    assert lcd["accept_enabled"] is True
    assert lcd["requires_response"] is True
    assert lcd["desk_position"] == "DOWN"
    assert lcd["next_motor_action"] == "raise"


@pytest.mark.asyncio
async def test_down_normal_rejects_b_button(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._last_posture_state[session["id"]] = "NORMAL"

    command = await engine.handle_button_event(
        {"session_id": session["id"], "button": "B", "event_id": "b-1"}
    )

    assert command is None
    assert motor_commands(mobius) == []


@pytest.mark.asyncio
async def test_down_stretch_warning_creates_raise_command(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    await add_samples(store, session["id"], 6, 3, 125)
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(posture_min_samples=5), store, mobius)
    await engine.analyze(session["id"])

    command = await engine.handle_button_event(
        {"session_id": session["id"], "button": "B", "event_id": "b-raise-warning"}
    )

    assert command["direction"] == "up"
    assert command["target_position"] == "UP"
    assert command["target_height_cm"] == 125
    assert engine._desk_positions[session["id"]] == "MOVING_UP"
    moving_lcd = lcd_commands(mobius)[-1]
    assert moving_lcd["desk_position"] == "MOVING_UP"
    assert moving_lcd["accept_enabled"] is False


@pytest.mark.asyncio
async def test_down_turtle_neck_creates_raise_command(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    await add_samples(store, session["id"], 26, 5, 130)
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(posture_min_samples=5), store, mobius)
    await engine.analyze(session["id"])

    command = await engine.handle_button_event(
        {"session_id": session["id"], "button": "B", "event_id": "b-raise-turtle"}
    )

    assert command["direction"] == "up"
    assert command["target_position"] == "UP"
    assert command["target_height_cm"] == 125


@pytest.mark.asyncio
async def test_moving_up_rejects_b_button(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._last_posture_state[session["id"]] = "STRETCH_WARNING"
    engine._desk_positions[session["id"]] = "MOVING_UP"

    command = await engine.handle_button_event(
        {"session_id": session["id"], "button": "B", "event_id": "b-moving-up"}
    )

    assert command is None
    assert motor_commands(mobius) == []


@pytest.mark.asyncio
async def test_up_state_b_button_creates_lower_command_without_suggestion(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(desk_sitting_height_cm=75), store, mobius)
    engine._last_posture_state[session["id"]] = "NORMAL"
    await engine.handle_motor_status(
        {"session_id": session["id"], "state": "UP", "position": "UP"},
        session["id"],
    )

    command = await engine.handle_button_event(
        {"session_id": session["id"], "button": "B", "event_id": "b-lower"}
    )

    assert command["direction"] == "down"
    assert command["target_position"] == "DOWN"
    assert command["target_height_cm"] == 75
    assert engine._desk_positions[session["id"]] == "MOVING_DOWN"


@pytest.mark.asyncio
async def test_moving_down_rejects_b_button(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._desk_positions[session["id"]] = "MOVING_DOWN"

    command = await engine.handle_button_event(
        {"session_id": session["id"], "button": "B", "event_id": "b-moving-down"}
    )

    assert command is None
    assert motor_commands(mobius) == []


@pytest.mark.asyncio
async def test_up_lcd_enables_lower_button_regardless_posture(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._last_posture_state[session["id"]] = "TURTLE_NECK"
    engine._desk_positions[session["id"]] = "UP"

    await engine._deliver_normal_to_lcd(session["id"])

    lcd = lcd_commands(mobius)[-1]
    assert lcd["desk_position"] == "UP"
    assert lcd["next_motor_action"] == "lower"
    assert lcd["accept_enabled"] is True
    assert lcd["requires_response"] is True


@pytest.mark.asyncio
async def test_moving_lcd_disables_button(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)

    await engine.handle_motor_status({"state": "MOVING_UP"}, session["id"])

    lcd = lcd_commands(mobius)[-1]
    assert lcd["line1"] == "DESK MOVING UP"
    assert lcd["accept_enabled"] is False
    assert lcd["requires_response"] is False


@pytest.mark.asyncio
async def test_motor_status_updates_position_up_and_down(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)

    await engine.handle_motor_status({"state": "UP", "position": "UP"}, session["id"])
    assert engine._desk_positions[session["id"]] == "UP"
    await engine.handle_motor_status({"state": "DOWN", "position": "DOWN"}, session["id"])
    assert engine._desk_positions[session["id"]] == "DOWN"


@pytest.mark.asyncio
async def test_motor_command_accepted_event_does_not_override_moving_state(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._desk_positions[session["id"]] = "MOVING_UP"

    await engine.handle_motor_status(
        {"event": "command_accepted", "state": "DOWN", "position": "DOWN"},
        session["id"],
    )

    assert engine._desk_positions[session["id"]] == "MOVING_UP"


@pytest.mark.asyncio
async def test_duplicate_b_event_is_ignored(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._last_posture_state[session["id"]] = "STRETCH_WARNING"

    payload = {"session_id": session["id"], "button": "B", "event_id": "same-event"}
    first = await engine.handle_button_event(payload)
    second = await engine.handle_button_event(payload)

    assert first is not None
    assert second is None
    assert len(motor_commands(mobius)) == 1


@pytest.mark.asyncio
async def test_raise_then_lower_not_blocked_by_previous_suggestion(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    await add_samples(store, session["id"], 6, 3, 125)
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(posture_min_samples=5), store, mobius)
    await engine.analyze(session["id"])
    raise_command = await engine.handle_button_event(
        {"session_id": session["id"], "button": "B", "event_id": "raise"}
    )
    await engine.handle_motor_status(
        {"state": "UP", "position": "UP", "command_id": raise_command["command_id"]},
        session["id"],
    )

    lower_command = await engine.handle_button_event(
        {"session_id": session["id"], "button": "B", "event_id": "lower"}
    )

    assert lower_command["direction"] == "down"
    assert lower_command["target_position"] == "DOWN"


@pytest.mark.asyncio
async def test_lighting_commands_are_created_only_on_state_change(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)

    await engine._deliver_to_light(session_id="session-1", posture_state="NORMAL")
    await engine._deliver_to_light(session_id="session-1", posture_state="NORMAL")
    await engine._deliver_to_light(session_id="session-1", posture_state="STRETCH_WARNING")
    await engine._deliver_to_light(session_id="session-1", posture_state="STRETCH_WARNING")
    await engine._deliver_to_light(session_id="session-1", posture_state="TURTLE_NECK")
    await engine._deliver_to_light(session_id="session-1", posture_state="NORMAL")
    await engine._deliver_to_light(session_id="session-2", posture_state="NORMAL")

    light_commands = [
        content
        for ae, container, content in mobius.calls
        if (ae, container) == ("postureLight", "command")
    ]
    assert [command["state"] for command in light_commands] == [
        "NORMAL",
        "STRETCH_WARNING",
        "TURTLE_NECK",
        "NORMAL",
        "NORMAL",
    ]


@pytest.mark.asyncio
async def test_start_button_creates_initial_normal_light_with_zero_transition(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)

    await engine.handle_button_event(
        {
            "session_id": session["id"],
            "button": "A",
            "action": "start",
            "event_id": "start-1",
        }
    )

    command = light_commands(mobius)[-1]
    assert command["state"] == "NORMAL"
    assert command["red"] == 0
    assert command["green"] == 255
    assert command["blue"] == 0
    assert command["transition_ms"] == 0


@pytest.mark.asyncio
async def test_same_light_mode_with_different_transition_is_not_deduped(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)

    await engine._deliver_to_light(
        session_id="session-1",
        posture_state="NORMAL",
        transition_ms=0,
    )
    await engine._deliver_to_light(session_id="session-1", posture_state="NORMAL")

    commands = light_commands(mobius)
    assert [command["transition_ms"] for command in commands] == [0, 1000]


@pytest.mark.asyncio
async def test_down_position_uses_posture_based_lighting(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._desk_positions[session["id"]] = "DOWN"

    await engine._deliver_to_light(session_id=session["id"], posture_state="NORMAL")
    await engine._deliver_to_light(session_id=session["id"], posture_state="STRETCH_WARNING")
    await engine._deliver_to_light(session_id=session["id"], posture_state="TURTLE_NECK")

    commands = light_commands(mobius)
    assert [command["state"] for command in commands] == [
        "NORMAL",
        "STRETCH_WARNING",
        "TURTLE_NECK",
    ]
    assert commands[0]["green"] == 255
    assert commands[1]["red"] == 255
    assert commands[1]["transition_ms"] == 5000
    assert commands[2]["red"] == 255


@pytest.mark.asyncio
async def test_moving_up_normal_posture_does_not_turn_light_green(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._desk_positions[session["id"]] = "MOVING_UP"

    await engine._deliver_to_light(session_id=session["id"], posture_state="TURTLE_NECK")
    await engine._deliver_to_light(session_id=session["id"], posture_state="NORMAL")

    commands = light_commands(mobius)
    assert len(commands) == 1
    assert commands[0]["state"] == "TURTLE_NECK"
    assert commands[0]["red"] == 255


@pytest.mark.asyncio
async def test_moving_up_forces_red_even_when_latest_posture_is_normal(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._desk_positions[session["id"]] = "MOVING_UP"

    await engine._deliver_to_light(session_id=session["id"], posture_state="NORMAL")

    command = light_commands(mobius)[-1]
    assert command["state"] == "TURTLE_NECK"
    assert command["red"] == 255
    assert command["green"] == 0


@pytest.mark.asyncio
async def test_up_status_creates_desk_up_green_command(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._last_posture_state[session["id"]] = "TURTLE_NECK"

    await engine.handle_motor_status({"state": "UP", "position": "UP"}, session["id"])

    command = light_commands(mobius)[-1]
    assert command["state"] == "DESK_UP"
    assert command["green"] == 255
    assert command["transition_ms"] == 1000


@pytest.mark.asyncio
async def test_up_position_ignores_warning_and_turtle_light_states(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._desk_positions[session["id"]] = "UP"

    await engine._deliver_to_light(session_id=session["id"], posture_state="STRETCH_WARNING")
    await engine._deliver_to_light(session_id=session["id"], posture_state="TURTLE_NECK")

    commands = light_commands(mobius)
    assert len(commands) == 1
    assert commands[0]["state"] == "DESK_UP"
    assert commands[0]["green"] == 255


@pytest.mark.asyncio
async def test_moving_down_keeps_green_light(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._desk_positions[session["id"]] = "MOVING_DOWN"

    await engine._deliver_to_light(session_id=session["id"], posture_state="TURTLE_NECK")

    command = light_commands(mobius)[-1]
    assert command["state"] == "DESK_UP"
    assert command["green"] == 255


@pytest.mark.asyncio
async def test_down_completion_resumes_latest_posture_lighting(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)

    for posture_state, expected_light_state in [
        ("NORMAL", "NORMAL"),
        ("STRETCH_WARNING", "STRETCH_WARNING"),
        ("TURTLE_NECK", "TURTLE_NECK"),
    ]:
        engine._last_light_state.clear()
        engine._last_posture_state[session["id"]] = posture_state
        await engine.handle_motor_status(
            {"state": "DOWN", "position": "DOWN"},
            session["id"],
        )
        assert light_commands(mobius)[-1]["state"] == expected_light_state


@pytest.mark.asyncio
async def test_down_completion_after_desk_up_resumes_warning_fade(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._last_posture_state[session["id"]] = "STRETCH_WARNING"

    await engine.handle_motor_status({"state": "UP", "position": "UP"}, session["id"])
    await engine.handle_motor_status({"state": "DOWN", "position": "DOWN"}, session["id"])

    commands = light_commands(mobius)
    assert commands[-2]["state"] == "DESK_UP"
    assert commands[-1]["state"] == "STRETCH_WARNING"
    assert commands[-1]["transition_ms"] == 5000


@pytest.mark.asyncio
async def test_second_up_completion_creates_green_again_after_warning_cycle(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._last_posture_state[session["id"]] = "TURTLE_NECK"

    await engine.handle_motor_status({"state": "UP", "position": "UP"}, session["id"])
    await engine.handle_motor_status({"state": "DOWN", "position": "DOWN"}, session["id"])
    await engine.handle_motor_status({"state": "UP", "position": "UP"}, session["id"])

    commands = light_commands(mobius)
    assert [command["state"] for command in commands] == [
        "DESK_UP",
        "TURTLE_NECK",
        "DESK_UP",
    ]


@pytest.mark.asyncio
async def test_duplicate_desk_up_light_command_is_skipped(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._desk_positions[session["id"]] = "UP"

    await engine._deliver_to_light(session_id=session["id"], posture_state="NORMAL")
    await engine._deliver_to_light(session_id=session["id"], posture_state="STRETCH_WARNING")

    commands = light_commands(mobius)
    assert len(commands) == 1
    assert commands[0]["state"] == "DESK_UP"


@pytest.mark.asyncio
async def test_lighting_failure_does_not_block_normal_lcd_delivery(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    await add_samples(store, session["id"], 6, 3, 90)
    mobius = FailLightMobius()
    engine = SuggestionEngine(Settings(posture_min_samples=5), store, mobius)

    result, suggestion_event = await engine.analyze(session["id"])

    assert result.model == "posture-v1"
    assert suggestion_event is None
    assert [(ae, cnt) for ae, cnt, _ in mobius.calls] == [
        ("deskInterface", "lcdCommand"),
    ]


@pytest.mark.asyncio
async def test_motor_command_failure_does_not_update_position(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    mobius = FailMotorMobius()
    engine = SuggestionEngine(Settings(), store, mobius)
    engine._last_posture_state[session["id"]] = "STRETCH_WARNING"

    with pytest.raises(MobiusError):
        await engine.handle_button_event(
            {"session_id": session["id"], "button": "B", "event_id": "motor-fail"}
        )

    assert engine._desk_position(session["id"]) == "DOWN"
