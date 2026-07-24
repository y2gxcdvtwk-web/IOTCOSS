import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.config import get_settings
from app.mobius import MobiusClient, MobiusError
from app.realtime import ConnectionManager
from app.store import SessionStore
from app.sync import AnalyticsSynchronizer
from app.suggestions import SuggestionEngine


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.store.initialize()
        app.state.sync_status = {"state": "not-run"}
        app.state.subscription_status = {"state": "not-configured"}
        subscription_task = None
        if settings.mobius_auto_register:
            try:
                await app.state.mobius.ensure_analytics_structure()
                if settings.mobius_sync_on_startup:
                    counts = await app.state.synchronizer.restore()
                    app.state.sync_status = {"state": "ok", **counts}
            except Exception as exc:
                app.state.sync_status = {"state": "error", "detail": str(exc)}
            if settings.mobius_notification_uri:
                async def delayed_subscription_reconcile():
                    await asyncio.sleep(2)
                    try:
                        await app.state.mobius.ensure_subscriptions()
                        app.state.subscription_status = {"state": "ok"}
                    except Exception as exc:
                        app.state.subscription_status = {
                            "state": "error", "detail": str(exc)
                        }

                app.state.subscription_status = {"state": "pending"}
                subscription_task = asyncio.create_task(delayed_subscription_reconcile())
            else:
                app.state.subscription_status = {
                    "state": "error",
                    "detail": (
                        "MOBIUS_NOTIFICATION_URI is not configured; Mobius cannot "
                        "deliver subscription notifications to FastAPI."
                    ),
                }
        yield
        if subscription_task and not subscription_task.done():
            subscription_task.cancel()
        await app.state.mobius.close()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.store = SessionStore(settings.database_path, settings.session_ttl_seconds)
    app.state.mobius = MobiusClient(settings)
    app.state.realtime = ConnectionManager()
    app.state.synchronizer = AnalyticsSynchronizer(app.state.mobius, app.state.store)
    app.state.suggestion_engine = SuggestionEngine(
        settings, app.state.store, app.state.mobius
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix=settings.api_prefix)

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(static_dir / "index.html")

    @app.get("/health")
    async def health(request: Request):
        mobius = await request.app.state.mobius.health()
        return {
            "status": "ok",
            "mobius": "connected" if mobius else "disconnected",
            "ae_sync": request.app.state.sync_status,
            "subscriptions": request.app.state.subscription_status,
        }

    return app


app = create_app()

