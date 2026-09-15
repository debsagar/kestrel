// Kestrel operations desk. Plain ES module, no framework, no build step.
// render(frame) is the single render path for both live and replay data --
// both feed it the same {day,date,screens_after,actions,note,status,error} frame shape.

const TYPE_NAMES = { po: "purchase order", order: "customer order", booking: "container booking",
  work_order: "work order", transfer: "warehouse transfer", invoice_in: "supplier invoice",
  invoice_out: "customer invoice", chargeback: "chargeback", credit_note: "credit note",
  lot: "inspection lot", ret: "return", asn: "shipping notice", receipt: "goods receipt",
  qualification: "supplier qualification", audit: "supplier audit", contract: "freight contract" };
const STATE_PHRASES = {
  po: { draft: "were drafted", in_production: "went into production at the supplier", shipped: "left the supplier", received: "arrived at the plant",
        inspected: "passed incoming inspection", invoiced: "were invoiced", matched: "matched order and receipt", paid: "were paid",
        cancelled: "were cancelled", short_closed: "closed short", confirmed: "were confirmed" },
  order: { received: "came in from customers", allocated: "had stock reserved", shipped: "shipped to customers",
           delivered: "were delivered", declined: "were declined" },
  booking: { booked: "were booked", cut_off: "reached the port cut-off", loaded: "were loaded", at_sea: "sailed",
             arrived: "arrived in Rotterdam", customs: "entered customs", cleared: "cleared customs",
             delivered: "were delivered to the Rotterdam warehouse", rolled: "were rolled to a later sailing",
             blanked: "lost their sailing (blank sailing)", cancelled: "were cancelled" },
  work_order: { planned: "were planned", released: "were released to the plant", running: "started on the line", complete: "finished", cancelled: "were cancelled" },
  transfer: { created: "were created", in_transit: "left the warehouse", delivered: "arrived at the regional warehouse" },
  invoice_in: { open: "arrived from suppliers", blocked: "were blocked for not matching the order", disputed: "were disputed",
                accepted: "were accepted", paid: "were paid" },
  invoice_out: { open: "were raised to customers", paid: "were paid by customers" },
  chargeback: { open: "were raised by customers for late or short delivery", paid: "were settled" },
  lot: { sampling: "went to sampling", accepted: "were accepted", rejected: "were rejected", sorted: "were sorted", returned: "were returned" },
  credit_note: { open: "were issued by suppliers", paid: "were settled" },
  asn: { sent: "were sent by suppliers" }, receipt: { received: "were booked in" },
  contract: { active: "took effect", expired: "expired" },
  qualification: { pending: "started", done: "completed" }, audit: { pending: "were requested", done: "came back" },
  ret: { in_transit: "started back from customers", restocked: "were put back in stock", written_off: "were written off" },
};

// -- static network config, mirrored from kestrel/network.py (never changes at runtime) --
const SUPPLIER_IDS = ["S-BAT", "S-SOC", "S-BRK", "S-DRV", "S-CASE"];
const COMPONENT_IDS = ["BAT", "SOC", "DRV", "CASE", "CHG", "PKG"];
const SKU_IDS = ["EB-STD", "EB-PRO", "SPK-1"];
const CUSTOMER_IDS = ["C-BIGBOX", "C-MARKET", "C-PLCHAIN", "C-WEB"];
const CUSTOMER_DC = { "C-BIGBOX": "DC-DE", "C-MARKET": "DC-DE", "C-PLCHAIN": "DC-PL", "C-WEB": "DC-DE" };
const NODE_IDS = ["PLANT", "DC-NL", "DC-DE", "DC-PL"];
const LEG_MODES = ["air", "ocean_cape", "ocean_suez", "rail", "sea_air", "truck"];
const RECORD_TYPES = ["po", "asn", "receipt", "lot", "invoice_in", "booking", "contract", "work_order",
  "transfer", "order", "invoice_out", "chargeback", "credit_note", "ret", "qualification", "audit"];
const EXCEPTION_SEVERITY = { cash: "high", supplier: "high", quality: "medium", invoice: "medium", booking: "low", dc: "low" };

// Action schemas mirrored from kestrel/agent/tools.py ENGINE_TOOLS -- the same set of
// engine-boundary actions the "luna" model player is offered, described declaratively
// enough to build a plain HTML form and contextual id pickers from open records.
const ACTIONS = {
  create_po: { fields: [
    { name: "supplier", kind: "enum", options: SUPPLIER_IDS, required: true },
    { name: "component", kind: "enum", options: COMPONENT_IDS, required: true },
    { name: "qty", kind: "int", required: true },
    { name: "requested_day", kind: "int" },
    { name: "incoterm", kind: "string" },
  ] },
  cancel_po: { fields: [{ name: "po_id", kind: "record", recordType: "po", required: true }] },
  expedite_po: { fields: [{ name: "po_id", kind: "record", recordType: "po", required: true }] },
  accept_invoice: { fields: [{ name: "invoice_id", kind: "record", recordType: "invoice_in", required: true }] },
  dispute_invoice: { fields: [{ name: "invoice_id", kind: "record", recordType: "invoice_in", required: true }] },
  set_inspection_level: { fields: [
    { name: "supplier", kind: "enum", options: SUPPLIER_IDS, required: true },
    { name: "level", kind: "enum", options: ["I", "II", "III"], required: true },
  ] },
  qualify_supplier: { fields: [{ name: "supplier", kind: "enum", options: SUPPLIER_IDS, required: true }] },
  request_audit: { fields: [{ name: "supplier", kind: "enum", options: SUPPLIER_IDS, required: true }] },
  return_lot: { fields: [{ name: "lot_id", kind: "record", recordType: "lot", required: true }] },
  book_container: { fields: [
    { name: "mode", kind: "enum", options: ["ocean", "air", "sea_air"], required: true },
    { name: "route", kind: "enum", options: ["suez", "cape"] },
    { name: "lines", kind: "lines", required: true },
    { name: "rate_type", kind: "enum", options: ["spot", "contract"] },
  ] },
  cancel_booking: { fields: [{ name: "booking_id", kind: "record", recordType: "booking", required: true }] },
  sign_freight_contract: { fields: [{ name: "containers_per_month", kind: "int", required: true }] },
  release_work_order: { fields: [
    { name: "sku", kind: "enum", options: SKU_IDS, required: true },
    { name: "qty", kind: "int", required: true },
  ] },
  cancel_work_order: { fields: [{ name: "work_order_id", kind: "record", recordType: "work_order", required: true }] },
  create_transfer: { fields: [
    { name: "src", kind: "enum", options: NODE_IDS, required: true },
    { name: "dst", kind: "enum", options: NODE_IDS, required: true },
    { name: "mode", kind: "enum", options: LEG_MODES, required: true },
    { name: "lines", kind: "lines", required: true },
  ] },
  set_allocation_policy: { fields: [
    { name: "mode", kind: "enum", options: ["priority", "fair_share"], required: true },
    { name: "order", kind: "customer_order" },
  ] },
  allocate_order: { fields: [
    { name: "order_id", kind: "record", recordType: "order", required: true },
    { name: "qty", kind: "int", required: true },
  ] },
  decline_order: { fields: [{ name: "order_id", kind: "record", recordType: "order", required: true }] },
  markdown: { fields: [
    { name: "sku", kind: "enum", options: SKU_IDS, required: true },
    { name: "percent", kind: "int", required: true },
  ] },
};

// Schematic (not geographic) node/lane layout for the SVG map.
const MAP_NODES = {
  "PLANT": { x: 70, y: 150, label: "Plant", sub: "Dongguan" },
  "DC-NL": { x: 320, y: 60, label: "DC-NL", sub: "Rotterdam" },
  "DC-DE": { x: 560, y: 150, label: "DC-DE", sub: "" },
  "DC-PL": { x: 560, y: 250, label: "DC-PL", sub: "" },
};
const MAP_LANES = [
  { src: "PLANT", dst: "DC-NL", label: "ocean/air", types: ["booking"] },
  { src: "DC-NL", dst: "DC-DE", label: "rail/truck", types: ["transfer"] },
  { src: "DC-NL", dst: "DC-PL", label: "rail/truck", types: ["transfer"] },
  { src: "DC-DE", dst: "DC-PL", label: "truck", types: ["transfer"] },
];

const state = {
  mode: "live", worldId: null, frames: [], records: {}, frameIndex: 0,
  selectedNode: "PLANT", selectedType: "po", selectedRecordId: null,
  player: "rule", model: null, playing: false, playTimer: null, busy: false,
  // Set when window.KESTREL_RUNS is present at load (the Task 21 offline artifact hook):
  // no fetch is ever made, live controls stay hidden, and the run selector reads that
  // array directly instead of GET /api/runs.
  offline: false,
};

const $ = (id) => document.getElementById(id);

// -- API helpers ------------------------------------------------------------

async function api(path, opts) {
  const res = await fetch("/api" + path, opts);
  let body = null;
  try { body = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok) {
    const detail = (body && body.detail) || res.statusText;
    throw new Error(`${(opts && opts.method) || "GET"} ${path} -> ${res.status}: ${detail}`);
  }
  return body;
}
const postJSON = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

function showError(message) {
  $("error-text").textContent = message;
  $("error-banner").hidden = false;
}

async function guarded(fn) {
  if (state.busy) return;
  state.busy = true;
  setControlsDisabled(true);
  try { await fn(); }
  catch (e) { showError(e.message || String(e)); }
  finally { state.busy = false; setControlsDisabled(false); }
}

function setControlsDisabled(disabled) {
  const isLive = !state.offline && state.mode === "live" && state.worldId;
  $("step-day-btn").disabled = disabled || !isLive;
  $("autopilot-btn").disabled = disabled || !isLive;
  $("autopilot-days").disabled = disabled || !isLive;
  $("llm-day-btn").disabled = disabled || !isLive;
  $("new-world-btn").disabled = disabled || state.offline;
  $("submit-action-btn").disabled = disabled || !(isLive && atLatestFrame());
}

function atLatestFrame() { return state.frameIndex === state.frames.length - 1; }

// -- live session actions ----------------------------------------------------

async function createWorld() {
  const seed = parseInt($("seed-input").value, 10) || 1;
  const { id } = await postJSON("/worlds", { seed });
  state.worldId = id; state.mode = "live"; state.player = "you"; state.model = null;
  await refreshLive();
}

async function refreshLive() {
  const data = await api(`/worlds/${state.worldId}/replay`);
  state.frames = data.frames;
  state.records = data.records;
  state.frameIndex = Math.max(0, data.frames.length - 1);
  render();
}

async function submitAction(action) {
  const [result] = await postJSON(`/worlds/${state.worldId}/actions`, [action]);
  await refreshLive();
  renderActionResult(result, action);
}

async function stepDay() {
  await postJSON(`/worlds/${state.worldId}/end_day`, { note: "" });
  await refreshLive();
}

async function runAutopilot() {
  const days = parseInt($("autopilot-days").value, 10) || 1;
  await postJSON(`/worlds/${state.worldId}/autopilot?days=${days}`, {});
  await refreshLive();
}

async function runLlmDay() {
  const frame = await postJSON(`/worlds/${state.worldId}/llm_day`, {});
  if (frame.error) showError(`LLM day incomplete: ${frame.error}`);
  await refreshLive();
}

// -- replay ------------------------------------------------------------------

async function listRuns() {
  const runs = await api("/runs");
  const select = $("run-select");
  select.innerHTML = '<option value="">Live session</option>';
  for (const run of runs) {
    const opt = document.createElement("option");
    opt.value = `${run.task_id}/${run.player}`;
    opt.textContent = `${run.task_id} / ${run.player}${run.model ? " (" + run.model + ")" : ""} -- ${run.status} ${run.completed_days}/${run.requested_days}d`;
    select.appendChild(opt);
  }
}

async function loadRun(taskId, player) {
  const data = await api(`/runs/${taskId}/${player}`);
  state.mode = "replay"; state.frames = data.frames; state.records = data.records;
  state.frameIndex = 0; state.player = data.player; state.model = data.model;
  stopPlaying();
  render();
}

function backToLive() {
  state.mode = "live"; state.player = "you"; state.model = null;
  stopPlaying();
  if (state.worldId) refreshLive(); else { state.frames = []; state.records = {}; render(); }
}

// -- offline artifact hook (Task 21: window.KESTREL_RUNS / window.KESTREL_FINDINGS_HTML) ----
// No fetch anywhere in this section -- render(frame) below is fed straight from the global,
// exactly as it would be fed a GET /api/runs/{task}/{player} response in the live desk.

function populateRunSelectOffline() {
  const select = $("run-select");
  select.innerHTML = "";
  window.KESTREL_RUNS.forEach((run, i) => {
    const opt = document.createElement("option");
    opt.value = String(i);
    const playerLabel = run.model ? `${run.player}/${run.model}` : run.player;
    opt.textContent = `${run.task_id} — ${playerLabel} — ${run.status}`;
    select.appendChild(opt);
  });
}

function loadRunOffline(index) {
  const data = window.KESTREL_RUNS[index];
  if (!data) return;
  state.mode = "replay"; state.frames = data.frames; state.records = data.records;
  state.frameIndex = 0; state.player = data.player; state.model = data.model;
  stopPlaying();
  render();
}

// -- play/pause over frames ---------------------------------------------------

function stopPlaying() {
  state.playing = false;
  if (state.playTimer) clearInterval(state.playTimer);
  state.playTimer = null;
  $("play-btn").textContent = "Play";
}

function togglePlay() {
  if (state.playing) { stopPlaying(); return; }
  state.playing = true;
  $("play-btn").textContent = "Pause";
  state.playTimer = setInterval(() => {
    if (state.frameIndex >= state.frames.length - 1) { stopPlaying(); return; }
    state.frameIndex += 1;
    render();
  }, Number($("speed-select").value));
}

// -- rendering ----------------------------------------------------------------

function currentFrame() { return state.frames[state.frameIndex] || null; }

function render() {
  renderBadges();
  const frame = currentFrame();
  populateActionTypeSelect();
  populateRecordTypeSelect();
  renderScrubControls();
  if (!frame) {
    $("kpi-strip").innerHTML = "";
    $("map").innerHTML = "";
    $("node-panel").innerHTML = "";
    $("exceptions-panel").innerHTML = "";
    $("news-panel").innerHTML = "";
    $("records-table").querySelector("tbody").innerHTML = "";
    $("note-box").textContent = "No day recorded yet. Create a world to begin.";
    setControlsDisabled(false);
    return;
  }
  const screens = frame.screens_after || frame.screens_before;
  renderKPIs(frame, screens);
  renderMap(screens);
  renderNodePanel(screens);
  renderExceptions(screens);
  renderNews(screens);
  renderRecords(screens);
  renderNote(frame);
  renderToday(frame);
  setControlsDisabled(false);
}

function renderBadges() {
  const modeBadge = $("mode-badge");
  modeBadge.textContent = state.mode === "live" ? "LIVE" : "REPLAY";
  modeBadge.className = "badge " + (state.mode === "live" ? "badge-live" : "badge-replay");
  const playerBadge = $("player-badge");
  if (state.mode === "replay") {
    playerBadge.hidden = false;
    playerBadge.textContent = state.player === "luna" ? `LUNA${state.model ? " " + state.model : ""}` : "RULE-BASED";
    playerBadge.className = "badge " + (state.player === "luna" ? "badge-luna" : "badge-rule");
  } else {
    playerBadge.hidden = true;
  }
  $("live-controls").hidden = state.offline || state.mode !== "live";
  $("action-panel").hidden = state.offline;
  $("day-date").textContent = currentFrame() ? `Day ${currentFrame().day} -- ${currentFrame().date}` : "";
}

function renderScrubControls() {
  const slider = $("scrub-slider");
  slider.max = Math.max(0, state.frames.length - 1);
  slider.value = state.frameIndex;
  slider.disabled = state.frames.length <= 1;
  $("play-btn").disabled = state.frames.length <= 1;
  $("prev-btn").disabled = state.frameIndex <= 0;
  $("next-btn").disabled = state.frameIndex >= state.frames.length - 1;
  const f = currentFrame();
  $("frame-position").textContent = f ? `Day ${f.day} of ${state.frames.length} — ${f.date}` : "No run loaded";
}

function fmtMoney(n) { return "€" + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 }); }

function renderKPIs(frame, screens) {
  const strip = $("kpi-strip");
  strip.innerHTML = "";
  const add = (label, value, sub) => {
    const div = document.createElement("div");
    div.className = "kpi";
    div.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}`;
    strip.appendChild(div);
  };
  add("Cash", fmtMoney(screens.finance.cash));
  const otifRows = CUSTOMER_IDS.map((cid) => {
    const c = screens.customers[cid];
    const pct = c ? Math.round(c.otif_to_date * 100) : 0;
    return `<div class="otif-row"><span>${cid}</span><span>${pct}%</span></div>`;
  }).join("");
  const otifDiv = document.createElement("div");
  otifDiv.className = "kpi";
  otifDiv.innerHTML = `<div class="label">OTIF to date</div>${otifRows}`;
  strip.appendChild(otifDiv);
  add("Exceptions to date", screens.exceptions.length);
  const openBookings = screens.records.booking || [];
  const containers = openBookings.reduce((sum, b) => sum + (b.data.containers || 0), 0);
  add("Inbound containers", containers, `${openBookings.length} open booking(s)`);
  add("Day", `${screens.calendar.today}`, `${screens.calendar.date} (${screens.calendar.weekday})`);
}

function laneCount(lane, screens) {
  if (lane.types.includes("booking")) {
    return (screens.records.booking || []).reduce((s, b) => s + Object.values(b.data.lines || {}).reduce((a, q) => a + q, 0), 0);
  }
  return (screens.records.transfer || [])
    .filter((t) => t.data.src === lane.src && t.data.dst === lane.dst)
    .reduce((s, t) => s + Object.values(t.data.lines || {}).reduce((a, q) => a + q, 0), 0);
}

function svgEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function renderMap(screens) {
  const svg = $("map");
  svg.innerHTML = "";
  for (const lane of MAP_LANES) {
    const a = MAP_NODES[lane.src], b = MAP_NODES[lane.dst];
    const count = laneCount(lane, screens);
    const line = svgEl("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: "lane" + (count > 0 ? " active" : "") });
    svg.appendChild(line);
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    svg.appendChild(svgEl("text", { x: mx, y: my - 8, class: "lane-label", "text-anchor": "middle" })).textContent = lane.label;
    if (count > 0) {
      svg.appendChild(svgEl("circle", { cx: mx, cy: my + 8, r: 11, class: "lane-count" }));
      const t = svgEl("text", { x: mx, y: my + 12, class: "lane-count-label", "text-anchor": "middle" });
      t.textContent = count > 999 ? Math.round(count / 1000) + "k" : count;
      svg.appendChild(t);
    }
  }
  for (const [nodeId, pos] of Object.entries(MAP_NODES)) {
    const g = svgEl("g", { "data-node": nodeId, style: "cursor:pointer" });
    g.addEventListener("click", () => { state.selectedNode = nodeId; render(); });
    g.appendChild(svgEl("rect", {
      x: pos.x - 44, y: pos.y - 22, width: 88, height: 44, rx: 8,
      class: "node-box" + (state.selectedNode === nodeId ? " selected" : ""),
    }));
    g.appendChild(svgEl("text", { x: pos.x, y: pos.y - 2, class: "node-label", "text-anchor": "middle" })).textContent = pos.label;
    if (pos.sub) g.appendChild(svgEl("text", { x: pos.x, y: pos.y + 14, class: "node-sub", "text-anchor": "middle" })).textContent = pos.sub;
    svg.appendChild(g);
  }
  // suppliers feed PLANT; customers hang off their DC -- context only, not clickable nodes.
  const miniNode = (x, y, w, text) => {
    svg.appendChild(svgEl("rect", { x, y: y - 9, width: w, height: 18, rx: 4, class: "mini-node" }));
    svg.appendChild(svgEl("text", { x: x + w / 2, y: y + 4, class: "mini-label", "text-anchor": "middle" })).textContent = text;
  };
  const plant = MAP_NODES.PLANT;
  SUPPLIER_IDS.forEach((sid, i) => {
    const y = 40 + i * 55;
    svg.appendChild(svgEl("line", { x1: 15, y1: y, x2: plant.x - 44, y2: plant.y - 15 + i * 3, class: "lane" }));
    miniNode(0, y, 30, sid.replace("S-", ""));
  });
  CUSTOMER_IDS.forEach((cid) => {
    const dc = MAP_NODES[CUSTOMER_DC[cid]];
    const idx = CUSTOMER_IDS.filter((c) => CUSTOMER_DC[c] === CUSTOMER_DC[cid]).indexOf(cid);
    const y = dc.y - 30 + idx * 22;
    svg.appendChild(svgEl("line", { x1: dc.x + 44, y1: dc.y, x2: 690, y2: y, class: "lane" }));
    miniNode(655, y, 62, cid.replace("C-", ""));
  });
}

function renderNodePanel(screens) {
  $("node-title").textContent = `Node stock -- ${state.selectedNode}`;
  const inv = screens.inventory[state.selectedNode] || {};
  const panel = $("node-panel");
  panel.innerHTML = '<div class="hd">Item</div><div class="hd">On hand</div><div class="hd">Allocated</div><div class="hd">In transit</div><div class="hd">On order</div>';
  for (const [item, row] of Object.entries(inv)) {
    panel.innerHTML += `<div>${item}</div><div>${row.on_hand}</div><div>${row.allocated}</div><div>${row.in_transit_to}</div><div>${row.on_order}${row.days_of_cover != null ? ` <span class="pill">${row.days_of_cover}d cover</span>` : ""}</div>`;
  }
}

function renderExceptions(screens) {
  const panel = $("exceptions-panel");
  const items = screens.exceptions.slice(-25).reverse();
  if (!items.length) { panel.innerHTML = '<p class="sub">None recorded.</p>'; return; }
  panel.innerHTML = items.map((e) => {
    const sev = EXCEPTION_SEVERITY[e.kind] || "low";
    return `<div class="exception-row sev-${sev}"><span class="exception-day">Day ${e.day}</span><span class="exception-text"><strong>${e.kind}</strong> (${e.ref || "-"}): ${e.text}</span></div>`;
  }).join("");
}

function renderNews(screens) {
  const panel = $("news-panel");
  const items = screens.news.slice(-15).reverse();
  if (!items.length) { panel.innerHTML = '<p class="sub">None recorded.</p>'; return; }
  panel.innerHTML = items.map((n) =>
    `<div class="news-item"><div class="meta">Day ${n.day} -- ${n.source}</div><div class="title">${n.title}</div><div>${n.body || ""}</div></div>`
  ).join("");
}

function orderCustomerIndex(screens) {
  const index = {};
  for (const [cid, c] of Object.entries(screens.customers)) {
    for (const o of c.open_orders) index[o.id] = cid;
  }
  return index;
}

function recordNodes(type, rec, screens) {
  switch (type) {
    case "po": case "asn": case "receipt": case "lot": case "invoice_in":
    case "qualification": case "audit": case "work_order": case "contract": case "credit_note":
      return ["PLANT"];
    case "booking":
      return ["PLANT", "DC-NL"];
    case "transfer":
      return [rec.data.src, rec.data.dst].filter(Boolean);
    case "order":
      return [CUSTOMER_DC[rec.data.customer]].filter(Boolean);
    case "ret":
      return [CUSTOMER_DC[rec.data.customer]].filter(Boolean);
    case "invoice_out": case "chargeback": {
      const cid = orderCustomerIndex(screens)[rec.data.order_id];
      return cid ? [CUSTOMER_DC[cid]] : [];
    }
    default: return [];
  }
}

function populateRecordTypeSelect() {
  const select = $("record-type-select");
  if (select.options.length) return;
  for (const t of RECORD_TYPES) {
    const opt = document.createElement("option");
    opt.value = t; opt.textContent = t;
    select.appendChild(opt);
  }
  select.value = state.selectedType;
  select.addEventListener("change", () => { state.selectedType = select.value; $("record-detail").hidden = true; render(); });
}

function renderRecords(screens) {
  const toolbar = $("records-toolbar");
  toolbar.innerHTML = `<span class="pill">Filtered to node: ${state.selectedNode}</span>
    <button type="button" id="clear-node-filter">Show all nodes</button>`;
  toolbar.querySelector("#clear-node-filter").addEventListener("click", () => { state.selectedNode = "__ALL__"; render(); });

  const all = screens.records[state.selectedType] || [];
  const rows = state.selectedNode === "__ALL__" ? all
    : all.filter((r) => recordNodes(state.selectedType, r, screens).includes(state.selectedNode));

  const table = $("records-table");
  table.querySelector("thead").innerHTML = "<tr><th>ID</th><th>State</th><th>Created</th><th>Summary</th></tr>";
  const tbody = table.querySelector("tbody");
  tbody.innerHTML = "";
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="sub">No open records here.</td></tr>';
  }
  for (const rec of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><code>${rec.id}</code></td><td>${statePill(rec.state)}</td><td>${rec.created_day}</td><td>${summarize(state.selectedType, rec)}</td>`;
    tr.addEventListener("click", () => { state.selectedRecordId = rec.id; renderRecordDetail(rec); });
    tbody.appendChild(tr);
  }
  if (state.selectedRecordId) {
    const found = rows.find((r) => r.id === state.selectedRecordId);
    if (found) renderRecordDetail(found); else $("record-detail").hidden = true;
  }
}

function statePill(stateName) {
  const bad = ["cancelled", "rejected", "declined", "written_off", "short_closed", "blocked"];
  const good = ["delivered", "paid", "accepted", "complete", "done", "matched", "cleared"];
  const cls = bad.includes(stateName) ? "pill-bad" : good.includes(stateName) ? "pill-good" : "pill-open";
  return `<span class="pill ${cls}">${stateName}</span>`;
}

function summarize(type, rec) {
  const d = rec.data;
  switch (type) {
    case "po": return `${d.supplier} / ${d.component} x${d.qty}`;
    case "booking": return `${d.mode}${d.route ? " " + d.route : ""}: ${JSON.stringify(d.lines)}`;
    case "transfer": return `${d.src} -> ${d.dst} (${d.mode}): ${JSON.stringify(d.lines)}`;
    case "order": return `${d.customer} / ${d.sku} x${d.qty}`;
    case "work_order": return `${d.sku} x${d.qty} (produced ${d.produced || 0})`;
    default: return Object.keys(d).slice(0, 3).map((k) => `${k}=${JSON.stringify(d[k])}`).join(", ");
  }
}

function renderRecordDetail(rec) {
  const panel = $("record-detail");
  panel.hidden = false;
  const history = rec.history.map(([day, s, detail]) => `<tr><td>${day}</td><td>${statePill(s)}</td><td>${detail}</td></tr>`).join("");
  const data = Object.entries(rec.data).map(([k, v]) => `<tr><td>${k}</td><td>${JSON.stringify(v)}</td></tr>`).join("");
  panel.innerHTML = `<strong>${rec.id}</strong> (${rec.type})
    <table><tbody>${data}</tbody></table>
    <div class="sub" style="margin-top:6px">History</div>
    <table><thead><tr><th>Day</th><th>State</th><th>Detail</th></tr></thead><tbody>${history}</tbody></table>`;
}

function renderNote(frame) {
  $("note-title").textContent = state.mode === "live"
    ? "Today's note"
    : (state.player === "luna" ? `Luna's note (${state.model || "model"})` : "Rule planner note");
  $("note-box").textContent = frame.note || (frame.status === "incomplete" ? "Day in progress -- no note yet." : "(no note)");
  if (frame.actions && frame.actions.length) {
    const list = frame.actions.map((a) =>
      `<div>${a.result.ok ? "✓" : "✗"} <code>${a.action.type || JSON.stringify(a.action)}</code>${a.result.id ? ` -> ${a.result.id}` : ""}${!a.result.ok ? ` -- ${a.result.reason}` : ""}</div>`
    ).join("");
    $("note-box").innerHTML += `<div style="margin-top:8px" class="sub">Actions this day</div>${list}`;
  }
  if (frame.report && frame.report.log && frame.report.log.length) {
    $("note-box").innerHTML += `<div style="margin-top:8px" class="sub">Outcomes</div>${frame.report.log.map((l) => `<div>${l}</div>`).join("")}`;
  }
}

function renderActionResult(result, action) {
  const el = $("action-result");
  el.innerHTML = result.ok
    ? `<div class="confirmation">${action.type} accepted${result.id ? " -> " + result.id : ""}</div>`
    : `<div class="rejection">${action.type} rejected: ${result.reason}</div>`;
}

// -- action form ---------------------------------------------------------------

function populateActionTypeSelect() {
  const select = $("action-type-select");
  if (select.options.length) return;
  for (const name of Object.keys(ACTIONS)) {
    const opt = document.createElement("option");
    opt.value = name; opt.textContent = name;
    select.appendChild(opt);
  }
  select.addEventListener("change", renderActionFields);
  renderActionFields();
}

function recordOptions(recordType) {
  const frame = currentFrame();
  if (!frame) return [];
  const screens = frame.screens_after || frame.screens_before;
  return screens.records[recordType] || [];
}

function renderActionFields() {
  const type = $("action-type-select").value;
  const container = $("action-fields");
  container.innerHTML = "";
  for (const field of ACTIONS[type].fields) {
    const wrap = document.createElement("div");
    wrap.className = "field";
    const label = document.createElement("label");
    label.textContent = field.name + (field.required ? " *" : "");
    label.setAttribute("for", "f-" + field.name);
    wrap.appendChild(label);
    if (field.kind === "enum") {
      const select = document.createElement("select");
      select.id = "f-" + field.name; select.name = field.name;
      select.innerHTML = (field.required ? "" : '<option value="">(none)</option>') + field.options.map((o) => `<option value="${o}">${o}</option>`).join("");
      wrap.appendChild(select);
    } else if (field.kind === "record") {
      const select = document.createElement("select");
      select.id = "f-" + field.name; select.name = field.name;
      const opts = recordOptions(field.recordType);
      select.innerHTML = opts.length
        ? opts.map((r) => `<option value="${r.id}">${r.id} (${r.state})</option>`).join("")
        : '<option value="">(no open records)</option>';
      wrap.appendChild(select);
    } else if (field.kind === "lines") {
      SKU_IDS.forEach((sku) => {
        const row = document.createElement("div");
        row.className = "field";
        row.innerHTML = `<label>${sku} qty</label><input type="number" min="0" step="1" data-line="${sku}" value="0">`;
        wrap.appendChild(row);
      });
    } else if (field.kind === "customer_order") {
      const input = document.createElement("input");
      input.type = "text"; input.id = "f-" + field.name; input.name = field.name;
      input.placeholder = CUSTOMER_IDS.join(",");
      input.value = CUSTOMER_IDS.join(",");
      wrap.appendChild(input);
      const hint = document.createElement("div");
      hint.className = "sub"; hint.textContent = "priority order, comma-separated, every customer once";
      wrap.appendChild(hint);
    } else if (field.kind === "int") {
      const input = document.createElement("input");
      input.type = "number"; input.step = "1"; input.id = "f-" + field.name; input.name = field.name;
      wrap.appendChild(input);
    } else {
      const input = document.createElement("input");
      input.type = "text"; input.id = "f-" + field.name; input.name = field.name;
      wrap.appendChild(input);
    }
    container.appendChild(wrap);
  }
}

function buildActionPayload() {
  const type = $("action-type-select").value;
  const action = { type };
  for (const field of ACTIONS[type].fields) {
    if (field.kind === "lines") {
      const lines = {};
      document.querySelectorAll('#action-fields input[data-line]').forEach((el) => {
        const q = parseInt(el.value, 10);
        if (q > 0) lines[el.dataset.line] = q;
      });
      action.lines = lines;
      continue;
    }
    const el = $("f-" + field.name);
    if (!el || el.value === "") continue;
    if (field.kind === "int") action[field.name] = parseInt(el.value, 10);
    else if (field.kind === "customer_order") action[field.name] = el.value.split(",").map((s) => s.trim()).filter(Boolean);
    else action[field.name] = el.value;
  }
  return action;
}

// -- theme ----------------------------------------------------------------------

function applyTheme(pref) {
  const root = document.documentElement;
  if (pref === "system") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", pref);
  try { localStorage.setItem("kestrel-theme", pref); } catch (e) { /* ignore */ }
}

// -- wiring ------------------------------------------------------------------

function wireLiveControls() {
  $("new-world-btn").addEventListener("click", () => guarded(createWorld));
  $("step-day-btn").addEventListener("click", () => guarded(stepDay));
  $("autopilot-btn").addEventListener("click", () => guarded(runAutopilot));
  $("llm-day-btn").addEventListener("click", () => guarded(runLlmDay));

  $("actions-form").addEventListener("submit", (e) => {
    e.preventDefault();
    guarded(() => submitAction(buildActionPayload()));
  });

  $("refresh-runs-btn").addEventListener("click", () => guarded(listRuns));
  $("run-select").addEventListener("change", (e) => {
    const val = e.target.value;
    guarded(async () => { if (!val) backToLive(); else { const [task, player] = val.split("/"); await loadRun(task, player); } });
  });

  guarded(listRuns);
}

function initOfflineMode() {
  // Task 21's artifact: window.KESTREL_RUNS carries the run.json(s) to show, and this
  // page must never touch the network -- no /api/worlds, no /api/runs, nothing.
  state.offline = true;
  $("live-controls").hidden = true;
  $("refresh-runs-btn").hidden = true;
  $("action-panel").hidden = true;
  populateRunSelectOffline();
  $("run-select").addEventListener("change", (e) => loadRunOffline(parseInt(e.target.value, 10)));
  if (window.KESTREL_RUNS.length) loadRunOffline(0);
  if (typeof window.KESTREL_FINDINGS_HTML === "string" && window.KESTREL_FINDINGS_HTML) {
    $("findings-content").innerHTML = window.KESTREL_FINDINGS_HTML;
    $("findings-btn").hidden = false;
  }
}

function init() {
  let savedTheme = "system";
  try { savedTheme = localStorage.getItem("kestrel-theme") || "system"; } catch (e) { /* ignore */ }
  $("theme-select").value = savedTheme;
  applyTheme(savedTheme);
  $("theme-select").addEventListener("change", (e) => applyTheme(e.target.value));

  $("scrub-slider").addEventListener("input", (e) => {
    stopPlaying();
    state.frameIndex = parseInt(e.target.value, 10);
    render();
  });
  $("play-btn").addEventListener("click", togglePlay);

  $("error-dismiss").addEventListener("click", () => { $("error-banner").hidden = true; });
  $("about-btn").addEventListener("click", () => $("about-panel").showModal());
  $("about-close").addEventListener("click", () => $("about-panel").close());
  $("findings-btn").addEventListener("click", () => $("findings-panel").showModal());
  $("findings-close").addEventListener("click", () => $("findings-panel").close());
  $("prev-btn").addEventListener("click", () => { stopPlaying(); if (state.frameIndex > 0) { state.frameIndex -= 1; render(); } });
  $("next-btn").addEventListener("click", () => { stopPlaying(); if (state.frameIndex < state.frames.length - 1) { state.frameIndex += 1; render(); } });
  $("speed-select").addEventListener("change", () => { if (state.playing) { stopPlaying(); togglePlay(); } });

  if (Array.isArray(window.KESTREL_RUNS)) initOfflineMode();
  else wireLiveControls();

  render();
}

init();

// -- "What happened today": a plain-language account of one day ---------------
function plural(n, word) { return `${n} ${word}${n === 1 ? "" : "s"}`; }
function actionSentence(a) {
  const x = a.action, ok = a.result.ok, id = a.result.id ? ` (${a.result.id})` : "";
  const lines = (o) => Object.entries(o || {}).map(([k, v]) => `${Number(v).toLocaleString()} ${k}`).join(", ");
  const what = {
    release_work_order: () => `released a work order for ${Number(x.qty).toLocaleString()} ${x.sku}`,
    cancel_work_order: () => `cancelled work order ${x.id}`,
    create_po: () => `ordered ${Number(x.qty).toLocaleString()} ${x.component} from ${x.supplier}`,
    cancel_po: () => `cancelled purchase order ${x.id}`,
    expedite_po: () => `asked to expedite purchase order ${x.id}`,
    book_container: () => `booked ${x.containers || 1} container(s) ${x.mode ? "by " + x.mode : ""}${x.route ? " via " + x.route : ""} carrying ${lines(x.lines)}`,
    cancel_booking: () => `cancelled booking ${x.id}`,
    sign_freight_contract: () => `signed a freight contract for ${x.containers_per_month} containers a month`,
    create_transfer: () => `moved ${lines(x.lines)} from ${x.src} to ${x.dst}`,
    accept_invoice: () => `accepted invoice ${x.id}`,
    dispute_invoice: () => `disputed invoice ${x.id}`,
    set_inspection_level: () => `set incoming inspection to level ${x.level}`,
    qualify_supplier: () => `started qualifying ${x.supplier}`,
    request_audit: () => `requested an audit of ${x.supplier}`,
    return_lot: () => `returned lot ${x.id}`,
    allocate_order: () => `hand-allocated ${x.qty} units to order ${x.id}`,
    decline_order: () => `declined order ${x.id}`,
    set_allocation_policy: () => `set allocation to ${x.mode}${x.order ? " (" + x.order.join(" > ") + ")" : ""}`,
    markdown: () => `marked ${x.sku} down by ${Math.round((x.pct || x.fraction || 0) * 100)}%`,
  }[x.type];
  const text = what ? what() : `did ${x.type}`;
  return ok ? `${text}${id}.` : `tried to ${text}, but it was refused: ${a.result.reason}.`;
}
function transitionsToday(frame) {
  const day = frame.day, seen = new Set(), groups = {};
  const pool = state.records && Object.keys(state.records).length
    ? Object.values(state.records)
    : Object.values(frame.screens_after?.records || {}).flat();
  for (const rec of pool) {
    for (const [d, st, detail] of rec.history || []) {
      if (d !== day || seen.has(rec.id + st)) continue;
      seen.add(rec.id + st);
      const key = rec.type + "|" + st;
      (groups[key] ||= { type: rec.type, state: st, ids: [], detail }).ids.push(rec.id);
    }
  }
  return Object.values(groups).map((g) => {
    const name = TYPE_NAMES[g.type] || g.type;
    let phrase = (STATE_PHRASES[g.type] || {})[g.state] || `moved to "${g.state.replace(/_/g, " ")}"`;
    if (g.ids.length === 1) phrase = phrase.replace(/^were /, "was ");
    const ids = g.ids.length <= 3 ? ` (${g.ids.join(", ")})` : "";
    return `${plural(g.ids.length, name)} ${phrase}${ids}.`;
  });
}
function renderToday(frame) {
  const box = $("today-box");
  if (!frame) { box.innerHTML = "No day loaded yet."; return; }
  const who = state.mode === "live" ? "You" : (state.player === "luna" ? `The model (${state.model || "luna"})` : "The rule planner");
  const acts = (frame.actions || []).map(actionSentence);
  const world = transitionsToday(frame);
  const log = frame.report?.log || [];
  const news = (frame.report?.news || []).map((n) => `News: ${n.title}.`);
  const exc = (frame.report?.new_exceptions || []).map((e) => `Exception: ${e.text}.`);
  const before = frame.screens_before?.finance?.cash, after = frame.screens_after?.finance?.cash;
  const cash = after == null ? "" : `Cash ended the day at ${fmtMoney(after)}` +
    (before == null ? "." : ` (${after - before >= 0 ? "+" : "−"}${fmtMoney(Math.abs(after - before))} today).`);
  const section = (title, items, empty) =>
    `<div class="today-col"><div class="sub">${title}</div>${items.length ? `<ul>${items.map((t) => `<li>${t}</li>`).join("")}</ul>` : `<div class="muted">${empty}</div>`}</div>`;
  box.innerHTML =
    section(`${who} did`, acts, "Nothing. No actions were taken this day.") +
    section("Meanwhile in the world", [...news, ...exc, ...log, ...world], "A quiet day: no documents changed state.") +
    (cash ? `<div class="today-cash">${cash}</div>` : "");
}
