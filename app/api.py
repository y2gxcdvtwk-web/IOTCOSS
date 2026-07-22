from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status

from app.mobius import MobiusError
from app.models import (
    AnalysisRequest, AnalysisResult, DeviceCommand, EventCreate, EventView, MobiusIngest,
    SessionCreate, SessionView,
)
from app.topology import ANALYTICS_AE, COMMAND_TARGETS, MOBIUS_TOPOLOGY

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
    identity = payload.user_id or str(payload.metadata.get("device_id") or "device")
    session = await request.app.state.store.create_session(identity, payload.metadata)
    try:
        await request.app.state.mobius.create_content_instance(
            ANALYTICS_AE, "currentSession", session
        )
    except MobiusError:
        pass
    return session


async def _existing_session_or_404(request: Request, session_id: str) -> dict:
    session = await request.app.state.store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions", response_model=list[SessionView])
async def list_sessions(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    session_status: str | None = Query(default=None, alias="status"),
):
    if session_status not in (None, "active", "closed", "expired"):
        raise HTTPException(status_code=422, detail="Invalid session status")
    return await request.app.state.store.list_sessions(limit, session_status)


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
    try:
        await request.app.state.mobius.create_content_instance(
            ANALYTICS_AE, "sessionSummaries", session
        )
        await request.app.state.mobius.create_content_instance(
            ANALYTICS_AE, "currentSession", session
        )
    except MobiusError:
        pass
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
            resource_name = await request.app.state.mobius.create_content_instance(
                ANALYTICS_AE, "sessionEvents", mobius_content
            )
        except MobiusError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    event = await request.app.state.store.add_event(
        session_id, payload.type, payload.content, payload.source, resource_name
    )
    await request.app.state.realtime.broadcast(session_id, {"event": "created", "data": event})
    return event


@router.get("/sessions/{session_id}/events", response_model=list[EventView])
async def list_events(session_id: str, request: Request, limit: int = Query(100, ge=1, le=500)):
    await _existing_session_or_404(request, session_id)
    return await request.app.state.store.list_events(session_id, limit)


@router.post("/sessions/{session_id}/analysis", response_model=AnalysisResult)
async def analyze(session_id: str, payload: AnalysisRequest, request: Request):
    await _existing_session_or_404(request, session_id)
    parts: list[str] = []
    if payload.include_session_events:
        events = await request.app.state.store.list_events(session_id, 200)
        parts.extend(str(event["content"]) for event in events)
    if payload.text:
        parts.append(payload.text)
    if not parts:
        raise HTTPException(status_code=422, detail="No content to analyze")
    result = await request.app.state.analyzer.analyze("\n".join(parts))
    try:
        await request.app.state.mobius.create_content_instance(
            ANALYTICS_AE,
            "suggestions",
            {"session_id": session_id, **result.model_dump()},
        )
    except MobiusError:
        pass
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


@router.post("/devices/{device}/commands", status_code=201)
async def send_device_command(device: str, payload: DeviceCommand, request: Request):
    target = COMMAND_TARGETS.get(device)
    if not target:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown device. Use one of: {', '.join(COMMAND_TARGETS)}",
        )
    try:
        resource_name = await request.app.state.mobius.create_content_instance(
            target[0], target[1], payload.content
        )
    except MobiusError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "device": device,
        "target": f"/{target[0]}/{target[1]}",
        "resource_name": resource_name,
    }


@router.post("/mobius/notifications", status_code=200)
async def receive_notification(request: Request, payload: dict[str, Any] = Body(...)):
    signal = payload.get("m2m:sgn", payload)
    if signal.get("vrq"):
        return {}

    representation = signal.get("nev", {}).get("rep", {})
    cin = representation.get("m2m:cin", representation)
    content = cin.get("con") if isinstance(cin, dict) else None
    if content is None:
        raise HTTPException(status_code=400, detail="Notification has no m2m:cin content")

    subscription_ref = str(signal.get("sur", "")).strip("/")
    parts = subscription_ref.split("/")
    ae_index = next(
        (index for index, part in enumerate(parts) if part in MOBIUS_TOPOLOGY),
        -1,
    )
    ae_name = parts[ae_index] if ae_index >= 0 else "mobius"
    container = (
        parts[ae_index + 1] if ae_index >= 0 and len(parts) > ae_index + 1
        else "deviceEvent"
    )
    source = f"{ae_name}/{container}" if ae_index >= 0 else "mobius"

    session_id = content.get("session_id") if isinstance(content, dict) else None
    session = (
        await request.app.state.store.get_session(session_id) if session_id else None
    )
    if not session or session["status"] != "active":
        session = await request.app.state.store.get_latest_active_session()
    if not session:
        session = await request.app.state.store.create_session(
            "mobius-device", {"origin": source}
        )
        try:
            await request.app.state.mobius.create_content_instance(
                ANALYTICS_AE, "currentSession", session
            )
        except MobiusError:
            pass

    event = await request.app.state.store.add_event(
        session["id"],
        container,
        content,
        source,
        cin.get("rn") if isinstance(cin, dict) else None,
    )
    try:
        await request.app.state.mobius.create_content_instance(
            ANALYTICS_AE, "sessionEvents", {"event": event}
        )
    except MobiusError:
        # The notification is still acknowledged to prevent repeated delivery;
        # health/admin sync exposes reconciliation state.
        pass
    await request.app.state.realtime.broadcast(
        session["id"], {"event": "mobius-notification", "data": event}
    )
    return {}


@router.post("/admin/sync-from-ae")
async def sync_from_ae(request: Request):
    try:
        counts = await request.app.state.synchronizer.restore()
    except MobiusError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    request.app.state.sync_status = {"state": "ok", **counts}
    return request.app.state.sync_status


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

