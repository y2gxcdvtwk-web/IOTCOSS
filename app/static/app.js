const $ = (id) => document.getElementById(id);
let selectedSessionId = null;
let selectedSession = null;
let currentFilter = "";
let socket = null;

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

function formatTime(value) {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
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

function renderSessions(sessions) {
  $("sessionCount").textContent = sessions.length;
  $("sessions").innerHTML = "";
  $("emptySessions").classList.toggle("hidden", sessions.length > 0);

  sessions.forEach((session) => {
    const button = document.createElement("button");
    button.className = `session-item ${session.id === selectedSessionId ? "selected" : ""}`;
    button.innerHTML = `
      <span class="session-item-top">
        <strong>${escapeHtml(session.metadata.device_id || "postureCamera")}</strong>
        <span class="badge ${session.status}">${statusLabel(session.status)}</span>
      </span>
      <span class="session-time">${formatTime(session.created_at)}</span>
      <span class="session-id">${session.id.slice(0, 8)} · ${duration(session)}</span>
    `;
    button.onclick = () => selectSession(session);
    $("sessions").appendChild(button);
  });
}

async function loadSessions(preserveSelection = true) {
  try {
    const query = currentFilter ? `?status=${currentFilter}` : "";
    const sessions = await request(`/sessions${query}`);
    $("status").textContent = `최근 업데이트 ${new Date().toLocaleTimeString("ko-KR")}`;
    renderSessions(sessions);
    if (!preserveSelection && sessions.length) await selectSession(sessions[0]);
    if (preserveSelection && selectedSessionId) {
      const refreshed = sessions.find((item) => item.id === selectedSessionId);
      if (refreshed) {
        selectedSession = refreshed;
        renderSessionHeader();
      }
    }
  } catch (error) {
    $("status").textContent = error.message;
  }
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
  const sensorEvents = events.filter((event) => event.type !== "analysis");
  const latest = [...sensorEvents].reverse().find((event) => event.content && typeof event.content === "object");
  $("latestMcra").textContent = latest?.content?.mCRA == null ? "—" : `${latest.content.mCRA}°`;
  $("latestPosture").textContent =
    latest?.content?.neck_forward == null ? "—" : latest.content.neck_forward ? "거북목" : "정상";
  [...events].reverse().forEach(renderEvent);
}

function renderEvent(item) {
  const content = item.content && typeof item.content === "object" ? item.content : {value: item.content};
  const row = document.createElement("article");
  row.className = "event-row";
  const posture = content.neck_forward == null ? "" :
    `<span class="posture ${content.neck_forward ? "bad" : "good"}">${content.neck_forward ? "거북목" : "정상"}</span>`;
  const mcra = content.mCRA == null ? "" : `<strong>${content.mCRA}°</strong>`;
  row.innerHTML = `
    <div class="event-dot"></div>
    <div class="event-body">
      <div class="event-top">
        <span>${escapeHtml(item.type)}</span>
        <time>${formatTime(item.created_at)}</time>
      </div>
      <div class="event-value">${mcra}${posture}</div>
      <div class="event-source">${escapeHtml(item.source)}</div>
    </div>
  `;
  $("events").appendChild(row);
}

function connectSocket() {
  socket?.close();
  if (!selectedSessionId || selectedSession.status !== "active") {
    $("liveState").textContent = "세션 종료";
    return;
  }
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/api/v1/ws/sessions/${selectedSessionId}`);
  socket.onopen = () => $("liveState").textContent = "● 실시간 연결";
  socket.onclose = () => $("liveState").textContent = "연결 대기";
  socket.onmessage = async () => {
    await loadEvents();
    await loadSessions(true);
  };
}

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = String(value);
  return node.innerHTML;
}

$("analyze").onclick = async () => {
  if (!selectedSessionId) return;
  $("analyze").disabled = true;
  $("analyze").textContent = "분석 중…";
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

document.querySelectorAll(".filter").forEach((button) => {
  button.onclick = async () => {
    document.querySelectorAll(".filter").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    currentFilter = button.dataset.status;
    await loadSessions(false);
  };
});

loadSessions(false);
setInterval(() => loadSessions(true), 5000);
