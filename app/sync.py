from typing import Any

from app.mobius import MobiusClient
from app.posture import normalize_posture_content
from app.store import SessionStore
from app.topology import ANALYTICS_AE


class AnalyticsSynchronizer:
    """Rebuilds the SQLite read cache from the canonical analyticsServer AE."""

    def __init__(self, mobius: MobiusClient, store: SessionStore):
        self.mobius = mobius
        self.store = store

    async def restore(self) -> dict[str, int]:
        counts = {"sessions": 0, "events": 0, "suggestions": 0}
        # Summaries are processed last so a closed snapshot overrides an older active snapshot.
        for container in ("currentSession", "sessionSummaries"):
            for cin in await self.mobius.list_content_instances(ANALYTICS_AE, container):
                content = cin.get("con")
                if isinstance(content, dict) and await self.store.upsert_session(content):
                    counts["sessions"] += 1

        for cin in await self.mobius.list_content_instances(ANALYTICS_AE, "sessionEvents"):
            event = self._event_from_cin(cin)
            if event and await self.store.upsert_event(event):
                counts["events"] += 1

        for cin in await self.mobius.list_content_instances(ANALYTICS_AE, "suggestions"):
            content = cin.get("con")
            if not isinstance(content, dict) or not content.get("session_id"):
                continue
            event = {
                "id": f"suggestion:{cin.get('rn', cin.get('ri', 'unknown'))}",
                "session_id": content["session_id"],
                "type": "analysis",
                "content": {key: value for key, value in content.items() if key != "session_id"},
                "source": "ai",
                "created_at": cin.get("ct") or cin.get("lt"),
                "mobius_resource_name": cin.get("rn"),
            }
            if event["created_at"] and await self.store.upsert_event(event):
                counts["suggestions"] += 1
        return counts

    @staticmethod
    def _event_from_cin(cin: dict[str, Any]) -> dict[str, Any] | None:
        content = cin.get("con")
        if not isinstance(content, dict):
            return None
        if isinstance(content.get("event"), dict):
            event = {**content["event"], "mobius_resource_name": cin.get("rn")}
            event["content"] = normalize_posture_content(event.get("content"))
            return event
        # Compatibility with events written before the canonical envelope was introduced.
        session_id = content.get("session_id")
        if not session_id:
            return None
        excluded = {"session_id", "event_type", "source"}
        return {
            "id": f"mobius:{cin.get('rn', cin.get('ri', 'unknown'))}",
            "session_id": session_id,
            "type": content.get("event_type", "sensor"),
            "content": normalize_posture_content(
                {key: value for key, value in content.items() if key not in excluded}
            ),
            "source": content.get("source", "mobius"),
            "created_at": cin.get("ct") or cin.get("lt"),
            "mobius_resource_name": cin.get("rn"),
        }
