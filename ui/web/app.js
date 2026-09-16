/* Jawawa Quant Computer — frontend controller (vanilla JS). */
"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

const state = {
  tasks: new Map(),        // task_id -> {status, events: []}
  live: new Map(),         // task_id -> lastStepText
  events: [],
};

function toast(msg, ms = 3200) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), ms);
}

async function jfetch(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

/* ---------------- navigation ---------------- */
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    btn.classList.add("active");
    $("#view-" + btn.dataset.view).classList.add("active");
    if (btn.dataset.view === "tasks") loadTasks();
    if (btn.dataset.view === "files") loadFiles(".");
    if (btn.dataset.view === "models") loadProviders();
    if (btn.dataset.view === "skills") loadSkills();
    if (btn.dataset.view === "memory") loadMemory();
    if (btn.dataset.view === "activity") loadActivity();
    if (btn.dataset.view === "settings") loadSettings();
    if (btn.dataset.view === "computer") loadComputer();
    if (btn.dataset.view === "chat") $("#chat-text").focus();
  });
});

/* ---------------- SSE ---------------- */
function connectSSE() {
  const src = new EventSource("/api/events/stream");
  src.onmessage = (e) => {
    try { const ev = JSON.parse(e.data); onEvent(ev); } catch (_) {}
  };
  src.onerror = () => { /* reconnects automatically */ };
}
window.addEventListener("beforeunload", () => { /* EventSource closes with page */ });

function onEvent(ev) {
  state.events.unshift(ev);
  if (ev.task_id) {
    if (!state.tasks.has(ev.task_id)) state.tasks.set(ev.task_id, []);
    const arr = state.tasks.get(ev.task_id);
    arr.push(ev);
    if (ev.event_type === "task") renderChatTask(ev.task_id, ev);
    else renderChatSteps(ev.task_id, arr);
    renderComputer(ev);
  }
}

function friendlyMessage(ev) {
  if (ev.status === "pending_approval") {
    const aid = (ev.evidence && ev.evidence.approval_id) || "?";
    return `${ev.message} — <button class="ghost" onclick="decide('${aid}',1)">Approve</button> <button class="ghost" onclick="decide('${aid}',0)">Deny</button>`;
  }
  return ev.message || `${ev.tool}.${ev.action}`;
}

async function decide(aid, approve) {
  try {
    await jfetch(`/api/approvals/${aid}/decide`, { method: "POST", body: JSON.stringify({ approve: !!approve }) });
    toast(approve ? "Approved" : "Denied");
  } catch (e) { toast(e.message); }
}

/* ---------------- chat ---------------- */
let stepCache = {}; // task_id -> step messages rendered so far
const msgRoot = $("#messages");

function ensureTaskBubble(taskId, userText) {
  if (stepCache[taskId]) return;
  stepCache[taskId] = { user: null, steps: [], result: null, statusEl: null };
  const b = el("div", "bubble user");
  b.textContent = userText;
  b.appendChild(el("span", "time", new Date().toLocaleTimeString()));
  msgRoot.appendChild(b);
  stepCache[taskId].user = b;
  stepCache[taskId].statusEl = el("div", "bubble step");
  msgRoot.appendChild(stepCache[taskId].statusEl);
}

function renderChatSteps(taskId, events) {
  const c = stepCache[taskId];
  if (!c) return;
  let html = "";
  for (const ev of events) {
    if (ev.event_type === "step") {
      const cls = `step ${ev.status}`;
      const dot = ev.status === "completed" ? "✓" : ev.status === "started" ? "●" : ev.status === "running" ? "…" : ev.status === "failed" ? "✗" : "◐";
      html += `<div class="bubble step ${cls}"><span class="dot">${dot}</span> ${friendlyMessage(ev)}</div>`;
    }
  }
  c.statusEl.innerHTML = html;
}

function renderChatTask(taskId, ev) {
  // If task completed/failed, show final bubble.
  const c = stepCache[taskId];
  if (c && (ev.status === "completed" || ev.status === "failed" || ev.status === "cancelled")) {
    const b = el("div", `bubble bot ${ev.status === "completed" ? "ok" : "err"}`);
    b.textContent = ev.message || (ev.status === "completed" ? "Done." : "Task did not finish.");
    b.appendChild(el("span", "time", new Date().toLocaleTimeString()));
    msgRoot.appendChild(b);
    delete stepCache[taskId];
  }
}

async function sendChat() {
  const ta = $("#chat-text");
  const text = ta.value.trim();
  if (!text) return;
  ta.value = "";
  ta.style.height = "auto";
  const empty = msgRoot.querySelector(".empty-state");
  if (empty) empty.remove();
  ensureTaskBubble("pending", text);
  try {
    const resp = await jfetch("/api/chat", { method: "POST", body: JSON.stringify({ message: text }) });
    delete stepCache.pending;
    stepCache[resp.task_id] = { statusEl: null, steps: [] };
    const dive = msgRoot.lastElementChild; // placeholder
    const b = el("div", "bubble step");
    b.textContent = "Queued…";
    msgRoot.appendChild(b);
    stepCache[resp.task_id].statusEl = b;
    state.tasks.set(resp.task_id, []);
  } catch (e) {
    const b = el("div", "bubble bot err");
    b.textContent = "Error: " + e.message;
    msgRoot.appendChild(b);
    delete stepCache.pending;
  }
}

$("#send-btn").addEventListener("click", sendChat);
$("#chat-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

/* ---------------- tasks ---------------- */
async function loadTasks() {
  const tasks = await jfetch("/api/tasks?limit=40");
  const root = $("#task-list");
  root.innerHTML = "";
  for (const t of tasks) {
    const card = el("div", "card");
    card.appendChild(el("h3", "", t.request));
    const row = el("div", "kv");
    row.appendChild(el("kbd", "", t.id));
    row.appendChild(el("span", `st-${t.status}`, t.status));
    row.appendChild(el("span", "muted", new Date(t.created_at * 1000).toLocaleString()));
    if (t.error) row.appendChild(el("span", "err", " · " + (t.error || "").slice(0, 120)));
    card.appendChild(row);
    if (t.result) {
      try {
        const r = JSON.parse(t.result);
        if (r.summary) card.appendChild(el("div", "muted", "✓ " + r.summary));
      } catch (_) {}
    }
    root.appendChild(card);
  }
}

/* ---------------- computer ---------------- */
async function loadComputer() {
  const info = await jfetch("/api/computer");
  $("#computer-head").innerHTML = "";
  $("#computer-head").appendChild(
    el("div", "muted", `Platform: ${info.os} (${info.release}) · ${info.architecture}`)
  );
}

function renderComputer(ev) {
  if (!ev.tool && ev.event_type !== "task") return;
  const run = $("#active-run");
  run.innerHTML = "";
  if (state.tasks.size === 0) { run.textContent = "No task running."; return; }
  const last = [...state.tasks.entries()].pop()[1].filter(e => e.event_type !== "message");
  const item = last[last.length - 1];
  if (item) run.textContent = `${item.tool ? item.tool + "." + item.action : "task"} → ${item.status}`;
  const recent = $("#recent-steps");
  const tail = state.events.filter(e => e.tool).slice(0, 8);
  recent.innerHTML = tail.length
    ? tail.map(e => `<div>${e.tool}.${e.action}  <span class="st-${e.status}">${e.status}</span></div>`).join("")
    : "No steps yet.";
}

$("#stop-all").addEventListener("click", async () => {
  const act = await jfetch("/api/acting");
  for (const tid of act.active || []) await jfetch(`/api/tasks/${tid}/cancel`, { method: "POST" });
  toast("Stop requested");
});
$("#browser-check").addEventListener("click", async () => {
  try {
    const r = await jfetch("/api/browser/health");
    $("#browser-status").textContent = `${r.driver} driver — ${r.detail}`;
  } catch (e) { $("#browser-status").textContent = e.message; }
});

/* ---------------- files ---------------- */
async function loadFiles(path) {
  const data = await jfetch("/api/files?path=" + encodeURIComponent(path || "."));
  $("#files-path").textContent = data.path;
  const root = $("#file-list");
  root.innerHTML = "";
  for (const e of data.entries) {
    const card = el("div", "card");
    const row = el("div", "kv");
    row.appendChild(el("span", "mono", e.is_dir ? "📁 " : "📄 " + e.name));
    row.appendChild(el("span", "muted", e.is_dir ? "directory" : "file"));
    card.appendChild(row);
    if (e.is_dir) card.addEventListener("click", () => loadFiles(e.path));
    root.appendChild(card);
  }
}

/* ---------------- models ---------------- */
async function loadProviders() {
  const providers = await jfetch("/api/providers");
  const root = $("#provider-list");
  root.innerHTML = "";
  for (const p of providers) {
    const card = el("div", "card");
    const row = el("div", "kv");
    row.appendChild(el("kbd", "", p.kind));
    row.appendChild(el("span", "", p.name));
    row.appendChild(el("span", "muted", " · " + (p.base_url || "demo")));
    row.appendChild(el("span", "muted", " · " + p.model));
    row.appendChild(el("span", "", p.enabled ? "on" : "off"));
    row.appendChild(el("span", "", p.has_key ? "key ✓" : ""));
    card.appendChild(row);
    const btnRow = el("div", "btn-row");
    const test = el("button", "ghost", "Test");
    test.addEventListener("click", async () => {
      try {
        const r = await jfetch(`/api/providers/${p.id}/test`);
        toast(`${p.name}: ${r.detail}${r.models.length ? " · " + r.models.slice(0, 4).join(", ") : ""}`, 6000);
      } catch (e) { toast(e.message); }
    });
    btnRow.appendChild(test);
    card.appendChild(btnRow);
    root.appendChild(card);
  }
}

async function loadSkills() {
  const data = await jfetch("/api/skills");
  const root = $("#skill-list");
  root.innerHTML = "";
  for (const t of data.tools) {
    const card = el("div", "card");
    card.appendChild(el("kbd", "mono", t.name));
    card.appendChild(el("div", "muted", t.description + "  · risk: " + t.risk));
    root.appendChild(card);
  }
}

$("#add-provider").addEventListener("click", async () => {
  const body = {
    kind: $("#p-kind").value,
    name: $("#p-name").value || "New provider",
    base_url: $("#p-url").value || undefined,
    model: $("#p-model").value,
    api_key: $("#p-key").value || undefined,
  };
  try {
    const r = await jfetch("/api/providers", { method: "POST", body: JSON.stringify(body) });
    $("#provider-result").textContent = `${r.ok ? "Connected ✓" : "Unreachable"} ${r.detail}` +
      (r.models.length ? " · " + r.models.slice(0, 5).join(", ") : "");
    $("#p-key").value = "";
    loadProviders();
  } catch (e) { $("#provider-result").textContent = "Error: " + e.message; }
});

/* ---------------- memory ---------------- */
async function loadMemory() {
  const mem = await jfetch("/api/memory");
  const root = $("#memory-list");
  root.innerHTML = "";
  for (const m of mem) {
    const card = el("div", "card");
    card.appendChild(el("div", "mono", m.content));
    card.appendChild(el("div", "muted", `${m.kind} · ${m.scope} · ${new Date(m.updated_at * 1000).toLocaleString()}`));
    root.appendChild(card);
  }
}
$("#mem-save").addEventListener("click", async () => {
  const content = $("#mem-content").value.trim();
  if (!content) return;
  await jfetch("/api/memory", { method: "POST", body: JSON.stringify({ content, kind: $("#mem-kind").value }) });
  $("#mem-content").value = "";
  loadMemory();
  toast("Saved");
});

/* ---------------- activity ---------------- */
async function loadActivity() {
  const list = await jfetch("/api/activity");
  const root = $("#activity-list");
  root.innerHTML = "";
  for (const a of list) {
    const card = el("div", "card");
    const row = el("div", "kv");
    row.appendChild(el("kbd", "", new Date(a.created_at * 1000).toLocaleTimeString()));
    row.appendChild(el("span", `st-${a.status}`, a.status));
    row.appendChild(el("span", "", `${a.skill ? a.skill + "." : ""}${a.action || "—"} ${a.resource ? "→ " + a.resource : ""}`));
    if (a.outcome) row.appendChild(el("span", "muted", "· " + a.outcome));
    card.appendChild(row);
    root.appendChild(card);
  }
}

/* ---------------- settings ---------------- */
async function loadSettings() {
  const s = await jfetch("/api/settings");
  $("#privacy-badge").textContent = s.privacy_mode;
  $("#provider-badge").textContent = "demo";
  try {
    const h = await jfetch("/api/health");
    $("#provider-badge").textContent = h.provider;
  } catch (_) {}
  $("#settings-status").textContent = JSON.stringify({ privacy: s.privacy_mode, approval: s.approval_mode, demo: s.demo_mode });
}
document.querySelectorAll("[data-privacy]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    await jfetch("/api/settings", { method: "POST", body: JSON.stringify({ privacy_mode: btn.dataset.privacy }) });
    loadSettings();
    toast("Privacy mode → " + btn.dataset.privacy);
  });
});

/* ---------------- boot ---------------- */
(async () => {
  try { await loadSettings(); } catch (_) {}
  connectSSE();
})();