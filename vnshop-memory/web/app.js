"use strict";

const $ = (sel) => document.querySelector(sel);
const state = { conversationId: null, busy: false, cy: null };

const LABEL_COLORS = {
  Screen: "#2f7fd8", Function: "#e0892b", Status: "#8a63d2", Report: "#2a9d8f",
  Document: "#7a8699", Order: "#d1495b", Supplier: "#c9a227", Payment: "#3fa34d",
  System: "#5c6bc0", BusinessObject: "#b5651d", Promotion: "#e76fbf", Role: "#00a3c4",
  BusinessRule: "#9c2f6b", Inventory: "#6b8e23",
};
const OTHER_COLOR = "#9aa5b1";
const PROVIDER_NAMES = { gemini: "Gemini", claude: "Claude" };
const SUGGESTIONS = [
  "Luồng tạo đơn trả hàng NCC gồm những màn hình nào?",
  "Những trạng thái của đơn hàng và điều kiện chuyển trạng thái?",
  "Màn hình nào hiển thị báo cáo đối soát?",
  "Quy tắc nghiệp vụ của Flash sale?",
];

// ---------- tiện ích ----------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null) node.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function renderMarkdown(target, text) {
  target.innerHTML = DOMPurify.sanitize(marked.parse(text || ""));
}

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function formatDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

function stripHeading(text, heading) {
  return heading && text.startsWith(heading) ? text.slice(heading.length).trimStart() : text;
}

function shortArgs(input) {
  if (!input) return "";
  return Object.entries(input).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(", ");
}

// ---------- tab và bố cục ----------

function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab-body").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  if (name === "graph") refitGraph();
}

document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
$("#toggle-sidebar").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
function openPanel() {
  $("#panel").classList.add("open");
  refitGraph();
}

function refitGraph() {
  if (!state.cy) return;
  state.cy.resize();
  state.cy.fit(undefined, 20);
  // Màn hình hẹp: fit cả đồ thị làm chữ quá nhỏ, nên giữ mức zoom tối thiểu quanh node chính.
  if (state.cy.zoom() < 0.7) {
    const focus = state.cy.nodes("[?focus]");
    state.cy.zoom(0.7);
    state.cy.center(focus.nonempty() ? focus : undefined);
  }
}

$("#toggle-panel").addEventListener("click", () => {
  if ($("#panel").classList.contains("open")) $("#panel").classList.remove("open");
  else openPanel();
});

// ---------- đồ thị ----------

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function initGraph() {
  state.cy = cytoscape({
    container: $("#cy"),
    wheelSensitivity: 0.3,
    style: [
      {
        selector: "node",
        style: {
          "background-color": (n) => LABEL_COLORS[n.data("label")] || OTHER_COLOR,
          label: (n) => { const s = n.data("name") || n.id(); return s.length > 28 ? s.slice(0, 27) + "…" : s; },
          color: cssVar("--text"), "font-size": 10, "text-valign": "bottom", "text-margin-y": 4,
          width: 18, height: 18, "text-wrap": "ellipsis", "text-max-width": 140,
        },
      },
      { selector: "node[?focus]", style: { width: 28, height: 28, "border-width": 3, "border-color": cssVar("--text"), "font-weight": "bold" } },
      { selector: "node:selected", style: { "border-width": 4, "border-color": cssVar("--accent") } },
      {
        selector: "edge",
        style: {
          width: 1.3, "line-color": cssVar("--border"), "target-arrow-color": cssVar("--border"),
          "target-arrow-shape": "triangle", "curve-style": "bezier", "arrow-scale": 0.8,
          label: "data(rel)", "font-size": 8, color: cssVar("--muted"), "text-rotation": "autorotate",
          "text-background-color": cssVar("--surface"), "text-background-opacity": 1, "text-background-padding": 1,
        },
      },
    ],
  });
  state.cy.on("tap", "node", (evt) => showEntity(evt.target.id()));
  state.cy.on("dbltap", "node", (evt) => expandNode(evt.target.id()));

  const used = Object.entries(LABEL_COLORS);
  $("#legend").replaceChildren(
    ...used.map(([label, color]) => el("span", { style: `--c:${color}` }, label)),
    el("span", { style: `--c:${OTHER_COLOR}` }, "Khác"),
    el("span", { class: "muted" }, "· Bấm: chi tiết · Bấm đúp: mở rộng"),
  );
}

function toElements(data) {
  return [
    ...data.nodes.map((n) => ({ group: "nodes", data: { ...n, id: n.id } })),
    ...data.edges.map((e) => ({ group: "edges", data: { id: e.id, source: e.source, target: e.target, rel: e.rel.toLowerCase() } })),
  ];
}

function runLayout() {
  state.cy.resize();
  state.cy.layout({
    name: "cose", animate: false, nodeRepulsion: 40000, idealEdgeLength: 110,
    nodeOverlap: 40, componentSpacing: 80, padding: 24,
  }).run();
  refitGraph();
}

async function showGraph(ids, expand = true) {
  if (!ids || !ids.length) return;
  const data = await api(`/api/graph?ids=${encodeURIComponent(ids.join(","))}&expand=${expand}`);
  state.cy.elements().remove();
  state.cy.add(toElements(data));
  runLayout();
}

async function expandNode(id) {
  const data = await api(`/api/graph?ids=${encodeURIComponent(id)}&expand=true`);
  const fresh = toElements(data).filter((e) => state.cy.getElementById(e.data.id).empty());
  fresh.forEach((e) => { if (e.group === "nodes") e.data.focus = false; });
  state.cy.add(fresh);
  runLayout();
}

$("#graph-search").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("#graph-q").value.trim();
  if (!q) return;
  const hits = await api(`/api/search?q=${encodeURIComponent(q)}&limit=10`);
  if (hits.length) await showGraph(hits.map((h) => h.id));
});

// ---------- chi tiết node ----------

async function showEntity(id) {
  const view = $("#entity-view");
  showTab("entity");
  view.replaceChildren(el("p", { class: "muted" }, "Đang tải…"));
  let ent;
  try { ent = await api(`/api/entity/${encodeURIComponent(id)}`); }
  catch (err) { view.replaceChildren(el("p", { class: "muted" }, String(err))); return; }

  const facts = [
    ["Loại gốc", ent.raw_type], ["Module", ent.module], ["File SRS", ent.source_file],
    ["Community", ent.community], ["id", ent.id],
  ].filter(([, v]) => v !== null && v !== undefined && v !== "");
  const relations = ent.relations.map((r) =>
    el("div", { class: "rel" },
      el("span", { class: "type" }, r.outgoing ? `${r.rel} →` : `← ${r.rel}`),
      el("span", {},
        el("button", { class: "link", onclick: () => showEntity(r.id) }, r.name),
        el("span", { class: "muted" }, ` · ${r.label}`),
        r.notes && r.notes.length ? el("span", { class: "note" }, r.notes.join("; ")) : null)));

  view.replaceChildren(el("div", { class: "entity" },
    el("h3", {}, ent.name),
    el("span", { class: "chip" }, ent.label),
    ent.description ? el("p", {}, ent.description) : null,
    el("dl", { class: "kv" }, facts.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, String(v))])),
    ent.properties ? el("details", {}, el("summary", {}, "Thuộc tính gốc"), el("pre", { class: "json" }, JSON.stringify(ent.properties, null, 2))) : null,
    ent.groups.length ? el("p", {}, el("strong", {}, "Nhóm: "), ent.groups.map((g) => g.name).join(", ")) : null,
    ent.chunks && ent.chunks.length ? [
      el("p", {}, el("strong", {}, `Đoạn SRS nhắc tới (${ent.chunks.length})`)),
      ent.chunks.map((c) => el("details", { class: "chunk" },
        el("summary", {}, c.heading || c.path),
        el("div", { class: "muted" }, c.path),
        el("div", { class: "excerpt" }, stripHeading(c.excerpt, c.heading)))),
    ] : null,
    el("p", {}, el("strong", {}, `Quan hệ (${ent.relations.length})`)),
    relations,
    el("p", {}, el("button", { class: "link", onclick: () => { showTab("graph"); showGraph([ent.id]); } }, "Vẽ node này và hàng xóm"))));
  if (state.cy) {
    state.cy.$(":selected").unselect();
    state.cy.getElementById(id).select();
  }
}

// ---------- vết suy luận ----------

async function showTrace(traceId) {
  const view = $("#trace-view");
  showTab("trace");
  if (window.innerWidth <= 1000) openPanel();
  view.replaceChildren(el("p", { class: "muted" }, "Đang tải…"));
  const t = await api(`/api/traces/${traceId}`);
  const touched = [...new Set(t.steps.flatMap((s) => s.touched))];
  view.replaceChildren(
    el("p", {}, el("strong", {}, "Câu hỏi: "), t.question),
    el("p", { class: "muted" },
      `${t.model ? `${PROVIDER_NAMES[t.mode]} (${t.model})` : "Chế độ tra cứu"} · ${t.steps.length} bước · ${t.duration_ms < 1000 ? `${t.duration_ms} ms` : `${(t.duration_ms / 1000).toFixed(1)} giây`}`),
    ...t.steps.map((s) => el("div", { class: "trace-step" },
      el("header", {},
        el("span", { class: "name" }, `${s.seq}. ${s.name}`),
        el("span", { class: "muted" }, `${s.duration_ms} ms · ${s.ok ? "ok" : "lỗi"}`)),
      el("div", { class: "muted" }, s.summary || ""),
      el("pre", { class: "json" }, s.input_json),
      s.touched.length ? el("div", { class: "muted" }, `Chạm ${s.touched.length} node`) : null)),
    touched.length ? el("button", { class: "primary", onclick: () => { showTab("graph"); showGraph(touched, false); } },
      `Vẽ ${touched.length} node đã chạm`) : null,
  );
}

// ---------- hội thoại ----------

function messageView(role, text) {
  const bubble = el("div", { class: "bubble" });
  if (role === "user") bubble.textContent = text;
  else renderMarkdown(bubble, text);
  return { root: el("div", { class: `msg ${role}` }, bubble), bubble };
}

function addTraceLink(msgRoot, traceId) {
  msgRoot.append(el("div", { class: "msg-actions" },
    el("button", { class: "link", onclick: () => showTrace(traceId) }, "Xem vết suy luận")));
}

function scrollDown() {
  const box = $("#messages");
  box.scrollTop = box.scrollHeight;
}

async function loadConversations() {
  const list = await api("/api/conversations");
  $("#conversations").replaceChildren(...list.map((c) => el("li", {},
    el("button", { class: `item${c.id === state.conversationId ? " active" : ""}`, title: c.title, onclick: () => openConversation(c.id) }, c.title),
    el("button", { class: "del", title: "Xoá", "aria-label": "Xoá hội thoại", onclick: () => deleteConversation(c.id) }, "×"))));
}

async function openConversation(id) {
  const conv = await api(`/api/conversations/${id}`);
  state.conversationId = id;
  $("#sidebar").classList.remove("open");
  const box = $("#messages");
  box.replaceChildren();
  let lastTrace = null;
  for (const m of conv.messages) {
    const view = messageView(m.role, m.content);
    if (m.trace_id) { addTraceLink(view.root, m.trace_id); lastTrace = m.trace_id; }
    box.append(view.root);
  }
  scrollDown();
  loadConversations();
  if (lastTrace) {
    const t = await api(`/api/traces/${lastTrace}`);
    const ids = [...new Set(t.steps.flatMap((s) => s.touched))];
    if (ids.length) showGraph(ids, false);
  }
}

async function deleteConversation(id) {
  await api(`/api/conversations/${id}`, { method: "DELETE" });
  if (state.conversationId === id) newConversation();
  loadConversations();
}

function newConversation() {
  state.conversationId = null;
  $("#messages").replaceChildren(emptyState);
  loadConversations();
  $("#input").focus();
}

const emptyState = $("#empty-state");
$("#suggestions").replaceChildren(...SUGGESTIONS.map((s) =>
  el("button", { type: "button", onclick: () => { $("#input").value = s; send(); } }, s)));
$("#new-chat").addEventListener("click", newConversation);

// ---------- gửi câu hỏi (SSE) ----------

async function* sseEvents(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const data = chunk.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
      if (data) yield JSON.parse(data);
    }
  }
}

async function send() {
  const text = $("#input").value.trim();
  if (!text || state.busy) return;
  state.busy = true;
  $("#send").disabled = true;
  $("#input").value = "";
  if (emptyState.isConnected) emptyState.remove();

  const box = $("#messages");
  box.append(messageView("user", text).root);
  const stepsList = el("div");
  const stepsBox = el("details", { class: "steps", open: "" }, el("summary", {}, "Đang tra cứu…"), stepsList);
  const bubble = el("div", { class: "bubble typing" });
  const root = el("div", { class: "msg assistant" }, stepsBox, bubble);
  box.append(root);
  scrollDown();

  const rows = {};
  let answer = "";
  let pending = false;
  const paint = () => { pending = false; renderMarkdown(bubble, answer); scrollDown(); };

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, conversation_id: state.conversationId }),
    });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    for await (const ev of sseEvents(res)) {
      if (ev.type === "tool_call") {
        rows[ev.id] = el("div", { class: "step" }, el("span", { class: "dot" }),
          el("span", { class: "name" }, ev.name), el("span", { class: "arg" }, shortArgs(ev.input)));
        stepsList.append(rows[ev.id]);
      } else if (ev.type === "tool_result") {
        const row = rows[ev.id];
        if (row) {
          row.classList.add(ev.ok ? "ok" : "err");
          row.append(el("span", { class: "muted" }, `${ev.summary} · ${ev.duration_ms} ms`));
        }
      } else if (ev.type === "graph") {
        showGraph(ev.ids);
      } else if (ev.type === "token") {
        answer += ev.text;
        if (!pending) { pending = true; requestAnimationFrame(paint); }
      } else if (ev.type === "done") {
        state.conversationId = ev.conversation_id;
        addTraceLink(root, ev.trace_id);
        loadConversations();
      } else if (ev.type === "error") {
        root.append(el("div", { class: "bubble error" }, ev.message));
      }
    }
  } catch (err) {
    root.append(el("div", { class: "bubble error" }, `Lỗi kết nối: ${err.message}`));
  } finally {
    paint();
    bubble.classList.remove("typing");
    if (!answer) bubble.remove();
    const n = stepsList.children.length;
    stepsBox.querySelector("summary").textContent = n ? `Đã tra ${n} bước` : "Không gọi tool";
    stepsBox.open = false;
    if (!n) stepsBox.remove();
    state.busy = false;
    $("#send").disabled = false;
    scrollDown();
  }
}

$("#composer").addEventListener("submit", (e) => { e.preventDefault(); send(); });
$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
});

// ---------- module + thông tin ----------

async function loadModules() {
  const mods = await api("/api/modules");
  $("#modules").replaceChildren(...mods.map((m) => el("li", {},
    el("button", {
      class: "item", title: m.key,
      onclick: async () => {
        const rows = await api(`/api/modules/${m.key.split("/").map(encodeURIComponent).join("/")}/entities`);
        $("#sidebar").classList.remove("open");
        showTab("graph");
        if (window.innerWidth <= 1000) openPanel();
        await showGraph(rows.map((r) => r.id), false);
      },
    }, m.code ? `${m.code}. ${m.name}` : m.name),
    el("span", { class: "count" }, m.entities))));
}

async function loadInfo() {
  const info = await api("/api/info");
  const badge = $("#mode-badge");
  if (info.model) {
    badge.textContent = `${PROVIDER_NAMES[info.chat_mode]} · ${info.model}`;
    badge.classList.add("ai");
  } else {
    badge.textContent = "Chế độ tra cứu (chưa có AI)";
    badge.title = "Đặt GEMINI_API_KEY để bật trả lời bằng Gemini";
  }
  $("#build-info").textContent =
    `Graph build ${formatDate(info.built_at) || "?"} · ${info.nodes} node · ${info.rels} quan hệ · ${info.chunks} đoạn SRS`;
}

initGraph();
Promise.all([loadInfo(), loadConversations(), loadModules()]).catch((err) => {
  $("#build-info").textContent = `Không kết nối được backend: ${err.message}`;
});
