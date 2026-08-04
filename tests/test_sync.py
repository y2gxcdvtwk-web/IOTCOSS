from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.mobius import MobiusClient
from app.store import SessionStore
from app.sync import AnalyticsSynchronizer


def test_blank_environment_keeps_api_key_blank(monkeypatch):
    monkeypatch.setenv("MOBIUS_API_KEY", "")
    monkeypatch.setenv("MOBIUS_LECTURE", "")
    monkeypatch.setenv("MOBIUS_CREATOR", "")
    settings = Settings()
    assert settings.mobius_api_key == ""
    assert settings.mobius_lecture == "LCT_20260002"
    assert settings.mobius_creator == "sjuADDHD"


@pytest.mark.asyncio
async def test_restore_rebuilds_sqlite_cache_from_ae(tmp_path: Path):
    session = {
        "id": "session-1",
        "user_id": "posture-camera-01",
        "status": "closed",
        "metadata": {"device_id": "posture-camera-01"},
        "created_at": "2026-07-22T00:00:00+00:00",
        "updated_at": "2026-07-22T00:10:00+00:00",
        "expires_at": "2026-07-23T00:00:00+00:00",
    }
    event = {
        "id": "event-1",
        "session_id": "session-1",
        "type": "postureSamples",
        "content": {"mCRA": 115.0, "neck_forward": True},
        "source": "postureCamera/postureSamples",
        "created_at": "2026-07-22T00:01:00+00:00",
        "mobius_resource_name": "cin-1",
    }

    class FakeMobius:
        async def list_content_instances(self, ae_name, container):
            return {
                "currentSession": [],
                "sessionSummaries": [{"rn": "summary-1", "con": session}],
                "sessionEvents": [{"rn": "cin-1", "con": {"event": event}}],
                "suggestions": [],
            }[container]

    store = SessionStore(tmp_path / "cache.db", 86_400)
    await store.initialize()
    counts = await AnalyticsSynchronizer(FakeMobius(), store).restore()

    assert counts["sessions"] == 1
    assert counts["events"] == 1
    assert (await store.get_session("session-1"))["status"] == "closed"
    assert (await store.list_events("session-1"))[0]["content"]["mCRA"] == 115.0


@pytest.mark.asyncio
async def test_restore_preserves_structured_suggestion_for_cooldown(tmp_path: Path):
    session = {
        "id": "session-1",
        "user_id": "device",
        "status": "active",
        "metadata": {},
        "created_at": "2026-07-22T00:00:00+00:00",
        "updated_at": "2026-07-22T00:00:00+00:00",
        "expires_at": "2027-07-22T00:00:00+00:00",
    }
    suggestion = {
        "suggestion_id": "suggestion-1",
        "session_id": "session-1",
        "type": "POSTURE_CORRECTION",
        "status": "delivered",
    }

    class FakeMobius:
        async def list_content_instances(self, ae_name, container):
            return {
                "currentSession": [{"con": session}],
                "sessionSummaries": [],
                "sessionEvents": [],
                "suggestions": [
                    {
                        "rn": "suggestion-cin-1",
                        "ct": "2026-07-22T00:01:00+00:00",
                        "con": suggestion,
                    }
                ],
            }[container]

    store = SessionStore(tmp_path / "cache.db", 86_400)
    await store.initialize()
    await AnalyticsSynchronizer(FakeMobius(), store).restore()
    events = await store.list_events("session-1")

    assert events[0]["type"] == "suggestion"
    assert events[0]["content"]["suggestion_id"] == "suggestion-1"


@pytest.mark.asyncio
async def test_existing_subscription_notification_uri_is_updated():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                request=request,
                json={"m2m:sub": {"nu": ["https://old.example/notify"]}},
            )
        return httpx.Response(200, request=request, json={"m2m:sub": {}})

    settings = Settings(
        mobius_notification_uri="https://analytics.example/api/v1/mobius/notifications"
    )
    client = MobiusClient(settings)
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url=settings.mobius_base_url,
        transport=httpx.MockTransport(handler),
    )

    await client._ensure_subscription("postureCamera", "postureSamples")
    await client.close()

    assert [request.method for request in calls] == ["GET", "PUT"]
    assert b"https://analytics.example/api/v1/mobius/notifications" in calls[1].content


@pytest.mark.asyncio
async def test_subscription_lookup_retries_iotcoss_non_unique_error():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(
                400,
                request=request,
                text="Query did not return a unique result: 9 results were returned",
            )
        return httpx.Response(
            200,
            request=request,
            json={
                "m2m:sub": {
                    "nu": ["https://analytics.example/api/v1/mobius/notifications"]
                }
            },
        )

    settings = Settings(
        mobius_notification_uri="https://analytics.example/api/v1/mobius/notifications",
        mobius_read_retry_delay_seconds=0,
    )
    client = MobiusClient(settings)
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url=settings.mobius_base_url,
        transport=httpx.MockTransport(handler),
    )

    await client._ensure_subscription("postureCamera", "postureSamples")
    await client.close()

    assert [request.method for request in calls] == ["GET", "GET", "GET"]
