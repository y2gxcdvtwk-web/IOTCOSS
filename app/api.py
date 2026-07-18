from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status

from app.mobius import MobiusError
from app.models import (
    AnalysisRequest, AnalysisResult, EventCreate, EventView, MobiusIngest,
    SessionCreate, SessionView,
)

router = APIRouter()


async def _session_or_404(request: Request, session_id: str) -> dict:
    session = await request.app.state.store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["status"] != "active":
        raise HTTPException(status_code=409, detail=f"Session is {session['status']}")
    return session


@router.post("/sessions", response_model=SessionView, status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreate, request: Request):
    return await request.app.state.store.create_session(payload.user_id, payload.metadata)


@router.get("/sessions/{session_id}", response_model=SessionView)
async def get_session(session_id: str, request: Request):
    session = await request.app.state.store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/sessions/{session_id}", response_model=SessionView)
async def close_session(session_id: str, request: Request):
    session = await request.app.state.store.close_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/sessions/{session_id}/events", response_model=EventView, status_code=201)
async def create_event(session_id: str, payload: EventCreate, request: Request):
    await _session_or_404(request, session_id)
    resource_name = None
    if payload.sync_to_mobius:
        if isinstance(payload.content, dict):
            mobius_content = {
                **payload.content,
                "session_id": session_id,
                "event_type": payload.type,
                "source": payload.source,
            }
        else:
            mobius_content = {
                "value": payload.content,
                "session_id": session_id,
                "event_type": payload.type,
                "source": payload.source,
            }
        try:
            resource_name = await request.app.state.mobius.create_content_instance(mobius_content)
        except MobiusError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    event = await request.app.state.store.add_event(
        session_id, payload.type, payload.content, payload.source, resource_name
    )
    await request.app.state.realtime.broadcast(session_id, {"event": "created", "data": event})
    return event


@router.get("/sessions/{session_id}/events", response_model=list[EventView])
async def list_events(session_id: str, request: Request, limit: int = Query(100, ge=1, le=500)):
    await _session_or_404(request, session_id)
    return await request.app.state.store.list_events(session_id, limit)


@router.post("/sessions/{session_id}/analysis", response_model=AnalysisResult)
async def analyze(session_id: str, payload: AnalysisRequest, request: Request):
    await _session_or_404(request, session_id)
    parts: list[str] = []
    if payload.include_session_events:
        events = await request.app.state.store.list_events(session_id, 200)
        parts.extend(str(event["content"]) for event in events)
    if payload.text:
        parts.append(payload.text)
    if not parts:
        raise HTTPException(status_code=422, detail="No content to analyze")
    result = await request.app.state.analyzer.analyze("\n".join(parts))
    event = await request.app.state.store.add_event(
        session_id, "analysis", result.model_dump(), "ai"
    )
    await request.app.state.realtime.broadcast(session_id, {"event": "analysis", "data": event})
    return result


@router.post("/mobius/ingest", response_model=EventView, status_code=201)
async def ingest(payload: MobiusIngest, request: Request):
    session_id = payload.session_id
    if not session_id:
        session = await request.app.state.store.create_session("mobius", {"origin": "mobius"})
        session_id = session["id"]
    else:
        await _session_or_404(request, session_id)
    event = await request.app.state.store.add_event(
        session_id, "sensor", payload.content, "mobius", payload.resource_name
    )
    await request.app.state.realtime.broadcast(session_id, {"event": "ingested", "data": event})
    return event


@router.websocket("/ws/sessions/{session_id}")
async def session_socket(websocket: WebSocket, session_id: str):
    manager = websocket.app.state.realtime
    session = await websocket.app.state.store.get_session(session_id)
    if not session or session["status"] != "active":
        await websocket.close(code=4404)
        return
    await manager.connect(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)

