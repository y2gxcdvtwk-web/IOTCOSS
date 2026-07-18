import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(UTC)


class SessionStore:
    def __init__(self, path: Path, ttl_seconds: int):
        self.path = path
        self.ttl_seconds = ttl_seconds

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._initialize)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, status TEXT NOT NULL,
                    metadata TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, type TEXT NOT NULL,
                    content TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL,
                    mobius_resource_name TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, created_at);
                """
            )

    @staticmethod
    def _session(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["metadata"] = json.loads(item["metadata"])
        if item["status"] == "active" and datetime.fromisoformat(item["expires_at"]) <= _now():
            item["status"] = "expired"
        return item

    @staticmethod
    def _event(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["content"] = json.loads(item["content"])
        return item

    async def create_session(self, user_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._create_session, user_id, metadata)

    def _create_session(self, user_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        item = {
            "id": str(uuid4()), "user_id": user_id, "status": "active",
            "metadata": metadata, "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=self.ttl_seconds)).isoformat(),
        }
        with self._connect() as db:
            db.execute(
                "INSERT INTO sessions VALUES (:id,:user_id,:status,:metadata,:created_at,:updated_at,:expires_at)",
                {**item, "metadata": json.dumps(metadata, ensure_ascii=False)},
            )
        return item

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_session, session_id)

    def _get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            return self._session(db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())

    async def get_latest_active_session(self) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_latest_active_session)

    def _get_latest_active_session(self) -> dict[str, Any] | None:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM sessions WHERE status='active' ORDER BY updated_at DESC"
            ).fetchall()
        for row in rows:
            session = self._session(row)
            if session and session["status"] == "active":
                return session
        return None

    async def get_latest_active_session(self) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_latest_active_session)

    def _get_latest_active_session(self) -> dict[str, Any] | None:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM sessions WHERE status='active' ORDER BY updated_at DESC"
            ).fetchall()
        for row in rows:
            session = self._session(row)
            if session and session["status"] == "active":
                return session
        return None

    async def close_session(self, session_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._close_session, session_id)

    def _close_session(self, session_id: str) -> dict[str, Any] | None:
        now = _now().isoformat()
        with self._connect() as db:
            db.execute("UPDATE sessions SET status='closed', updated_at=? WHERE id=?", (now, session_id))
            return self._session(db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())

    async def add_event(
        self, session_id: str, event_type: str, content: Any, source: str,
        mobius_resource_name: str | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._add_event, session_id, event_type, content, source, mobius_resource_name
        )

    def _add_event(
        self, session_id: str, event_type: str, content: Any, source: str,
        mobius_resource_name: str | None,
    ) -> dict[str, Any]:
        item = {
            "id": str(uuid4()), "session_id": session_id, "type": event_type,
            "content": content, "source": source, "created_at": _now().isoformat(),
            "mobius_resource_name": mobius_resource_name,
        }
        with self._connect() as db:
            db.execute(
                "INSERT INTO events VALUES (:id,:session_id,:type,:content,:source,:created_at,:mobius_resource_name)",
                {**item, "content": json.dumps(content, ensure_ascii=False)},
            )
            db.execute(
                "UPDATE sessions SET updated_at=?, expires_at=? WHERE id=?",
                (_now().isoformat(), (_now() + timedelta(seconds=self.ttl_seconds)).isoformat(), session_id),
            )
        return item

    async def list_events(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_events, session_id, limit)

    def _list_events(self, session_id: str, limit: int) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [self._event(row) for row in reversed(rows)]

