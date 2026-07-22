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


async def add_samples(store, session_id, count, interval_seconds, mcra):
    started = datetime.now(UTC) - timedelta(seconds=count * interval_seconds)
    for index in range(count):
        measured_at = started + timedelta(seconds=index * interval_seconds)
        await store.add_event(
            session_id,
            "postureSamples",
            {"mCRA": mcra, "measured_at": measured_at.isoformat()},
            "postureCamera/postureSamples",
        )


def test_posture_metrics_use_120_degree_threshold():
    now = datetime.now(UTC)
    events = [
        {
            "type": "postureSamples",
            "source": "postureCamera/postureSamples",
            "created_at": (now + timedelta(seconds=index)).isoformat(),
            "content": {"mCRA": mcra},
        }
        for index, mcra in enumerate((119, 120, 125))
    ]
    metrics = calculate_posture_metrics(events)
    assert metrics["valid_sample_count"] == 3
    assert metrics["forward_sample_ratio"] == pytest.approx(0.667, abs=0.001)


@pytest.mark.asyncio
async def test_actionable_analysis_creates_suggestion_and_lcd_command(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    await add_samples(store, session["id"], 6, 3, 125)
    mobius = FakeMobius()
    engine = SuggestionEngine(
        Settings(posture_min_samples=5, posture_suggestion_cooldown_seconds=180),
        store,
        mobius,
    )

    result, suggestion_event = await engine.analyze(session["id"])

    assert result.model == "posture-v1"
    assert suggestion_event["content"]["type"] == "POSTURE_CORRECTION"
    assert [(ae, cnt) for ae, cnt, _ in mobius.calls] == [
        ("analyticsServer", "suggestions"),
        ("deskInterface", "lcdCommand"),
    ]
    assert mobius.calls[1][2]["suggestion_id"] == suggestion_event["content"]["suggestion_id"]

    _, duplicate = await engine.analyze(session["id"])
    assert duplicate is None
    assert len(mobius.calls) == 2


@pytest.mark.asyncio
async def test_accepted_height_suggestion_creates_one_motor_command(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    await add_samples(store, session["id"], 26, 5, 130)
    mobius = FakeMobius()
    engine = SuggestionEngine(Settings(posture_min_samples=5), store, mobius)
    _, suggestion_event = await engine.analyze(session["id"])
    suggestion = suggestion_event["content"]
    assert suggestion["type"] == "DESK_HEIGHT_CHANGE"

    button = {
        "session_id": session["id"],
        "button": "B",
    }
    command = await engine.handle_button_event(button)
    duplicate = await engine.handle_button_event(button)

    assert command["target_height_cm"] == 125
    assert duplicate is None
    assert [(ae, cnt) for ae, cnt, _ in mobius.calls][-2:] == [
        ("deskMotor", "command"),
        ("analyticsServer", "suggestions"),
    ]


@pytest.mark.asyncio
async def test_proposed_suggestion_retries_lcd_delivery_without_duplicate(tmp_path: Path):
    store = SessionStore(tmp_path / "test.db", 86_400)
    await store.initialize()
    session = await store.create_session("device", {})
    await add_samples(store, session["id"], 6, 3, 125)
    mobius = FailLcdOnceMobius()
    engine = SuggestionEngine(Settings(posture_min_samples=5), store, mobius)

    with pytest.raises(MobiusError):
        await engine.analyze(session["id"])
    _, delivered = await engine.analyze(session["id"])

    assert delivered["content"]["status"] == "delivered"
    assert [(ae, cnt) for ae, cnt, _ in mobius.calls] == [
        ("analyticsServer", "suggestions"),
        ("deskInterface", "lcdCommand"),
    ]
