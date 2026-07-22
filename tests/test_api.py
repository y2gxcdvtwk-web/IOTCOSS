import re
from pathlib import Path

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

