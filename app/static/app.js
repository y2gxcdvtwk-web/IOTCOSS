const $ = (id) => document.getElementById(id);
let sessionId = localStorage.getItem("sessionId");
let socket;

async function request(path, options = {}) {
  const response = await fetch(`/api/v1${path}`, {
    headers: {"Content-Type": "application/json"}, ...options
  });
  if (!response.ok) throw new Error((await response.json()).detail || "요청 실패");
  return response.json();
}
function showError(error) { $("status").textContent = error.message; }
function renderEvent(item) {
  const li = document.createElement("li");
  li.innerHTML = `<div>${escapeHtml(typeof item.content === "string" ? item.content : JSON.stringify(item.content))}</div>
    <div class="meta">${item.type} · ${new Date(item.created_at).toLocaleString()}</div>`;
  $("events").prepend(li);
}
function escapeHtml(value) {
  const node = document.createElement("div"); node.textContent = value; return node.innerHTML;
}
async function activate(id) {
  sessionId = id; localStorage.setItem("sessionId", id);
  $("workspace").classList.remove("hidden"); $("status").textContent = `세션 ${id.slice(0,8)} 연결됨`;
  $("events").innerHTML = "";
  (await request(`/sessions/${id}/events`)).forEach(renderEvent);
  socket?.close();
  socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/v1/ws/sessions/${id}`);
  socket.onmessage = (message) => renderEvent(JSON.parse(message.data).data);
}
$("start").onclick = async () => {
  try {
    const session = await request("/sessions", {method:"POST", body:JSON.stringify({user_id:$("userId").value})});
    await activate(session.id);
  } catch (e) { showError(e); }
};
$("save").onclick = async () => {
  try {
    const content = $("content").value.trim(); if (!content) return;
    await request(`/sessions/${sessionId}/events`, {method:"POST", body:JSON.stringify({content, sync_to_mobius:false})});
    $("content").value = "";
  } catch (e) { showError(e); }
};
$("analyze").onclick = async () => {
  try {
    const result = await request(`/sessions/${sessionId}/analysis`, {method:"POST", body:JSON.stringify({text:$("content").value || null})});
    $("result").textContent = `${result.summary}\n\n${result.recommendations.join("\n")}`;
  } catch (e) { showError(e); }
};
if (sessionId) request(`/sessions/${sessionId}`).then(() => activate(sessionId)).catch(() => localStorage.removeItem("sessionId"));

