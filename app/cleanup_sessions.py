from __future__ import annotations

import argparse
import asyncio

from app.config import get_settings
from app.store import SessionStore


async def _cleanup_completed_sessions(confirm: bool) -> int:
    if not confirm:
        print("Refusing to delete without --confirm.")
        return 2

    settings = get_settings()
    store = SessionStore(settings.database_path, settings.session_ttl_seconds)
    await store.initialize()
    result = await store.delete_completed_session_records()
    print(
        "Deleted completed session records: "
        f"sessions={result['deleted_sessions']}, "
        f"events={result['deleted_events']}, "
        f"kept_active={result['kept_active_sessions']}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safely remove completed local web-app session records."
    )
    parser.add_argument(
        "--completed-only",
        action="store_true",
        help="Delete only closed or expired local sessions and their local events.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required confirmation flag for deletion.",
    )
    args = parser.parse_args()

    if not args.completed_only:
        parser.error("Only --completed-only cleanup is supported.")

    raise SystemExit(asyncio.run(_cleanup_completed_sessions(args.confirm)))


if __name__ == "__main__":
    main()
