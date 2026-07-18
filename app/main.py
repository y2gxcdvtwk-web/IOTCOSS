from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.analysis import Analyzer
from app.api import router
from app.config import get_settings
from app.mobius import MobiusClient, MobiusError
from app.realtime import ConnectionManager
from app.store import SessionStore


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.store.initialize()
        if settings.mobius_auto_register:
            try:
                await app.state.mobius.ensure_structure()
            except Exception:
                pass  # health endpoint exposes the disconnected state; local workflows remain available.
        yield
        await app.state.mobius.close()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.store = SessionStore(settings.database_path, settings.session_ttl_seconds)
    app.state.mobius = MobiusClient(settings)
    app.state.analyzer = Analyzer(settings)
    app.state.realtime = ConnectionManager()
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
        return {"status": "ok", "mobius": "connected" if mobius else "disconnected"}

    return app


app = create_app()

