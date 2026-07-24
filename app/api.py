from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status

from app.mobius import MobiusError
from app.models import (
    AnalysisRequest, AnalysisResult, DeviceCommand, EventCreate, EventView, MobiusIngest,
    SessionCreate, SessionView,
)
from app.topology import ANALYTICS_AE, COMMAND_TARGETS, MOBIUS_TOPOLOGY
from app.posture import normalize_posture_content

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


def _is_start_button_event(source: str, content: Any) -> bool:
    if source != "deskInterface/buttonEvents" or not isinstance(content, dict):
        return False
    action = str(content.get("action") or "").lower()
    button = str(content.get("button") or "").upper()
    return action == "start" or (button in {"A", "START", "KICKOFF"} and action in {"", "start"})


def _is_stop_button_event(source: str, content: Any) -> bool:
    if source != "deskInterface/buttonEvents" or not isinstance(content, dict):
        return False
    action = str(content.get("action") or "").lower()
    button = str(content.get("button") or "").upper()
    return button in {"A", "STOP", "END"} and action in {"stop", "end", "close"}


def _is_sessionless_device_status(source: str, content: Any) -> bool:
    if not isinstance(content, dict):
        return False
    if content.get("session_id"):
        return False
    return source in {
        "postureCamera/status",
        "deskMotor/status",
        "postureLight/status",
    }


@router.get("/sessions", response_model=list[SessionView])
async def list_sessions(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    session_status: str | None = Query(default=None, alias="status"),
):
    if session_status not in (None, "active", "closed", "expired"):
        raise HTTPException(status_code=422, detail="Invalid session status")
    return await request.app.state.store.list_sessions(limit, session_status)


@router.delete("/sessions")
async def delete_completed_sessions(
    request: Request,
    confirm: bool = Query(False),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Deletion confirmation is required")
    result = await request.app.state.store.delete_completed_session_records(
        request.app.state.suggestion_engine.moving_session_ids()
    )
    return {
        **result,
        "detail": "Completed session records deleted",
    }


@router.get("/sessions/{session_id}", response_model=SessionView)
async def get_session(session_id: str, request: Request):
    session = await request.app.state.store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/sessions/{session_id}/record")
async def delete_session_record(session_id: str, request: Request):
    session = await request.app.state.store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["status"] == "active":
        raise HTTPException(status_code=409, detail="Active session cannot be deleted")
    desk_position = request.app.state.suggestion_engine.desk_position_for_session(session_id)
    if desk_position in {"MOVING_UP", "MOVING_DOWN"}:
        raise HTTPException(status_code=409, detail="Moving session cannot be deleted")
    deleted = await request.app.state.store.delete_session_record(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "deleted": True,
        "detail": "Session record deleted",
    }


@router.delete("/sessions/{session_id}", response_model=SessionView)
async def close_session(session_id: str, request: Request):
    session = await request.app.state.store.close_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    result, _ = await request.app.state.suggestion_engine.analyze(
        session_id, deliver=False
    )
    await request.app.state.store.add_event(
        session_id, "analysis", result.model_dump(), "ai"
    )
    try:
        await request.app.state.mobius.create_content_instance(
            ANALYTICS_AE,
            "sessionSummaries",
            {**session, "analysis": result.model_dump()},
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
    session = await _existing_session_or_404(request, session_id)
    try:
        result, suggestion_event = await request.app.state.suggestion_engine.analyze(
            session_id, deliver=session["status"] == "active"
        )
    except MobiusError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    event = await request.app.state.store.add_event(
        session_id, "analysis", result.model_dump(), "ai"
    )
    await request.app.state.realtime.broadcast(session_id, {"event": "analysis", "data": event})
    if suggestion_event:
        await request.app.state.realtime.broadcast(
            session_id, {"event": "suggestion", "data": suggestion_event}
        )
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
    content = normalize_posture_content(content)

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
    print(
        "[MOBIUS]\n"
        f"source={source}\n"
        f"sur={subscription_ref}\n"
        f"content={content}"
    )

    start_button_event = _is_start_button_event(source, content)
    stop_button_event = _is_stop_button_event(source, content)
    session_id = content.get("session_id") if isinstance(content, dict) else None
    session = None
    if session_id:
        session = await request.app.state.store.get_session(session_id)
    button_event = source == "deskInterface/buttonEvents" and isinstance(content, dict)
    if _is_sessionless_device_status(source, content):
        print(f"Ignoring sessionless device status: source={source}")
        return {}
    if start_button_event:
        previous_session = session if session and session["status"] == "active" else None
        if not previous_session:
            previous_session = await request.app.state.store.get_latest_active_session()
        if previous_session:
            await request.app.state.store.close_session(previous_session["id"])
            print(
                "Closed previous active session before A/start: "
                f"{previous_session['id']}"
            )
        session = await request.app.state.store.create_session(
            "desk-interface",
            {
                "origin": source,
                "device_id": content.get("device_id") if isinstance(content, dict) else None,
                "started_by": "button_A",
                "previous_session_id": previous_session["id"] if previous_session else None,
            },
        )
        print(f"Created new session from A/start: {session['id']}")
        try:
            await request.app.state.mobius.create_content_instance(
                ANALYTICS_AE, "currentSession", session
            )
        except MobiusError:
            pass
    if stop_button_event and (not session or session["status"] != "active"):
        session = await request.app.state.store.get_latest_active_session()
    # Delayed non-start status notifications can arrive after their explicit
    # session was closed. Keep that known session instead of creating a new one.
    if button_event and not start_button_event and not stop_button_event and session and session["status"] != "active":
        session = await request.app.state.store.get_latest_active_session()
    if stop_button_event and not session:
        return {}
    if not session:
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
    if button_event and isinstance(content, dict):
        content = {**content, "session_id": session["id"]}

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
    if source == "postureCamera/postureSamples" and session["status"] == "active":
        try:
            _, suggestion_event = await request.app.state.suggestion_engine.analyze(
                session["id"], automatic=True
            )
            if suggestion_event:
                await request.app.state.realtime.broadcast(
                    session["id"], {"event": "suggestion", "data": suggestion_event}
                )
        except MobiusError:
            pass
    elif source in {"deskMotor/status", "deskMotor/motorEvents"} and isinstance(content, dict):
        await request.app.state.suggestion_engine.handle_motor_status(
            content,
            session["id"],
        )
    elif source == "deskInterface/buttonEvents" and isinstance(content, dict):
        command = None
        try:
            command = await request.app.state.suggestion_engine.handle_button_event(
                {
                    **content,
                    "session_id": session["id"],
                    "_mobius_resource_name": cin.get("rn") if isinstance(cin, dict) else None,
                }
            )
            if command:
                event_name = (
                    "motor-command"
                    if command.get("device") == "deskMotor" or command.get("action") == "set_height"
                    else "device-command"
                )
                await request.app.state.realtime.broadcast(
                    session["id"], {"event": event_name, "data": command}
                )
        except MobiusError as exc:
            print(f"Button command delivery failed: {exc}")
        if stop_button_event:
            closed_session = await request.app.state.store.close_session(session["id"])
            if closed_session:
                try:
                    await request.app.state.mobius.create_content_instance(
                        ANALYTICS_AE, "currentSession", closed_session
                    )
                except MobiusError:
                    pass
                await request.app.state.realtime.broadcast(
                    session["id"],
                    {"event": "session-closed", "data": closed_session},
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


@router.post("/admin/reconcile-subscriptions")
async def reconcile_subscriptions(request: Request):
    try:
        await request.app.state.mobius.ensure_subscriptions()
    except MobiusError as exc:
        request.app.state.subscription_status = {
            "state": "error", "detail": str(exc)
        }
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    request.app.state.subscription_status = {"state": "ok"}
    return request.app.state.subscription_status


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

