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
  const data = await apiGet("/api/taster-list");
  const tasters = data.tasters || [];
  buttons = tasters.map((t, idx) => {
    const letter = t.letter || "";
    const id = t.id || ("T-" + (letter || String.fromCharCode(65 + (idx % 26))));
    return {
      id,
      mac: t.mac || "",
      letter,
      role: t.role || "none",
      lane: t.lane,
      last_seen_ms: t.last_seen_ms || null,
      last_event_type: t.last_event_type || null,
      battery_percent: t.last_battery_percent ?? null,
      rssi_dbm: t.last_rssi_dbm ?? null
    };
  });

  resetAssignments();

  // initial assignment from backend fields (role/lane)
  buttons.forEach(btn => {
    if (btn.role === "bahn" && btn.lane != null) {
      const ln = Number(btn.lane);
      if (!isNaN(ln) && ln >= 1 && ln <= maxLane) {
        if (!laneAssignments[ln].active) laneAssignments[ln].active = btn.id;
        else if (laneAssignments[ln].active !== btn.id) laneAssignments[ln].pending = btn.id;
      }
    }
  });

  renderButtonList();
  renderLanesTable();
  byId("tasterLastRefresh").textContent = "Letzte Aktualisierung: " + new Date().toLocaleTimeString();
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
      slotLabel = slotInfo.slot + (slotInfo.role.endsWith("pending") ? " (neu)" : " (aktiv)");
    }

    const letter = btn.letter || "?";
    div.innerHTML = `
      <div class="taster-header">
        <span>Taster ${escapeHtml(letter)}</span>
        <span class="taster-badge">${escapeHtml(slotLabel)}</span>
      </div>
      <div class="taster-mac">${escapeHtml(btn.mac)}</div>
      <div class="small mt-1 text-muted">
        Akku: ${btn.battery_percent != null ? escapeHtml(btn.battery_percent) + "%" : "–"} |
        RSSI: ${btn.rssi_dbm != null ? escapeHtml(btn.rssi_dbm) + " dBm" : "–"}
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
      if (lane) assignButtonToLane(btnId, Number(lane));
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
      if (activeBtn && pendingBtn && pendingBtn.id !== activeBtn.id) extra = ` <span class="text-muted">(neu: ${escapeHtml(pendingBtn.letter || "?")})</span>`;
      tasterHtml = `<div class="taster-assigned"><strong>Taster ${escapeHtml(main)}</strong>${extra}</div>`;
    }

    tr.innerHTML = `
      <td>${b}</td>
      <td>${escapeHtml(name)}</td>
      <td>${escapeHtml(startnr)}</td>
      <td>${escapeHtml(disz)}</td>
      <td><div class="drop-target" data-lane="${b}">${tasterHtml}</div></td>
    `;
    tbody.appendChild(tr);
  }

  byId("bahnenFooter").textContent = currentRun
    ? `Lauf ${currentRun}: ${runRows.length} Startkarten-Zeilen (nicht belegte Bahnen sind inaktiv).`
    : "Keine Laufdaten geladen.";

  attachDropTargets();
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
      await apiPost("/api/settings", { startcards_base_url: baseUrl, startcards_suffix: suffix });
      // mirror to main tab
      await loadSettingsIntoUI();
      const msg = byId("settingsSavedMsg");
      msg.classList.remove("d-none");
      setTimeout(() => msg.classList.add("d-none"), 1500);
    } catch (e) {
      alert("Speichern fehlgeschlagen: " + e.message);
    }
  });

  byId("btnRefreshTaster").addEventListener("click", () => loadButtons().catch(e => alert("Taster laden fehlgeschlagen: " + e.message)));
  byId("btnRefreshStatus").addEventListener("click", () => refreshSystemStatus().catch(e => alert("Status laden fehlgeschlagen: " + e.message)));

  // initial loads
  await refreshSystemStatus().catch(() => {});
  await loadButtons().catch(() => {});
  // keep suffix display in sync with settings input
  byId("suffixInput").addEventListener("input", () => { byId("suffixDisplay").value = byId("suffixInput").value; });
  byId("baseUrlInputSettings").addEventListener("input", () => { byId("baseUrlInput").value = byId("baseUrlInputSettings").value; });
  byId("suffixDisplay").value = byId("suffixInput").value;
  byId("baseUrlInput").addEventListener("input", () => { byId("baseUrlInputSettings").value = byId("baseUrlInput").value; });
}

document.addEventListener("DOMContentLoaded", () => { init(); });
