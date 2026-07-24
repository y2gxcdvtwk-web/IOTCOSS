const $ = (id) => document.getElementById(id);

let selectedSessionId = null;
let selectedSession = null;
let currentFilter = "";
let socket = null;
const deletingSessionIds = new Set();
let deletingCompletedSessions = false;

async function request(path, options = {}) {
  const response = await fetch(`/api/v1${path}`, {
    headers: {"Content-Type": "application/json"},
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `요청 실패 (${response.status})`);
  }
  return response.json();
}

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = String(value);
  return node.innerHTML;
}

function formatTime(value) {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function duration(session) {
  const end = session.status === "active" ? new Date() : new Date(session.updated_at);
  const seconds = Math.max(0, Math.floor((end - new Date(session.created_at)) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes}분 ${seconds % 60}초` : `${seconds}초`;
}

function statusLabel(status) {
  return {active: "진행 중", closed: "종료", expired: "만료"}[status] || status;
}

function isNeckForward(content) {
  if (!content) return null;
  const mcra = Number(content.mCRA);
  if (content.mCRA != null && Number.isFinite(mcra)) return mcra >= 120;
  return content.neck_forward == null ? null : Boolean(content.neck_forward);
}

function renderSessions(sessions) {
  $("sessionCount").textContent = sessions.length;
  $("sessions").innerHTML = "";
  $("emptySessions").classList.toggle("hidden", sessions.length > 0);

  sessions.forEach((session) => {
    const item = document.createElement("article");
    item.className = `session-row ${session.id === selectedSessionId ? "selected" : ""}`;

    const selectButton = document.createElement("button");
    selectButton.className = "session-item";
    selectButton.innerHTML = `
      <span class="session-item-top">
        <strong>${escapeHtml(session.metadata.device_id || "postureCamera")}</strong>
        <span class="badge ${session.status}">${statusLabel(session.status)}</span>
      </span>
      <span class="session-time">${formatTime(session.created_at)}</span>
      <span class="session-id">${session.id.slice(0, 8)} · ${duration(session)}</span>
    `;
    selectButton.onclick = () => selectSession(session);

    const deleteButton = document.createElement("button");
    deleteButton.className = "delete-session secondary danger";
    deleteButton.textContent = "삭제";
    deleteButton.disabled = session.status === "active" || deletingSessionIds.has(session.id);
    deleteButton.title = session.status === "active"
      ? "활성 세션은 삭제할 수 없습니다."
      : "세션 기록 삭제";
    deleteButton.onclick = () => deleteSessionRecord(session, deleteButton);

    item.appendChild(selectButton);
    item.appendChild(deleteButton);
    $("sessions").appendChild(item);
  });
}

async function loadSessions(preserveSelection = true) {
  try {
    const query = currentFilter ? `?status=${currentFilter}` : "";
    const sessions = await request(`/sessions${query}`);
    $("status").textContent = `최근 업데이트 ${new Date().toLocaleTimeString("ko-KR")}`;
    renderSessions(sessions);

    if (!preserveSelection && sessions.length) {
      await selectSession(sessions[0]);
    }

    if (preserveSelection && selectedSessionId) {
      const refreshed = sessions.find((item) => item.id === selectedSessionId);
      if (refreshed) {
        selectedSession = refreshed;
        renderSessionHeader();
      } else {
        clearSelection();
      }
    }
  } catch (error) {
    $("status").textContent = error.message;
  }
}

function clearSelection() {
  selectedSessionId = null;
  selectedSession = null;
  socket?.close();
  $("sessionDetail").classList.add("hidden");
  $("emptyDetail").classList.remove("hidden");
}

function renderSessionHeader() {
  $("detailTitle").textContent = selectedSession.metadata.device_id || "postureCamera";
  $("detailBadge").textContent = statusLabel(selectedSession.status);
  $("detailBadge").className = `badge ${selectedSession.status}`;
  $("detailMeta").textContent =
    `${formatTime(selectedSession.created_at)} 시작 · ${duration(selectedSession)} · ${selectedSession.id}`;
}

async function selectSession(session) {
  selectedSession = session;
  selectedSessionId = session.id;
  $("emptyDetail").classList.add("hidden");
  $("sessionDetail").classList.remove("hidden");
  $("analysisPanel").classList.add("hidden");
  renderSessionHeader();
  await loadEvents();
  $("events").scrollIntoView({
    behavior: "smooth",
    block: "start",
  });
  connectSocket();
  await loadSessions(true);
}

async function loadEvents() {
  try {
    const events = await request(`/sessions/${selectedSessionId}/events?limit=500`);
    renderEvents(events);
  } catch (error) {
    $("status").textContent = error.message;
  }
}

function renderEvents(events) {
  $("events").innerHTML = "";
  $("eventCount").textContent = events.length;
  $("emptyEvents").classList.toggle("hidden", events.length > 0);

  const metricEvents = events.filter((event) => (
    event.content && typeof event.content === "object" &&
    (event.content.mCRA != null || event.content.neck_forward != null)
  ));
  const latest = [...metricEvents].reverse().find((event) => (
    event.content && typeof event.content === "object"
  ));

  $("latestMcra").textContent = latest?.content?.mCRA == null ? "--" : `${latest.content.mCRA}°`;
  const latestNeckForward = isNeckForward(latest?.content);
  $("latestPosture").textContent =
    latestNeckForward == null ? "--" : latestNeckForward ? "거북목" : "정상";

  [...events].reverse().forEach(renderEvent);
}

function renderEvent(item) {
  const content = item.content && typeof item.content === "object" ? item.content : {value: item.content};
  const row = document.createElement("article");
  row.className = "event-row";
  const neckForward = isNeckForward(content);
  const posture = neckForward == null ? "" :
    `<span class="posture ${neckForward ? "bad" : "good"}">${neckForward ? "거북목" : "정상"}</span>`;
  const mcra = content.mCRA == null ? "" : `<strong>${content.mCRA}°</strong>`;
  const summary = eventSummary(item, content);

  row.innerHTML = `
    <div class="event-dot"></div>
    <div class="event-body">
      <div class="event-top">
        <span>${escapeHtml(item.type)}</span>
        <time>${formatTime(item.created_at)}</time>
      </div>
      <div class="event-value">${mcra}${posture}${summary}</div>
      <div class="event-source">${escapeHtml(item.source)}</div>
    </div>
  `;
  $("events").appendChild(row);
}

function eventSummary(item, content) {
  if (content.mCRA != null || content.neck_forward != null) return "";
  if (item.type === "buttonEvents") {
    const button = content.button ? `button ${content.button}` : "button";
    const action = content.action || content.event || "pressed";
    return `<span>${escapeHtml(`${button} · ${action}`)}</span>`;
  }
  if (item.type === "suggestion") {
    const title = content.title || content.type || "suggestion";
    const message = content.message || content.reason || content.status || "";
    return `<span>${escapeHtml(message ? `${title} · ${message}` : title)}</span>`;
  }
  if (item.type === "analysis") {
    const summary = content.summary || content.recommendations?.[0] || "analysis";
    return `<span>${escapeHtml(summary)}</span>`;
  }
  const value = content.value == null ? JSON.stringify(content) : content.value;
  return `<span>${escapeHtml(value)}</span>`;
}

function connectSocket() {
  socket?.close();
  if (!selectedSessionId || selectedSession.status !== "active") {
    $("liveState").textContent = "세션 종료";
    return;
  }

  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/api/v1/ws/sessions/${selectedSessionId}`);
  socket.onopen = () => $("liveState").textContent = "실시간 연결";
  socket.onclose = () => $("liveState").textContent = "연결 대기";
  socket.onmessage = async () => {
    await loadEvents();
    await loadSessions(true);
  };
}

async function deleteSessionRecord(session, button) {
  if (!confirm("이 세션 기록을 삭제하시겠습니까?")) return;

  deletingSessionIds.add(session.id);
  button.disabled = true;
  try {
    await request(`/sessions/${session.id}/record`, {method: "DELETE"});
    $("status").textContent = "세션이 삭제되었습니다.";
    if (selectedSessionId === session.id) {
      clearSelection();
    }
    await loadSessions(false);
  } catch (error) {
    $("status").textContent = error.message;
  } finally {
    deletingSessionIds.delete(session.id);
  }
}

async function deleteCompletedSessions() {
  if (!confirm("저장된 세션 기록을 모두 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.")) return;

  const button = $("clearCompletedSessions");
  deletingCompletedSessions = true;
  button.disabled = true;
  try {
    const result = await request("/sessions?confirm=true", {method: "DELETE"});
    $("status").textContent =
      `종료된 테스트 세션이 모두 삭제되었습니다. (${result.deleted_sessions}개 세션, ${result.deleted_events}개 이벤트)`;
    if (selectedSession && selectedSession.status !== "active") {
      clearSelection();
    }
    await loadSessions(false);
  } catch (error) {
    $("status").textContent = error.message;
  } finally {
    deletingCompletedSessions = false;
    button.disabled = false;
  }
}

$("analyze").onclick = async () => {
  if (!selectedSessionId) return;

  $("analyze").disabled = true;
  $("analyze").textContent = "분석 중";
  try {
    const result = await request(`/sessions/${selectedSessionId}/analysis`, {
      method: "POST",
      body: JSON.stringify({include_session_events: true}),
    });
    $("analysisSummary").textContent = result.summary;
    $("recommendations").innerHTML = "";
    result.recommendations.forEach((text) => {
      const item = document.createElement("li");
      item.textContent = text;
      $("recommendations").appendChild(item);
    });
    $("analysisPanel").classList.remove("hidden");
  } catch (error) {
    $("status").textContent = error.message;
  } finally {
    $("analyze").disabled = false;
    $("analyze").textContent = "AI 분석";
  }
};

$("refresh").onclick = async () => {
  await loadSessions(true);
  if (selectedSessionId) await loadEvents();
};

$("clearCompletedSessions").onclick = deleteCompletedSessions;

document.querySelectorAll(".filter").forEach((button) => {
  button.onclick = async () => {
    document.querySelectorAll(".filter").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    currentFilter = button.dataset.status;
    await loadSessions(false);
  };
});

loadSessions(false);
setInterval(() => {
  if (!deletingCompletedSessions) loadSessions(true);
}, 5000);
