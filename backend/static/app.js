/* Stoppuhr v0.4.2 – UI Logic (Startkarten: manuelles Laden, Bahnen dynamisch) */

function byId(id) { return document.getElementById(id); }

function formatTime(ms) {
  if (!ms) return "–";
  try { return new Date(ms).toLocaleTimeString(); } catch { return "–"; }
}

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (m) => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  }[m]));
}

// -----------------------------
// Global State (UI)
// -----------------------------
let startcards = { rows: [], max_lane: 0, runs: [], source_url: null, last_fetch_ts: null, error: null };
let currentRun = null;

let buttons = []; // from backend
let laneAssignments = {}; // lane -> {active, pending}
let maxLane = 0;

// -----------------------------
// Backend calls
// -----------------------------
async function apiGet(path) {
  const r = await fetch(path, { headers: { "Accept": "application/json" } });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return await r.json();
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify(body || {})
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || (j && j.ok === false)) {
    const msg = (j && j.error) ? j.error : ("HTTP " + r.status);
    throw new Error(msg);
  }
  return j;
}

// -----------------------------
// Settings / Startcards
// -----------------------------
async function loadSettingsIntoUI() {
  const s = await apiGet("/api/settings");
  byId("baseUrlInput").value = s.startcards_base_url || "";
  byId("baseUrlInputSettings").value = s.startcards_base_url || "";
  byId("suffixInput").value = s.startcards_suffix || "/export/CSV/Startkarten.csv";
  byId("suffixDisplay").value = byId("suffixInput").value;
  byId("autoNextInput").value = s.auto_next_run_s ?? "10";
  byId("stopLockoutInput").value = s.stop_lockout_s ?? "5";
  byId("shutdownGraceInput").value = s.shutdown_grace_s ?? "10";
}

async function loadStartcardsFromBackend() {
  const sc = await apiGet("/api/startcards");
  startcards = sc;
  maxLane = Number(sc.max_lane || 0);
  if (!maxLane || maxLane < 1) maxLane = 10;
  byId("maxLaneLabel").textContent = String(maxLane);
  updateRunSelect(sc.runs || []);
  renderLanesTable();
  updateStartcardsStatusLine();
}

function updateStartcardsStatusLine() {
  const el = byId("startcardsStatus");
  const ts = startcards.last_fetch_ts ? formatTime(startcards.last_fetch_ts) : "–";
  const src = startcards.source_url ? startcards.source_url : "–";
  if (startcards.error) {
    el.textContent = `Status: Fehler (${startcards.error}). Letzter Versuch: ${ts}. URL: ${src}`;
    el.classList.remove("text-muted");
    el.classList.add("text-danger");
  } else {
    el.textContent = `Status: ${startcards.rows?.length || 0} Zeilen. Letztes Laden: ${ts}. URL: ${src}`;
    el.classList.remove("text-danger");
    el.classList.add("text-muted");
  }
}

function updateRunSelect(runs) {
  const sel = byId("laufSelect");
  sel.innerHTML = "";
  const r = (runs || []).map(String);
  r.sort((a,b) => (parseInt(a,10)||0) - (parseInt(b,10)||0));
  r.forEach(run => {
    const opt = document.createElement("option");
    opt.value = run;
    opt.textContent = run;
    sel.appendChild(opt);
  });
  // default
  if (!currentRun) currentRun = r[0] || null;
  if (currentRun && r.includes(String(currentRun))) {
    sel.value = String(currentRun);
  } else if (r.length) {
    currentRun = r[0];
    sel.value = r[0];
  }
}

// -----------------------------
// Taster / Drag&Drop assignments
// -----------------------------
function resetAssignments() {
  laneAssignments = {};
  for (let b = 1; b <= maxLane; b++) laneAssignments[b] = { active: null, pending: null };
}

function getSlotForButton(btnId) {
  for (let b = 1; b <= maxLane; b++) {
    if (laneAssignments[b].active === btnId) return { slot: `BAHN ${b}`, role: "bahn-active" };
    if (laneAssignments[b].pending === btnId) return { slot: `BAHN ${b}`, role: "bahn-pending" };
  }
  return { slot: null, role: null };
}

function findButtonById(id) { return buttons.find(b => b.id === id) || null; }

async function loadButtons() {
  const data = await apiGet("/api/mapping");
  const entries = [];
  if (data.starter) entries.push({ t: data.starter, role: "starter", lane: null });
  Object.keys(data.mapping || {}).forEach(lane => {
    if (data.mapping[lane]) entries.push({ t: data.mapping[lane], role: "bahn", lane });
  });
  (data.unmapped_taster || []).forEach(t => entries.push({ t, role: "none", lane: null }));
  buttons = entries.map(({ t, role, lane }) => ({
    id: t.mac,
    mac: t.mac || "",
    letter: t.letter || "?",
    name: t.name || "",
    role,
    lane,
    last_seen_ms: t.last_seen_ts || null,
    last_event_type: null,
    battery_percent: t.online ? (t.battery ?? null) : null,
    rssi_dbm: t.online ? (t.rssi ?? null) : null,
    vbat: t.online ? (t.vbat ?? null) : null,
    temp: t.online ? (t.temp ?? null) : null,
    humidity: t.online ? (t.humidity ?? null) : null,
    ssid: t.online ? (t.ssid ?? null) : null,
    pending_lane: t.pending_lane || null,
    online: !!t.online
  }));

  resetAssignments();

  // initial assignment from backend fields (role/lane)
  buttons.forEach(btn => {
    if (btn.role === "bahn" && btn.lane != null) {
      const ln = Number(btn.lane);
      if (!isNaN(ln) && ln >= 1 && ln <= maxLane) {
        if (!laneAssignments[ln].active) laneAssignments[ln].active = btn.id;
        else if (laneAssignments[ln].active !== btn.id) laneAssignments[ln].pending = btn.id;
      }
    } else if (btn.role === "none" && btn.pending_lane && btn.pending_lane !== "starter") {
      // Bereitschaft: Tausch wartet auf den ersten Druck dieses Tasters
      const ln = Number(btn.pending_lane);
      if (ln >= 1 && ln <= maxLane) laneAssignments[ln].pending = btn.id;
    }
  });

  renderButtonList();
  renderStarter();
  renderLanesTable();
  byId("tasterLastRefresh").textContent = "Letzte Aktualisierung: " + new Date().toLocaleTimeString();
}

async function unassignLane(lane) {
  try {
    await apiPost("/api/unassign", { lane: String(lane) });
    await loadButtons();
  } catch (e) {
    alert("Entfernen fehlgeschlagen: " + e.message);
  }
}

function vitalsText(btn) {
  if (!btn || !btn.online) return "offline";
  const parts = [];
  if (btn.battery_percent != null) parts.push(btn.battery_percent + "%" + (btn.vbat != null ? " (" + Number(btn.vbat).toFixed(2) + " V)" : ""));
  if (btn.rssi_dbm != null) parts.push(btn.rssi_dbm + " dBm");
  if (btn.ssid) parts.push(btn.ssid);
  if (btn.temp != null) parts.push(Number(btn.temp).toFixed(1) + " °C");
  if (btn.humidity != null) parts.push(Number(btn.humidity).toFixed(0) + " % rF");
  return parts.join(" · ");
}

async function swapNow(lane, mac) {
  try {
    await apiPost("/api/assign", { mac, lane: lane === "starter" ? "starter" : Number(lane), immediate: true });
    await loadButtons();
  } catch (e) {
    alert("Tausch fehlgeschlagen: " + e.message);
  }
}

function pendingActionsHtml(lane, mac) {
  return `<div class="mt-1"><button class="btn btn-sm btn-outline-primary btn-swap-now" data-lane="${escapeHtml(String(lane))}" data-mac="${escapeHtml(mac)}">Sofort tauschen</button>
    <button class="btn btn-sm btn-outline-secondary btn-cancel-pending" data-lane="${escapeHtml(String(lane))}">Abbrechen</button></div>`;
}

document.addEventListener("click", ev => {
  const swap = ev.target.closest(".btn-swap-now");
  if (swap) { swapNow(swap.dataset.lane, swap.dataset.mac); return; }
  const cancel = ev.target.closest(".btn-cancel-pending");
  if (cancel) {
    apiPost("/api/cancel-pending", { lane: cancel.dataset.lane }).then(() => loadButtons())
      .catch(e => alert("Abbrechen fehlgeschlagen: " + e.message));
  }
});

function renderStarter() {
  const box = byId("starterDrop");
  const s = buttons.find(b => b.role === "starter");
  const p = buttons.find(b => b.role === "none" && b.pending_lane === "starter");
  const pendingHtml = p
    ? `<div class="small text-warning">Bereitschaft: Taster ${escapeHtml(p.letter || "?")} wird beim ersten Druck Starter</div>${pendingActionsHtml("starter", p.mac)}`
    : "";
  box.innerHTML = (s
    ? `<strong>Taster ${escapeHtml(s.letter || "?")}</strong> <span class="small text-muted">${escapeHtml(s.name)} · ${escapeHtml(vitalsText(s))}</span>`
    : `<span class="text-muted small">kein Starter – Taster hierher ziehen</span>`) + pendingHtml;
}

// Messergebnisse des Servers (Zeiten je Lauf und Bahn)
let runStatus = { current_run: null, current_attempt: 1, current_key: null, runs: {} };
let serverOffsetMs = 0; // Serverzeit minus Browserzeit
let lastServerKey = null;

async function loadRunStatus() {
  const t0 = Date.now();
  runStatus = await apiGet("/api/run-status");
  if (runStatus.server_now) serverOffsetMs = runStatus.server_now - (t0 + Date.now()) / 2;
  let label = "Server-Lauf: " + (runStatus.current_label ?? "–");
  if (runStatus.start_lockout_remaining_s > 0) {
    label += ` · Start gesperrt: ${Math.ceil(runStatus.start_lockout_remaining_s)} s`;
  }
  if (runStatus.next_run_in_s != null) label += ` · nächster Lauf in ${Math.ceil(runStatus.next_run_in_s)} s`;
  byId("serverRunLabel").textContent = label;
  // Anzeige folgt dem Lauf des Servers, wenn dieser wechselt
  const serverRun = String(runStatus.current_run ?? "");
  const serverKey = String(runStatus.current_key ?? "");
  if (lastServerKey !== null && serverKey !== lastServerKey && serverRun) {
    const sel = byId("laufSelect");
    if ([...sel.options].some(o => o.value === serverRun)) {
      sel.value = serverRun;
      currentRun = serverRun;
      renderLanesTable();
    }
  }
  lastServerKey = serverKey;
  updateClocks();
}

function formatMs(ms) {
  if (ms == null) return "–";
  const total = Math.max(0, ms) / 1000;
  if (total < 60) return total.toFixed(2) + " s";
  const m = Math.floor(total / 60);
  return m + ":" + (total - m * 60).toFixed(2).padStart(5, "0");
}

// Zeitspalte: gestoppte Zeit fest anzeigen, sonst laeuft die Uhr seit dem Start mit
function updateClocks() {
  const runKey = String(currentRun) === String(runStatus.current_run)
    ? runStatus.current_key
    : latestAttemptKeyForRun(currentRun);
  const run = runStatus.runs[runKey] || {};
  const now = Date.now() + serverOffsetMs;
  document.querySelectorAll(".lane-time").forEach(td => {
    const lane = td.dataset.lane;
    const stopped = (run.times_ms || {})[lane];
    let text = "–";
    let cls = "lane-time";
    if (stopped != null) {
      text = formatMs(stopped);
      cls += " fw-bold";
    } else if (run.started && td.dataset.active === "1") {
      text = formatMs(now - run.starter_ts);
      cls += " text-primary";
    }
    if (td.textContent !== text) td.textContent = text;
    td.className = cls;
  });
}

function latestAttemptKeyForRun(run) {
  const runStr = String(run);
  const latestAttempt = attemptNumberForRun(run);
  return latestAttempt > 1 ? `${runStr}/${latestAttempt}` : runStr;
}

function attemptNumberForRun(run) {
  const runStr = String(run);
  let latestAttempt = 0;
  Object.keys(runStatus.runs || {}).forEach(key => {
    const [baseRun, attemptText] = key.split("/");
    if (baseRun !== runStr) return;
    const attempt = attemptText ? Number(attemptText) : 1;
    if (attempt > latestAttempt) latestAttempt = attempt;
  });
  return latestAttempt;
}

// TESTBEREICH: Tastendruck ohne echten Taster ausloesen (spaeter entfernen)
function renderTestButtons() {
  const box = byId("testButtons");
  box.innerHTML = "";
  const mk = (label, cls, handler) => {
    const b = document.createElement("button");
    b.className = "btn btn-sm " + cls;
    b.textContent = label;
    b.addEventListener("click", handler);
    box.appendChild(b);
  };
  const press = async (lane) => {
    const msg = byId("testMessage");
    try {
      await apiPost("/api/triggers", { test_lane: lane });
      msg.textContent = `Bahn/Starter „${lane}“ gedrückt.`;
      msg.className = "small mt-2 text-success";
    } catch (e) {
      msg.textContent = `„${lane}“: ${e.message}`;
      msg.className = "small mt-2 text-danger";
    }
    loadRunStatus().catch(() => {});
  };
  mk("Start", "btn-success", () => press("starter"));
  for (let b = 1; b <= maxLane; b++) mk("Bahn " + b, "btn-outline-primary", () => press(String(b)));
  mk("Messung zurücksetzen", "btn-outline-danger", async () => {
    await apiPost("/api/test/reset-run", {}).catch(() => {});
    byId("testMessage").textContent = "Messung des Server-Laufs zurückgesetzt.";
    byId("testMessage").className = "small mt-2 text-muted";
    loadRunStatus().catch(() => {});
  });
}

function renderButtonList() {
  const container = byId("tasterList");
  container.innerHTML = "";

  buttons.forEach(btn => {
    const div = document.createElement("div");
    div.className = "taster-card";
    div.draggable = true;
    div.dataset.buttonId = btn.id;

    const slotInfo = getSlotForButton(btn.id);
    let slotLabel = "–";
    if (slotInfo.slot) {
      slotLabel = slotInfo.slot + (slotInfo.role.endsWith("pending") ? " (Bereitschaft)" : " (aktiv)");
    } else if (btn.pending_lane === "starter") {
      slotLabel = "START (Bereitschaft)";
    }

    const letter = btn.letter || "?";
    const assigned = btn.role === "starter" || (btn.role === "bahn" && btn.lane != null);
    const unassignHtml = assigned
      ? `<button class="btn btn-sm btn-outline-secondary btn-unassign" data-lane="${btn.role === "starter" ? "starter" : escapeHtml(String(btn.lane))}">Entfernen</button>`
      : "";
    div.innerHTML = `
      <div class="taster-header">
        <span>Taster ${escapeHtml(letter)}</span>
        ${unassignHtml}
        <span class="taster-badge">${escapeHtml(slotLabel)}</span>
      </div>
      <div class="taster-mac">${escapeHtml(btn.name ? btn.name + " · " + btn.mac : btn.mac)}</div>
      <div class="small mt-1 text-muted">
        ${escapeHtml(vitalsText(btn))}
      </div>
    `;

    div.addEventListener("dragstart", ev => {
      div.classList.add("dragging");
      ev.dataTransfer.setData("text/plain", btn.id);
    });
    div.addEventListener("dragend", () => div.classList.remove("dragging"));

    container.appendChild(div);
  });
}

function attachDropTargets() {
  const targets = document.querySelectorAll(".drop-target");
  targets.forEach(target => {
    if (target._hasDropHandlers) return;
    target._hasDropHandlers = true;

    target.addEventListener("dragover", ev => { ev.preventDefault(); target.classList.add("drop-hover"); });
    target.addEventListener("dragleave", () => target.classList.remove("drop-hover"));
    target.addEventListener("drop", ev => {
      ev.preventDefault();
      target.classList.remove("drop-hover");
      const btnId = ev.dataTransfer.getData("text/plain");
      const lane = target.getAttribute("data-lane");
      if (!lane) return;
      // Zuordnung auf dem Server speichern, danach Serverstand neu laden
      const btn = findButtonById(btnId);
      if (btn && btn.mac) {
        apiPost("/api/assign", { mac: btn.mac, lane: lane === "starter" ? "starter" : Number(lane) })
          .then(() => loadButtons())
          .catch(e => alert("Zuordnung speichern fehlgeschlagen: " + e.message));
      } else {
        assignButtonToLane(btnId, Number(lane));
      }
    });
  });
}

function assignButtonToLane(buttonId, lane) {
  if (!laneAssignments[lane]) return;

  // remove from all lanes
  for (let b = 1; b <= maxLane; b++) {
    if (laneAssignments[b].active === buttonId) laneAssignments[b].active = null;
    if (laneAssignments[b].pending === buttonId) laneAssignments[b].pending = null;
  }

  const a = laneAssignments[lane];
  if (!a.active) a.active = buttonId;
  else if (a.active !== buttonId) a.pending = buttonId;

  renderButtonList();
  renderLanesTable();
}

// -----------------------------
// Lanes Table
// -----------------------------
function rowsForCurrentRun() {
  if (!currentRun) return [];
  const runStr = String(currentRun);
  return (startcards.rows || []).filter(r => String(r["Lauf"] ?? r["lauf"] ?? "").trim() === runStr);
}

function renderLanesTable() {
  const tbody = byId("bahnenTableBody");
  tbody.innerHTML = "";

  const runRows = rowsForCurrentRun();

  // map lane->row (one per lane)
  const byLane = {};
  runRows.forEach(r => {
    const laneVal = (r["Bahn"] ?? r["bahn"] ?? "").toString().trim();
    const ln = parseInt(laneVal, 10);
    if (!isNaN(ln) && ln >= 1) byLane[ln] = r;
  });

  for (let b = 1; b <= maxLane; b++) {
    const r = byLane[b];
    const tr = document.createElement("tr");
    if (!r) tr.classList.add("lane-inactive");

    const name = r ? (r["Name"] ?? r["name"] ?? "–") : "–";
    const startnr = r ? (r["Startnummer"] ?? r["startnummer"] ?? "–") : "–";
    const disz = r ? (r["Disziplin"] ?? r["disziplin"] ?? "–") : "–";

    const assign = laneAssignments[b] || { active: null, pending: null };
    const activeBtn = assign.active ? findButtonById(assign.active) : null;
    const pendingBtn = assign.pending ? findButtonById(assign.pending) : null;

    let tasterHtml = `<span class="text-muted small">kein Taster</span>`;
    if (activeBtn || pendingBtn) {
      let main = activeBtn ? (activeBtn.letter || "?") : (pendingBtn.letter || "?");
      let extra = "";
      if (activeBtn && pendingBtn && pendingBtn.id !== activeBtn.id) {
        extra = ` <span class="text-warning">(Bereitschaft: ${escapeHtml(pendingBtn.letter || "?")})</span>${pendingActionsHtml(b, pendingBtn.mac)}`;
      }
      const shown = activeBtn || pendingBtn;
      tasterHtml = `<div class="taster-assigned"><strong>Taster ${escapeHtml(main)}</strong>${extra}<div class="small text-muted">${escapeHtml(vitalsText(shown))}</div></div>`;
    }

    tr.innerHTML = `
      <td>${b}</td>
      <td>${escapeHtml(name)}</td>
      <td>${escapeHtml(startnr)}</td>
      <td>${escapeHtml(disz)}</td>
      <td><div class="drop-target" data-lane="${b}">${tasterHtml}</div></td>
      <td class="lane-time" data-lane="${b}" data-active="${r ? 1 : 0}">–</td>
    `;
    tbody.appendChild(tr);
  }

  const selectedRunKey = String(currentRun) === String(runStatus.current_run)
    ? runStatus.current_key
    : latestAttemptKeyForRun(currentRun);
  byId("bahnenFooter").textContent = currentRun
    ? `Lauf ${selectedRunKey || currentRun}: ${runRows.length} Startkarten-Zeilen (nicht belegte Bahnen sind inaktiv).`
    : "Keine Laufdaten geladen.";

  attachDropTargets();
  updateClocks();
}

// -----------------------------
// System status
// -----------------------------
async function refreshSystemStatus() {
  const s = await apiGet("/api/system-status");
  byId("sysHostname").textContent = s.hostname || "–";
  byId("sysUptime").textContent = s.uptime || "–";
  byId("sysLoad").textContent = (s.load_avg && s.load_avg.length >= 3)
    ? `${s.load_avg[0].toFixed(2)} / ${s.load_avg[1].toFixed(2)} / ${s.load_avg[2].toFixed(2)}`
    : "–";
  byId("sysCpu").textContent = (s.cpu_percent != null) ? s.cpu_percent.toFixed(1) + " %" : "–";
  if (s.mem) byId("sysMem").textContent = `${(s.mem.used/1024/1024).toFixed(1)} / ${(s.mem.total/1024/1024).toFixed(1)} MiB (${s.mem.percent.toFixed(1)} %)`;
  else byId("sysMem").textContent = "–";
  if (s.disk) byId("sysDisk").textContent = `${(s.disk.used/1024/1024/1024).toFixed(1)} / ${(s.disk.total/1024/1024/1024).toFixed(1)} GiB (${s.disk.percent.toFixed(1)} %)`;
  else byId("sysDisk").textContent = "–";
  byId("svcStatus").textContent = (s.services && s.services.stoppuhr) ? s.services.stoppuhr : "–";

  byId("statusLastRefresh").textContent = "Letzte Aktualisierung: " + new Date().toLocaleTimeString();
  await refreshCluster().catch(() => {});
}

function fmtDuration(s) {
  if (s == null) return "–";
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  return (d ? d + " d " : "") + h + " h " + m + " min";
}

function nodeCardHtml(n, label) {
  if (!n.reachable) {
    return `<div class="col-md-6"><div class="border border-danger rounded p-2">
      <strong>${escapeHtml(label)}</strong> <span class="badge text-bg-danger">nicht erreichbar</span>
      <div class="small text-muted">${escapeHtml(n.peer_ip || "")}</div></div></div>`;
  }
  const ips = Object.entries(n.ips || {}).map(([i, a]) => `${escapeHtml(i)}: ${escapeHtml(a)}`).join(", ") || "–";
  const rd = n.redis || {};
  const redisText = rd.role === "master" ? `Hauptbestand (Kopien: ${rd.replicas})`
    : rd.role === "slave" ? `Kopie (${rd.link === "up" ? "synchron" : "NICHT synchron"})` : "nicht erreichbar";
  const work = n.has_vip ? `<span class="badge text-bg-success">arbeitet</span>` : `<span class="badge text-bg-secondary">Bereitschaft</span>`;
  const rc = n.last_role_change ? `${escapeHtml(n.last_role_change.state)} um ${new Date(n.last_role_change.ts).toLocaleTimeString()}` : "–";
  const hot = n.cpu_temp != null && n.cpu_temp >= 70 ? ' class="text-danger fw-bold"' : "";
  return `<div class="col-md-6"><div class="border rounded p-2">
    <strong>${escapeHtml(label)}</strong> ${work}
    <div class="small">Hostname: ${escapeHtml(n.hostname)}</div>
    <div class="small">WLAN: ${escapeHtml(n.wifi_ssid || "–")}</div>
    <div class="small">IP: ${ips}</div>
    <div class="small">Server-Adresse (VIP): ${n.has_vip ? escapeHtml(n.vip) : "nicht hier"}</div>
    <div class="small">Stoppuhr-Dienst: ${n.stoppuhr_active ? "läuft" : "gestoppt"}</div>
    <div class="small">Daten: ${redisText}</div>
    <div class="small">Letzter Wechsel: ${rc}</div>
    <div class="small"${hot}>CPU ${n.cpu_percent.toFixed(0)} % · ${n.cpu_temp != null ? n.cpu_temp + " °C" : "– °C"} · RAM ${n.mem_percent.toFixed(0)} % · Disk ${n.disk_percent.toFixed(0)} %</div>
    <div class="small">Laufzeit: ${fmtDuration(n.uptime_s)}</div></div></div>`;
}

async function refreshCluster() {
  const c = await apiGet("/api/cluster-status");
  const badge = byId("activePiBadge");
  const card = byId("clusterCard");
  if (!c.two_pi) { badge.classList.add("d-none"); card.classList.add("d-none"); return; }
  const label = n => `${n.kind === "bad" ? "Bad-Pi" : n.kind === "koffer" ? "Koffer-Pi" : "Pi"} (${n.hostname || n.peer_ip || "?"})`;
  const warn = !c.peer.reachable || (c.peer.redis && c.peer.redis.role === "slave" && c.peer.redis.link !== "up");
  badge.textContent = c.active_hostname
    ? "Aktiv: " + (c.active_kind === "bad" ? "Bad-Pi" : c.active_kind === "koffer" ? "Koffer-Pi" : c.active_hostname)
    : "Aktiver Pi unbekannt";
  badge.className = "badge " + (!c.active_hostname ? "text-bg-danger" : warn ? "text-bg-warning" : "text-bg-success");
  card.classList.remove("d-none");
  byId("clusterSummary").innerHTML = !c.peer.reachable
    ? `<span class="text-danger">Partner-Pi nicht erreichbar – keine Sicherung, bitte prüfen.</span>`
    : warn ? `<span class="text-warning">Kopie noch nicht synchron.</span>` : `<span class="text-success">Beide Pis erreichbar, Daten synchron.</span>`;
  byId("clusterNodes").innerHTML = nodeCardHtml(c.self, label(c.self) + " – dieser Server") + nodeCardHtml(c.peer, label(c.peer));
  const w = Object.entries(c.tasters_per_wifi || {}).map(([s, n]) => `${s}: ${n}`).join(" · ");
  byId("clusterWifi").textContent = w ? "Taster online je WLAN: " + w : "Keine Taster online.";
}

// -----------------------------
// Init
// -----------------------------
async function init() {
  try {
    const v = await apiGet("/api/version");
    byId("appVersion").textContent = v.version || "–";
  } catch {}

  await loadSettingsIntoUI();
  await loadStartcardsFromBackend().catch(() => updateStartcardsStatusLine());

  byId("laufSelect").addEventListener("change", (e) => {
    currentRun = e.target.value;
    renderLanesTable();
  });

  byId("btnSetRun").addEventListener("click", async () => {
    const run = byId("laufSelect").value;
    if (!run) return;
    const nextAttempt = attemptNumberForRun(run) + 1;
    const attemptLabel = nextAttempt === 1 ? String(run) : `${run}/${nextAttempt}`;
    if (!confirm(`Lauf ${run} als neue Version ${attemptLabel} vorbereiten?\nBisherige Zeiten bleiben erhalten. Der Start ist erst nach Ablauf der Stopp-Sperre möglich.`)) return;
    try {
      await apiPost("/api/current-run", { run: Number(run) });
      currentRun = run;
      await loadRunStatus();
      renderLanesTable();
      alert(`Lauf ${runStatus.current_key} vorbereitet. Start in ${Math.ceil(runStatus.start_lockout_remaining_s || 0)} Sekunden möglich.`);
    } catch (e) {
      alert("Vorbereiten fehlgeschlagen: " + e.message);
    }
  });

  byId("btnReloadStartcards").addEventListener("click", async () => {
    const baseUrl = byId("baseUrlInput").value.trim();
    const suffix = byId("suffixDisplay").value.trim();
    byId("startcardsStatus").textContent = "Status: lade Startkarten…";
    try {
      await apiPost("/api/startcards/reload", { base_url: baseUrl, suffix: suffix });
      await loadSettingsIntoUI();
      await loadStartcardsFromBackend();
    } catch (e) {
      byId("startcardsStatus").textContent = "Status: Fehler: " + e.message;
      byId("startcardsStatus").classList.add("text-danger");
    }
  });

  byId("btnSaveSettings").addEventListener("click", async () => {
    const baseUrl = byId("baseUrlInputSettings").value.trim();
    const suffix = byId("suffixInput").value.trim();
    try {
      await apiPost("/api/settings", {
        startcards_base_url: baseUrl,
        startcards_suffix: suffix,
        auto_next_run_s: byId("autoNextInput").value,
        stop_lockout_s: byId("stopLockoutInput").value,
        shutdown_grace_s: byId("shutdownGraceInput").value
      });
      // mirror to main tab
      await loadSettingsIntoUI();
      const msg = byId("settingsSavedMsg");
      msg.classList.remove("d-none");
      setTimeout(() => msg.classList.add("d-none"), 1500);
    } catch (e) {
      alert("Speichern fehlgeschlagen: " + e.message);
    }
  });

  byId("btnEndCompetition").addEventListener("click", async event => {
    const confirmed = window.confirm(
      "Wettkampf wirklich beenden?\n\n" +
      "Startkarten, Laufzeiten, Ergebnisse und Taster-Zuordnungen werden gelöscht. " +
      "Erreichbare Taster schalten sich aus."
    );
    if (!confirmed) return;

    const button = event.currentTarget;
    button.disabled = true;
    try {
      const result = await apiPost("/api/competition/end");
      startcards = { rows: [], max_lane: 0, runs: [], source_url: null, last_fetch_ts: null, error: null };
      currentRun = null;
      maxLane = 10;
      byId("maxLaneLabel").textContent = String(maxLane);
      updateRunSelect([]);
      updateStartcardsStatusLine();
      await Promise.all([loadButtons(), loadRunStatus()]);
      alert(`Wettkampf beendet. Der Abschaltbefehl ist ${result.shutdown_grace_s} Sekunden aktiv.`);
    } catch (e) {
      alert("Wettkampf konnte nicht beendet werden: " + e.message);
    } finally {
      button.disabled = false;
    }
  });

  byId("btnClearStarter").addEventListener("click", () => unassignLane("starter"));
  byId("tasterList").addEventListener("click", ev => {
    const b = ev.target.closest(".btn-unassign");
    if (b) unassignLane(b.dataset.lane);
  });

  byId("btnRefreshTaster").addEventListener("click", () => loadButtons().catch(e => alert("Taster laden fehlgeschlagen: " + e.message)));
  byId("btnRefreshStatus").addEventListener("click", () => refreshSystemStatus().catch(e => alert("Status laden fehlgeschlagen: " + e.message)));

  // initial loads
  await refreshSystemStatus().catch(() => {});
  setInterval(() => refreshCluster().catch(() => {}), 10000);
  await loadButtons().catch(() => {});
  renderTestButtons();
  await loadRunStatus().catch(() => {});
  // Beim Start den Lauf anzeigen, der auf dem Server aktuell ist
  const serverRun = String(runStatus.current_run ?? "");
  if (serverRun && [...byId("laufSelect").options].some(o => o.value === serverRun)) {
    byId("laufSelect").value = serverRun;
    currentRun = serverRun;
    renderLanesTable();
  }
  setInterval(() => { loadRunStatus().catch(() => {}); }, 500);
  setInterval(updateClocks, 50);
  // Taster-Liste regelmaessig aktualisieren (nicht waehrend Drag&Drop)
  setInterval(() => {
    if (document.querySelector(".taster-card.dragging")) return;
    loadButtons().catch(() => {});
  }, 5000);
  // keep suffix display in sync with settings input
  byId("suffixInput").addEventListener("input", () => { byId("suffixDisplay").value = byId("suffixInput").value; });
  byId("baseUrlInputSettings").addEventListener("input", () => { byId("baseUrlInput").value = byId("baseUrlInputSettings").value; });
  byId("suffixDisplay").value = byId("suffixInput").value;
  byId("baseUrlInput").addEventListener("input", () => { byId("baseUrlInputSettings").value = byId("baseUrlInput").value; });

  // Live-Ansicht des Exports (/legacy/heats.xml), wie ihn JAuswertung abholt
  let exportTimer = null;
  const fmtMs = ms => {
    const cs = Math.floor(ms / 10);
    const pad = (n, l = 2) => String(n).padStart(l, "0");
    return `${pad(Math.floor(cs / 6000))}:${pad(Math.floor(cs / 100) % 60)},${pad(cs % 100)}`;
  };
  async function refreshExport() {
    try {
      const res = await fetch("/legacy/heats.xml", { cache: "no-store" });
      const text = await res.text();
      byId("exportRaw").textContent = text;
      const doc = new DOMParser().parseFromString(text, "application/xml");
      if (doc.querySelector("parsererror")) throw new Error("XML nicht lesbar");
      const rows = [];
      doc.querySelectorAll("AlphaServer\\.Heat").forEach(h => {
        const ev = h.querySelector(":scope > event")?.textContent;
        const heat = h.querySelector(":scope > heat")?.textContent;
        h.querySelectorAll(":scope > lanes > entry").forEach(e => {
          const idx = Number(e.querySelector("laneindex")?.textContent);
          const ms = Number(e.querySelector("times > long")?.textContent);
          rows.push(`<tr><td>${ev}</td><td>${heat}</td><td>${idx + 1}</td><td>${fmtMs(ms)}</td><td>${ms}</td></tr>`);
        });
      });
      byId("exportRows").innerHTML = rows.join("") || `<tr><td colspan="5" class="text-muted">Noch keine Zeiten im Export.</td></tr>`;
      const heats = doc.querySelectorAll("AlphaServer\\.Heat").length;
      byId("exportInfo").textContent = `${heats} Lauf/Läufe, aktualisiert ${new Date().toLocaleTimeString()} (Bahn = Anzeige 1-basiert, im XML ab 0)`;
    } catch (e) {
      byId("exportInfo").textContent = `Fehler: ${e.message}`;
    }
  }
  byId("btnToggleExport").addEventListener("click", () => {
    const view = byId("exportView");
    const open = view.classList.toggle("d-none") === false;
    byId("btnToggleExport").textContent = open ? "Live-Ansicht schließen" : "Live-Ansicht öffnen";
    clearInterval(exportTimer);
    if (open) { refreshExport(); exportTimer = setInterval(refreshExport, 2000); }
  });

  // JAuswertung haengt Port 1999 und /legacy/heats.xml selbst an: eingetragen wird nur die IP
  byId("alphaServerValue").value = location.hostname;
  byId("alphaServerUrl").textContent = `http://${location.hostname}:1999/legacy/heats.xml`;
  byId("btnCopyAlpha").addEventListener("click", async () => {
    const input = byId("alphaServerValue");
    try { await navigator.clipboard.writeText(input.value); }
    catch { input.select(); document.execCommand("copy"); }
    const msg = byId("alphaCopiedMsg");
    msg.classList.remove("d-none");
    setTimeout(() => msg.classList.add("d-none"), 2000);
  });
}

document.addEventListener("DOMContentLoaded", () => { init(); });
