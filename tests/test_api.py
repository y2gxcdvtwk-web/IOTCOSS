from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings


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


def test_unknown_session(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOBIUS_AUTO_REGISTER", "false")
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as client:
        assert client.get("/api/v1/sessions/missing").status_code == 404

