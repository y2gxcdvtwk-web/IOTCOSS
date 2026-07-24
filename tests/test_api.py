import re
from pathlib import Path

import anyio
from fastapi.testclient import TestClient

from app.config import get_settings


def test_dashboard_javascript_references_existing_elements():
    static = Path(__file__).parents[1] / "app" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    javascript = (static / "app.js").read_text(encoding="utf-8")
    element_ids = set(re.findall(r'id="([^"]+)"', html))
    referenced_ids = set(re.findall(r'\$\("([^"]+)"\)', javascript))
    assert referenced_ids <= element_ids


def test_session_event_and_analysis(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as client:
        session = client.post("/api/v1/sessions", json={"user_id": "u1"}).json()
        assert session["status"] == "active"

        event = client.post(
            f"/api/v1/sessions/{session['id']}/events",
            json={"content": "오늘 집중이 잘 되었다.", "sync_to_mobius": False},
        )
        assert event.status_code == 201

        analysis = client.post(
            f"/api/v1/sessions/{session['id']}/analysis",
            json={"include_session_events": True},
        )
        assert analysis.status_code == 200
        assert analysis.json()["provider"] == "local"

        events = client.get(f"/api/v1/sessions/{session['id']}/events").json()
        assert len(events) == 2

        sessions = client.get("/api/v1/sessions").json()
        assert sessions[0]["id"] == session["id"]

        client.delete(f"/api/v1/sessions/{session['id']}")
        assert client.get(
            f"/api/v1/sessions/{session['id']}/events"
        ).status_code == 200
        assert client.post(
            f"/api/v1/sessions/{session['id']}/analysis",
            json={"include_session_events": True},
        ).status_code == 200


def test_session_can_be_created_without_user_id(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()

    async def create_content_instance(*args):
        return "cin-1"

    app.state.mobius.create_content_instance = create_content_instance
    with TestClient(app) as client:
        session = client.post(
            "/api/v1/sessions",
            json={"metadata": {"device_id": "posture-camera-01"}},
        )
        active = client.get("/api/v1/sessions?status=active")
    assert session.status_code == 201
    assert session.json()["user_id"] == "posture-camera-01"
    assert len(active.json()) == 1


def test_closed_session_record_can_be_deleted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    calls = []

    async def create_content_instance(ae_name, container, content):
        calls.append((ae_name, container, content))
        return "cin-1"

    app.state.mobius.create_content_instance = create_content_instance
    with TestClient(app) as client:
        session = client.post("/api/v1/sessions", json={"user_id": "u1"}).json()
        client.post(
            f"/api/v1/sessions/{session['id']}/events",
            json={"content": {"value": "sample"}, "sync_to_mobius": False},
        )
        client.delete(f"/api/v1/sessions/{session['id']}")
        calls.clear()

        deleted = client.delete(f"/api/v1/sessions/{session['id']}/record")

        assert deleted.status_code == 200
        assert client.get(f"/api/v1/sessions/{session['id']}").status_code == 404
        assert client.get(f"/api/v1/sessions/{session['id']}/events").status_code == 404
        assert calls == []


def test_deleted_session_record_is_not_restored_by_sync(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        session = client.post("/api/v1/sessions", json={"user_id": "u1"}).json()
        client.delete(f"/api/v1/sessions/{session['id']}")
        assert client.delete(f"/api/v1/sessions/{session['id']}/record").status_code == 200

        restored = {
            **session,
            "status": "closed",
        }
        assert anyio.run(app.state.store.upsert_session, restored) is False
        assert client.get(f"/api/v1/sessions/{session['id']}").status_code == 404


def test_missing_session_record_delete_returns_404(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as client:
        assert client.delete("/api/v1/sessions/missing/record").status_code == 404


def test_active_session_record_delete_returns_409(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as client:
        session = client.post("/api/v1/sessions", json={"user_id": "u1"}).json()
        response = client.delete(f"/api/v1/sessions/{session['id']}/record")

    assert response.status_code == 409
    assert response.json()["detail"] == "Active session cannot be deleted"


def test_bulk_delete_requires_confirmation(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as client:
        response = client.delete("/api/v1/sessions")

    assert response.status_code == 400


def test_bulk_delete_removes_only_completed_sessions(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    calls = []

    async def create_content_instance(ae_name, container, content):
        calls.append((ae_name, container, content))
        return "cin-1"

    app.state.mobius.create_content_instance = create_content_instance
    with TestClient(app) as client:
        active = client.post("/api/v1/sessions", json={"user_id": "active"}).json()
        closed = client.post("/api/v1/sessions", json={"user_id": "closed"}).json()
        other_closed = client.post("/api/v1/sessions", json={"user_id": "closed-2"}).json()
        client.post(
            f"/api/v1/sessions/{closed['id']}/events",
            json={"content": {"value": "closed"}, "sync_to_mobius": False},
        )
        client.post(
            f"/api/v1/sessions/{active['id']}/events",
            json={"content": {"value": "active"}, "sync_to_mobius": False},
        )
        client.delete(f"/api/v1/sessions/{closed['id']}")
        client.delete(f"/api/v1/sessions/{other_closed['id']}")
        calls.clear()

        deleted = client.delete("/api/v1/sessions?confirm=true").json()
        sessions = client.get("/api/v1/sessions").json()
        active_events = client.get(f"/api/v1/sessions/{active['id']}/events").json()

    assert deleted["deleted_sessions"] == 2
    assert [session["id"] for session in sessions] == [active["id"]]
    assert active_events[0]["content"]["value"] == "active"
    assert calls == []


def test_unknown_session(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as client:
        assert client.get("/api/v1/sessions/missing").status_code == 404


def test_device_command_uses_fixed_topology(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    calls = []

    async def create_content_instance(ae_name, container, content):
        calls.append((ae_name, container, content))
        return "cin-1"

    app.state.mobius.create_content_instance = create_content_instance
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/devices/desk-motor/commands",
            json={"content": {"height": 120}},
        )
    assert response.status_code == 201
    assert calls == [("deskMotor", "command", {"height": 120})]


def test_mobius_notification_is_added_to_current_session(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()

    async def create_content_instance(*args):
        return "cin-1"

    app.state.mobius.create_content_instance = create_content_instance
    with TestClient(app) as client:
        session = client.post("/api/v1/sessions", json={"user_id": "u1"}).json()
        response = client.post(
            "/api/v1/mobius/notifications",
            json={
                "m2m:sgn": {
                    "sur": "/Mobius/postureCamera/postureEvents/subToAnalyticsServer",
                    "nev": {
                        "rep": {
                            "m2m:cin": {
                                "rn": "cin-event",
                                "con": {"neck_forward": True},
                            }
                        }
                    },
                }
            },
        )
        events = client.get(
            f"/api/v1/sessions/{session['id']}/events"
        ).json()
    assert response.status_code == 200
    assert events[0]["source"] == "postureCamera/postureEvents"


def test_delayed_offline_notification_does_not_create_new_session(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()

    async def create_content_instance(*args):
        return "cin-1"

    app.state.mobius.create_content_instance = create_content_instance
    with TestClient(app) as client:
        session = client.post("/api/v1/sessions", json={}).json()
        closed = client.delete(f"/api/v1/sessions/{session['id']}").json()
        response = client.post(
            "/api/v1/mobius/notifications",
            json={
                "m2m:sgn": {
                    "sur": "/Mobius/postureCamera/status/subToAnalyticsServer",
                    "nev": {
                        "rep": {
                            "m2m:cin": {
                                "rn": "cin-offline",
                                "con": {
                                    "session_id": session["id"],
                                    "state": "offline",
                                },
                            }
                        }
                    },
                }
            },
        )
        sessions = client.get("/api/v1/sessions").json()
        events = client.get(f"/api/v1/sessions/{session['id']}/events").json()

    assert response.status_code == 200
    assert len(sessions) == 1
    assert sessions[0]["status"] == "closed"
    assert sessions[0]["updated_at"] == closed["updated_at"]
    offline = next(event for event in events if event["content"].get("state") == "offline")
    assert offline["type"] == "status"


def test_sessionless_posture_camera_status_does_not_create_session(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()

    async def create_content_instance(*args):
        return "cin-1"

    app.state.mobius.create_content_instance = create_content_instance
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/mobius/notifications",
            json={
                "m2m:sgn": {
                    "sur": "/Mobius/postureCamera/status/subToAnalyticsServer",
                    "nev": {
                        "rep": {
                            "m2m:cin": {
                                "rn": "cin-online",
                                "con": {
                                    "device_id": "posture-camera-01",
                                    "session_id": None,
                                    "state": "online",
                                },
                            }
                        }
                    },
                }
            },
        )
        sessions = client.get("/api/v1/sessions").json()

    assert response.status_code == 200
    assert sessions == []


def test_start_button_with_closed_session_id_creates_new_active_session(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()

    async def create_content_instance(*args):
        return "cin-1"

    app.state.mobius.create_content_instance = create_content_instance
    with TestClient(app) as client:
        old_session = client.post("/api/v1/sessions", json={}).json()
        client.delete(f"/api/v1/sessions/{old_session['id']}")

        response = client.post(
            "/api/v1/mobius/notifications",
            json={
                "m2m:sgn": {
                    "sur": "/Mobius/deskInterface/buttonEvents/subToAnalyticsServer",
                    "nev": {
                        "rep": {
                            "m2m:cin": {
                                "rn": "button-a-new",
                                "con": {
                                    "session_id": old_session["id"],
                                    "device_id": "desk-interface-uno-r4-01",
                                    "button": "A",
                                    "action": "start",
                                    "event": "button_pressed",
                                },
                            }
                        }
                    },
                }
            },
        )
        sessions = client.get("/api/v1/sessions").json()
        active_sessions = [
            session for session in sessions if session["status"] == "active"
        ]
        old_events = client.get(f"/api/v1/sessions/{old_session['id']}/events").json()
        new_events = client.get(
            f"/api/v1/sessions/{active_sessions[0]['id']}/events"
        ).json()

    assert response.status_code == 200
    assert len(active_sessions) == 1
    assert active_sessions[0]["id"] != old_session["id"]
    assert not any(event["source"] == "deskInterface/buttonEvents" for event in old_events)
    button_event = next(
        event for event in new_events if event["source"] == "deskInterface/buttonEvents"
    )
    assert button_event["content"]["session_id"] == active_sessions[0]["id"]


def test_stop_button_closes_session_when_command_delivery_fails(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app
    from app.mobius import MobiusError

    app = create_app()

    async def create_content_instance(ae_name, container, content):
        if ae_name == "postureCamera" and container == "command":
            raise MobiusError("camera command failed")
        return "cin-1"

    app.state.mobius.create_content_instance = create_content_instance
    with TestClient(app) as client:
        session = client.post("/api/v1/sessions", json={}).json()

        response = client.post(
            "/api/v1/mobius/notifications",
            json={
                "m2m:sgn": {
                    "sur": "/Mobius/deskInterface/buttonEvents/subToAnalyticsServer",
                    "nev": {
                        "rep": {
                            "m2m:cin": {
                                "rn": "button-a-stop",
                                "con": {
                                    "session_id": session["id"],
                                    "device_id": "desk-interface-uno-r4-01",
                                    "button": "A",
                                    "action": "stop",
                                    "event": "button_pressed",
                                },
                            }
                        }
                    },
                }
            },
        )
        stopped = client.get(f"/api/v1/sessions/{session['id']}").json()
        events = client.get(f"/api/v1/sessions/{session['id']}/events").json()

    assert response.status_code == 200
    assert stopped["status"] == "closed"
    assert any(event["source"] == "deskInterface/buttonEvents" for event in events)


def test_mcra_overrides_inverted_neck_forward_flag(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()

    async def create_content_instance(*args):
        return "cin-1"

    app.state.mobius.create_content_instance = create_content_instance
    with TestClient(app) as client:
        session = client.post("/api/v1/sessions", json={}).json()
        response = client.post(
            "/api/v1/mobius/notifications",
            json={
                "m2m:sgn": {
                    "sur": "/Mobius/postureCamera/postureSamples/subToAnalyticsServer",
                    "nev": {
                        "rep": {
                            "m2m:cin": {
                                "rn": "cin-posture",
                                "con": {
                                    "session_id": session["id"],
                                    "mCRA": 125,
                                    "neck_forward": False,
                                },
                            }
                        }
                    },
                }
            },
        )
        events = client.get(f"/api/v1/sessions/{session['id']}/events").json()

    assert response.status_code == 200
    assert events[0]["content"]["neck_forward"] is True

