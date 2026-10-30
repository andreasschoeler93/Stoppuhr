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
// Vitaldaten-Diagramme (Canvas, ohne Bibliothek)
// -----------------------------
const VITAL_CHARTS = [
  { idx: 1, title: "Akku", unit: "%", color: "#198754", min: 0, max: 100 },
  { idx: 2, title: "Akkuspannung", unit: "V", color: "#0d6efd", decimals: 2 },
  { idx: 3, title: "Temperatur", unit: "°C", color: "#dc3545", decimals: 1 },
  { idx: 4, title: "Luftfeuchte", unit: "%", color: "#0dcaf0", decimals: 0 },
  { idx: 5, title: "WLAN-Stärke", unit: "dBm", color: "#6f42c1", decimals: 0 },
];
// Pi-Diagramme: idx zeigt auf die Spalte im Pi-Messpunkt [ts, CPU-Temperatur, CPU-Last, Speicher]
const PI_CHARTS = [
  { id: "pi1", idx: 1, idx2: 2, title: "Pi CPU-Temperatur (durchgezogen) und CPU-Last (gestrichelt)", unit: "°C / %", pi: true, min: 0, max: 100 },
];
const PI_COLORS = { "Koffer-Pi": "#0d6efd", "Bad-Pi": "#fd7e14", "Pi": "#0d6efd" };
let vitalsData = null;
const TASTER_COLORS = ["#0d6efd", "#dc3545", "#198754", "#fd7e14", "#6f42c1", "#0dcaf0", "#d63384", "#795548", "#6c757d", "#20c997"];

async function refreshVitals() {
  const list = ((await apiGet("/api/taster")).tasters || [])
    .slice().sort((a, b) => String(a.letter || "~").localeCompare(String(b.letter || "~")));
  const hours = byId("vitalsHours").value;
  let starts = [];
  const series = await Promise.all(list.map(async (t, i) => {
    const d = await apiGet(`/api/vitals/history?mac=${encodeURIComponent(t.mac)}&hours=${hours}`).catch(() => ({ points: [] }));
    if (d.starts && d.starts.length) starts = d.starts;
    return { label: `Taster ${t.letter || "?"}`, color: TASTER_COLORS[i % TASTER_COLORS.length], points: d.points || [] };
  }));
  const pi = await apiGet(`/api/vitals/pi?hours=${hours}`).catch(() => ({ nodes: [] }));
  if (!starts.length && pi.starts) starts = pi.starts;
  const piNodes = pi.nodes || [];
  await refreshCharger().catch(() => {});
  const piSeries = piNodes.map(n => ({ label: n.name, color: PI_COLORS[n.name] || "#0d6efd", points: n.points || [] }));
  vitalsData = { hours: Number(hours), series, starts: starts || [], tasters: list, piNodes, piSeries };
  drawVitals();
}

// Grenzwerte: low = Wert darunter, high = Wert darüber. [gelb ab, rot ab]
// Standardwerte; die gespeicherten Werte kommen vom Server (GET /api/limits, Einstellungen → Grenzwerte)
const LIMITS = {
  taster: {
    battery: { low: [30, 15] }, vbat: { low: [3.5, 3.3] }, temp: { high: [45, 55] },
    humidity: { high: [80, 90] }, rssi: { low: [-75, -85] },
  },
  pi: {
    cpu_temp: { high: [70, 80] }, cpu_percent: { high: [85, 95] },
    mem_percent: { high: [85, 95] }, disk_percent: { high: [85, 95] },
  },
  charger: { temp: { high: [45, 60] }, humidity: { high: [80, 90] }, rssi: { low: [-75, -85] } },
  finish: { diff: { high: [0.5, 1] } },
};

// Beschriftung der Einstellungen: [Gruppe, Schlüssel, Name, Einheit, Schrittweite]
const LIMIT_DEFS = [
  ["taster", "battery", "Taster: Akku", "%", 1],
  ["taster", "vbat", "Taster: Akkuspannung", "V", 0.01],
  ["taster", "temp", "Taster: Temperatur", "°C", 1],
  ["taster", "humidity", "Taster: Luftfeuchte", "%", 1],
  ["taster", "rssi", "Taster: WLAN-Signal", "dBm", 1],
  ["pi", "cpu_temp", "Pi: CPU-Temperatur", "°C", 1],
  ["pi", "cpu_percent", "Pi: CPU-Last", "%", 1],
  ["pi", "mem_percent", "Pi: Speicher", "%", 1],
  ["pi", "disk_percent", "Pi: SD-Karte", "%", 1],
  ["charger", "temp", "Ladekoffer: Temperatur", "°C", 1],
  ["charger", "humidity", "Ladekoffer: Luftfeuchte", "%", 1],
  ["charger", "rssi", "Ladekoffer: WLAN-Signal", "dBm", 1],
  ["finish", "diff", "Zieleinlauf: Abweichung zur Bahnzeit (±)", "s", 0.1],
];

function applyLimits(serverLimits) {
  Object.entries(serverLimits || {}).forEach(([group, rules]) => {
    Object.entries(rules).forEach(([key, rule]) => {
      if (LIMITS[group] && LIMITS[group][key] && Array.isArray(rule.values)) {
        LIMITS[group][key] = { [rule.dir]: rule.values.map(Number) };
      }
    });
  });
}

function renderLimitsForm() {
  byId("limitsBody").innerHTML = LIMIT_DEFS.map(([group, key, label, unit, step]) => {
    const rule = LIMITS[group][key], low = !!rule.low, values = rule.low || rule.high;
    const input = (i, color) => `<input type="number" step="${step}" class="form-control form-control-sm limit-input"
      data-group="${group}" data-key="${key}" data-idx="${i}" value="${values[i]}" style="border-color:${color}">`;
    return `<tr><td>${label}</td><td class="small text-muted">${low ? "Wert darunter ist schlecht" : "Wert darüber ist schlecht"}</td>
      <td>${input(0, "#ffc107")}</td><td>${input(1, "#dc3545")}</td><td>${unit}</td></tr>`;
  }).join("");
}

async function loadLimits() {
  const data = await apiGet("/api/limits");
  applyLimits(data.limits);
  renderLimitsForm();
}

async function saveLimits(reset) {
  const err = byId("limitsError");
  err.classList.add("d-none");
  const limits = {};
  document.querySelectorAll(".limit-input").forEach(inp => {
    const { group, key, idx } = inp.dataset;
    limits[group] = limits[group] || {};
    limits[group][key] = limits[group][key] || { values: [null, null] };
    limits[group][key].values[Number(idx)] = inp.value;
  });
  try {
    const res = await apiPost("/api/limits", reset ? { reset: true } : { limits });
    applyLimits(res.limits);
    renderLimitsForm();
    const msg = byId("limitsSavedMsg");
    msg.classList.remove("d-none");
    setTimeout(() => msg.classList.add("d-none"), 1500);
    refreshAllAlerts();
    loadButtons().catch(() => {});
    if (vitalsData && byId("vitals").classList.contains("active")) drawVitals();
  } catch (e) {
    err.textContent = e.message;
    err.classList.remove("d-none");
  }
}

// Liefert "danger" (rot), "warning" (gelb) oder null
function limitLevel(value, rule) {
  if (value === null || value === undefined || !rule || Number.isNaN(Number(value))) return null;
  const v = Number(value);
  if (rule.low) return v <= rule.low[1] ? "danger" : v <= rule.low[0] ? "warning" : null;
  if (rule.high) return v >= rule.high[1] ? "danger" : v >= rule.high[0] ? "warning" : null;
  return null;
}

function levelHtml(text, level) {
  return level ? `<span class="val-${level}">${text}</span>` : text;
}

// Banner oben für Taster, Pis und Ladekoffer-Messwerte (Ladeplatine-Fehler kommen aus refreshCharger)
function sensorAlerts(tasters, piNodes) {
  const alerts = [];
  const push = (level, text) => { if (level) alerts.push({ level, text }); };
  const word = level => level === "danger" ? "kritisch" : "auffällig";
  const check = (who, value, rule, label, dec, unit) => {
    const level = limitLevel(value, rule);
    push(level, `${who}: ${label} ${word(level)} (${Number(value).toFixed(dec)} ${unit}).`);
  };
  tasters.forEach(t => {
    const who = `Taster ${t.letter || "?"}`, lim = LIMITS.taster;
    if (!t.online) {
      // Nur Taster mit Rolle (Starter oder Bahn) sind im Betrieb gebraucht; freie Taster dürfen im Koffer liegen
      if (t.roleText) push("danger", `${who} (${t.roleText}) ist offline.`);
      return;
    }
    check(who, t.battery, lim.battery, "Akku", 0, "%");
    check(who, t.vbat, lim.vbat, "Akkuspannung", 2, "V");
    check(who, t.temp, lim.temp, "Temperatur", 1, "°C");
    check(who, t.humidity, lim.humidity, "Luftfeuchte", 0, "%");
    check(who, t.rssi, lim.rssi, "WLAN-Signal", 0, "dBm");
  });
  piNodes.forEach(n => {
    const who = n.name || "Pi", lim = LIMITS.pi;
    if (!n.reachable) { push("danger", `${who}: nicht erreichbar.`); return; }
    check(who, n.cpu_temp, lim.cpu_temp, "CPU-Temperatur", 1, "°C");
    check(who, n.cpu_percent, lim.cpu_percent, "CPU-Last", 0, "%");
    check(who, n.mem_percent, lim.mem_percent, "Speicher", 0, "%");
    check(who, n.disk_percent, lim.disk_percent, "SD-Karte", 0, "%");
  });
  const c = chargerData && chargerData.known && chargerData.online ? chargerData.status : null;
  if (c) {
    check("Ladekoffer", c.temp, LIMITS.charger.temp, "Temperatur", 1, "°C");
    check("Ladekoffer", c.humidity, LIMITS.charger.humidity, "Luftfeuchte", 0, "%");
    check("Ladekoffer", c.rssi, LIMITS.charger.rssi, "WLAN-Signal", 0, "dBm");
  }
  return alerts;
}

async function refreshSensorAlerts() {
  const [map, pi] = await Promise.all([
    apiGet("/api/mapping").catch(() => ({})),
    apiGet("/api/vitals/pi?hours=1").catch(() => ({ nodes: [] })),
  ]);
  const tasters = [];
  if (map.starter) tasters.push({ ...map.starter, roleText: "Starter" });
  if (map.finish) tasters.push({ ...map.finish, roleText: "Zieleinlauf" });
  Object.keys(map.mapping || {}).forEach(lane => {
    if (map.mapping[lane]) tasters.push({ ...map.mapping[lane], roleText: `Bahn ${lane}` });
  });
  (map.unmapped_taster || []).forEach(t => tasters.push(t));
  const alerts = sensorAlerts(tasters, pi.nodes || []);
  byId("sensorAlerts").innerHTML = alerts
    .map(a => `<div class="alert alert-${a.level} py-1 px-2 small mb-2">${escapeHtml(a.text)}</div>`).join("");
}

function piStatusHtml() {
  const nodes = vitalsData.piNodes || [];
  if (!nodes.length) return "";
  const num = (v, dec, unit, rule) => (v === null || v === undefined) ? "–" : levelHtml(`${Number(v).toFixed(dec)} ${unit}`, limitLevel(v, rule));
  const up = s => s === null || s === undefined ? "–" : (s >= 86400 ? `${Math.floor(s / 86400)} d ${Math.floor(s % 86400 / 3600)} h` : `${Math.floor(s / 3600)} h ${Math.floor(s % 3600 / 60)} min`);
  const rows = [
    ["Status", n => !n.reachable ? '<span class="badge text-bg-danger">nicht erreichbar</span>'
      : (n.active ? '<span class="badge text-bg-success">arbeitet</span>' : '<span class="badge text-bg-secondary">Bereitschaft</span>')],
    ["CPU-Temp.", n => num(n.cpu_temp, 1, "°C", LIMITS.pi.cpu_temp)],
    ["CPU-Last", n => num(n.cpu_percent, 0, "%", LIMITS.pi.cpu_percent)],
    ["Speicher", n => num(n.mem_percent, 0, "%", LIMITS.pi.mem_percent)],
    ["SD-Karte", n => num(n.disk_percent, 0, "%", LIMITS.pi.disk_percent)],
    ["Laufzeit", n => up(n.uptime_s)],
  ];
  const head = nodes.map(n => `<th class="text-center" style="color:${PI_COLORS[n.name] || "#0d6efd"}">${escapeHtml(n.name)}</th>`).join("");
  const body = rows.map(([name, f]) => `<tr><th class="text-nowrap fw-normal">${name}</th>${
    nodes.map(n => `<td class="text-center text-nowrap">${f(n)}</td>`).join("")}</tr>`).join("");
  return `<div class="table-responsive mt-2"><table class="table table-sm align-middle mb-0"><thead><tr><th></th>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function vitalsStatusHtml() {
  const list = vitalsData.tasters || [];
  const num = (v, dec, unit, rule) => (v === null || v === undefined) ? "–" : levelHtml(`${Number(v).toFixed(dec)} ${unit}`, limitLevel(v, rule));
  const rows = [
    ["Status", t => t.online ? '<span class="badge text-bg-success">online</span>' : '<span class="badge text-bg-secondary">offline</span>'],
    ["Akku", t => num(t.battery, 0, "%", LIMITS.taster.battery)],
    ["Spannung", t => num(t.vbat, 2, "V", LIMITS.taster.vbat)],
    ["Temperatur", t => num(t.temp, 1, "°C", LIMITS.taster.temp)],
    ["Luftfeuchte", t => num(t.humidity, 0, "%", LIMITS.taster.humidity)],
    ["WLAN", t => num(t.rssi, 0, "dBm", LIMITS.taster.rssi)],
  ];
  if (!list.length) return '<span class="text-muted small">Noch kein Taster angemeldet.</span>';
  const head = list.map((t, i) => `<th class="text-center" style="color:${TASTER_COLORS[i % TASTER_COLORS.length]}">${escapeHtml(t.letter || "?")}</th>`).join("");
  const body = rows.map(([name, f]) => `<tr><th class="text-nowrap fw-normal">${name}</th>${
    list.map(t => `<td class="text-center text-nowrap${t.online || name === "Status" ? "" : " text-muted"}">${f(t)}</td>`).join("")}</tr>`).join("");
  return `<div class="table-responsive"><table class="table table-sm align-middle mb-0"><thead><tr><th></th>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

// Ladekoffer: Status der Ladeplatine (kommt per WLAN an den Pi, GET /api/charger)
let chargerData = null;
const CHARGER_STATE = {
  bereit: ["text-bg-success", "Ladekoffer: bereit"],
  laedt: ["text-bg-warning", "Ladekoffer: lädt"],
  teilweise: ["text-bg-warning", "Ladekoffer: nicht komplett"],
  fehler: ["text-bg-danger", "Ladekoffer: Fehler"],
  offline: ["text-bg-secondary", "Ladekoffer: offline"],
};
const CHARGER_LEVEL = { error: "danger", warn: "warning", info: "info", ok: "success" };

async function refreshCharger() {
  chargerData = await apiGet("/api/charger");
  const badge = byId("chargerBadge"), box = byId("chargerAlerts");
  if (!chargerData.known) { badge.classList.add("d-none"); box.innerHTML = ""; return; }
  const [cls, label] = CHARGER_STATE[chargerData.state] || CHARGER_STATE.offline;
  badge.className = "badge " + cls;
  badge.textContent = label;
  // Oben nur, was Aufmerksamkeit braucht; alles andere steht im Tab "Vitaldaten"
  box.innerHTML = chargerData.messages.filter(m => m.level === "error" || m.level === "warn")
    .map(m => `<div class="alert alert-${CHARGER_LEVEL[m.level]} py-1 px-2 small mb-2">${escapeHtml(m.text)}</div>`).join("");
  if (vitalsData && byId("vitals").classList.contains("active")) drawVitals();
}

async function refreshAllAlerts() {
  await refreshCharger().catch(() => {});
  await refreshSensorAlerts().catch(() => {});
}

function chargerStatusHtml() {
  if (!chargerData || !chargerData.known) return "";
  const s = chargerData.status, slots = {};
  s.slots.forEach(x => { slots[x.n] = x; });
  const num = (v, dec, unit) => (v === null || v === undefined) ? "–" : `${Number(v).toFixed(dec)} ${unit}`;
  const cell = x => !x || !x.present ? '<span class="badge text-bg-secondary">fehlt</span>'
    : x.fault ? '<span class="badge text-bg-danger">Fehler</span>'
    : x.charging ? '<span class="badge text-bg-warning">lädt</span>'
    : x.full ? '<span class="badge text-bg-success">voll</span>' : '<span class="badge text-bg-light text-dark">da</span>';
  const nums = Array.from({ length: 10 }, (_, i) => i + 1);
  const head = nums.map(n => `<th class="text-center">${n}</th>`).join("");
  const rows = [["Zustand", x => cell(x)], ["Spannung", x => x && x.present ? num(x.vbat, 2, "V") : "–"]];
  const body = rows.map(([name, f]) => `<tr><th class="text-nowrap fw-normal">${name}</th>${
    nums.map(n => `<td class="text-center text-nowrap">${f(slots[n])}</td>`).join("")}</tr>`).join("");
  const [cls, label] = CHARGER_STATE[chargerData.state] || CHARGER_STATE.offline;
  const msgs = chargerData.messages.map(m => `<div class="small text-${CHARGER_LEVEL[m.level]}">${escapeHtml(m.text)}</div>`).join("");
  const lim = LIMITS.charger;
  const colored = (v, dec, unit, rule) => levelHtml(num(v, dec, unit), limitLevel(v, rule));
  const info = `Temperatur ${colored(s.temp, 1, "°C", lim.temp)} · Luftfeuchte ${colored(s.humidity, 0, "%", lim.humidity)} · WLAN ${colored(s.rssi, 0, "dBm", lim.rssi)} · Firmware ${escapeHtml(s.fw || "–")}`;
  return `<div class="mt-3"><strong class="small">Ladekoffer</strong> <span class="badge ${cls}">${label.replace("Ladekoffer: ", "")}</span>
    <div class="table-responsive mt-1"><table class="table table-sm align-middle mb-0"><thead><tr><th>Platz</th>${head}</tr></thead><tbody>${body}</tbody></table></div>
    <div class="small text-muted mt-1">${info}</div>${msgs}</div>`;
}

function drawVitals() {
  const box = byId("vitalsCharts");
  const s = vitalsData.series;
  const legend = x => `<span class="me-3"><span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:${x.color};vertical-align:-1px"></span> ${escapeHtml(x.label)}</span>`;
  byId("vitalsInfo").innerHTML = (s.length ? s.map(legend).join("") : "Noch kein Taster angemeldet.")
    + (vitalsData.piSeries.length ? ' <span class="text-muted me-2">|</span>' + vitalsData.piSeries.map(legend).join("") : "");
  if (!box.children.length) {
    box.innerHTML = VITAL_CHARTS.concat(PI_CHARTS).map(c => `<div class="col-lg-6"><div class="card"><div class="card-body p-2">
      <strong class="small">${c.title} (${c.unit})</strong>
      <canvas id="vc-${c.id || c.idx}" style="width:100%;height:180px"></canvas></div></div></div>`).join("") +
      `<div class="col-12"><div class="card h-100"><div class="card-body p-2">
      <strong class="small">Zustand der Taster und Pis</strong><div id="vitalsStatus" class="mt-1"></div></div></div></div>`;
  }
  byId("vitalsStatus").innerHTML = vitalsStatusHtml() + piStatusHtml() + chargerStatusHtml();
  VITAL_CHARTS.forEach(c => drawVitalChart(c, s));
  PI_CHARTS.forEach(c => drawVitalChart(c, vitalsData.piSeries));
}

function drawVitalChart(c, series) {
  const cv = byId("vc-" + (c.id || c.idx));
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth, h = cv.clientHeight;
  if (!w) return;
  cv.width = w * dpr; cv.height = h * dpr;
  const g = cv.getContext("2d");
  g.scale(dpr, dpr);
  g.clearRect(0, 0, w, h);
  const cols = c.idx2 ? [[c.idx, false], [c.idx2, true]] : [[c.idx, false]];
  const lines = cols.flatMap(([ci, dash]) => series.map(s => ({ dash, color: s.color, data: s.points.filter(p => p[ci] !== null).map(p => [p[0], p[ci]]) })));
  const all = lines.flatMap(l => l.data.map(d => d[1]));
  if (!all.length) { g.fillStyle = "#888"; g.font = "12px sans-serif"; g.fillText("keine Daten", 10, 20); return; }
  const dec = c.decimals ?? 0;
  const t1 = Date.now(), t0 = t1 - vitalsData.hours * 3600 * 1000;
  let lo = c.min ?? Math.min(...all);
  let hi = c.max ?? Math.max(...all);
  if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  if (c.min === undefined) { const pad = (hi - lo) * 0.1; lo -= pad; hi += pad; }
  const L = 42, R = 8, T = 8, B = 20;
  const x = t => L + (t - t0) / (t1 - t0) * (w - L - R);
  const y = v => T + (1 - (v - lo) / (hi - lo)) * (h - T - B);
  g.font = "11px sans-serif"; g.strokeStyle = "#e5e5e5"; g.fillStyle = "#666"; g.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * i / 4, yy = y(v);
    g.beginPath(); g.moveTo(L, yy); g.lineTo(w - R, yy); g.stroke();
    g.textAlign = "right"; g.fillText(v.toFixed(dec), L - 4, yy + 4);
  }
  g.textAlign = "center";
  for (let i = 0; i <= 3; i++) {
    const t = t0 + (t1 - t0) * i / 3;
    g.fillText(new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), x(t), h - 5);
  }
  // Laufstarts als senkrechte gestrichelte Linien mit Beschriftung (Lauf-Nr.)
  g.save();
  g.setLineDash([4, 3]); g.strokeStyle = "#444"; g.fillStyle = "#444"; g.lineWidth = 1; g.textAlign = "left";
  (vitalsData.starts || []).forEach(([t, key]) => {
    if (t < t0 || t > t1) return;
    const xx = x(t);
    g.beginPath(); g.moveTo(xx, T); g.lineTo(xx, h - B); g.stroke();
    g.fillText("L" + key, xx + 2, T + 9);
  });
  g.restore();
  g.lineWidth = 1.6;
  lines.forEach(l => {
    g.strokeStyle = l.color; g.setLineDash(l.dash ? [5, 3] : []); g.beginPath();
    let prev = null;
    l.data.forEach(([t, v]) => {
      // Luecke ueber 2 Minuten (Taster aus): Linie unterbrechen
      if (prev === null || t - prev > 120000) g.moveTo(x(t), y(v)); else g.lineTo(x(t), y(v));
      prev = t;
    });
    g.stroke();
  });
}

// -----------------------------
// Backend calls
// -----------------------------
async function apiGet(path) {
  const r = await fetch(path, { headers: { "Accept": "application/json" } });
  if (r.status === 401) { location.href = "/login"; throw new Error("Nicht angemeldet"); }
  if (!r.ok) throw new Error("HTTP " + r.status);
  return await r.json();
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify(body || {})
  });
  if (r.status === 401 && !path.startsWith("/api/auth/")) { location.href = "/login"; throw new Error("Nicht angemeldet"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok || (j && j.ok === false)) {
    const msg = (j && j.error) ? j.error : ("HTTP " + r.status);
    throw new Error(msg);
  }
  return j;
}

// -----------------------------
// Zugang und WLAN-Netze
// -----------------------------
let wifiInfo = null;
let wifiFilled = false;

function showError(id, text) {
  const el = byId(id);
  el.textContent = text || "";
  el.classList.toggle("d-none", !text);
}

async function refreshAccount() {
  const s = await apiGet("/api/auth/status");
  byId("accountUser").textContent = s.user || "–";
}

async function saveAccount() {
  showError("accountError", "");
  try {
    await apiPost("/api/auth/change", {
      current: byId("accCurrent").value,
      user: byId("accUser").value.trim(),
      password: byId("accPassword").value
    });
  } catch (e) {
    showError("accountError", e.message);
    return;
  }
  for (const id of ["accCurrent", "accUser", "accPassword"]) byId(id).value = "";
  await refreshAccount().catch(() => {});
  alert("Zugang geändert.");
}

async function logout() {
  await apiPost("/api/auth/logout").catch(() => {});
  location.href = "/login";
}

async function refreshWifi() {
  wifiInfo = await apiGet("/api/wifi-config");
  const i = wifiInfo;
  // Felder nur beim ersten Laden befuellen, damit Eingaben nicht ueberschrieben werden
  if (!wifiFilled && i.configured) {
    byId("wifiSsid1").value = i.ssid1;
    byId("wifiSsid2").value = i.ssid2;
    wifiFilled = true;
  }
  const lines = [];
  let waiting = false;
  if (i.configured) {
    const t = i.tasters;
    lines.push(`Taster: ${t.acked.length} von ${t.online.length} online haben die neuen Daten bestätigt` +
      (t.missing.length ? ` (es fehlen: ${t.missing.map(escapeHtml).join(", ")})` : ""));
    for (const p of i.pis) {
      const done = p.applied_ver >= i.version;
      if (!done) waiting = true;
      lines.push(`Pi ${escapeHtml(p.hostname || "")}${p.kind ? " (" + escapeHtml(p.kind) + ")" : ""}: ` +
        (done ? "umgestellt" : (i.force || (t.online.length && !t.missing.length) ? "wird umgestellt …" : "wartet auf die Taster")));
    }
  } else {
    lines.push("Noch keine Daten hinterlegt. Die Taster nutzen die Werte aus ihrer Firmware.");
  }
  byId("wifiStatus").innerHTML = lines.join("<br>");
  byId("btnWifiForce").classList.toggle("d-none", !(i.configured && waiting && !i.force));
}

async function saveWifi() {
  showError("wifiError", "");
  const body = {
    ssid1: byId("wifiSsid1").value.trim(), psk1: byId("wifiPsk1").value,
    ssid2: byId("wifiSsid2").value.trim(), psk2: byId("wifiPsk2").value
  };
  if (!window.confirm("WLAN-Daten ändern? Erst übernehmen die Taster sie, danach stellen die Pis ihr WLAN um. Die Verbindung zur Oberfläche kann kurz abbrechen.")) return;
  try {
    try {
      await apiPost("/api/wifi-config", body);
    } catch (e) {
      if (e.message !== "locked") throw e;
      const typed = window.prompt(
        `ACHTUNG: Der Wettkampf läuft bereits. Zur Bestätigung ${wifiInfo.confirm_text} eintippen:`);
      if (typed !== wifiInfo.confirm_text) return;
      await apiPost("/api/wifi-config", { ...body, confirm: typed });
    }
  } catch (e) {
    showError("wifiError", e.message);
    return;
  }
  byId("wifiPsk1").value = "";
  byId("wifiPsk2").value = "";
  await refreshWifi().catch(() => {});
}

async function forceWifi() {
  if (!window.confirm("Die Pis jetzt umstellen? Taster, die noch nicht bestätigt haben, finden das Netz danach evtl. nicht mehr.")) return;
  try {
    await apiPost("/api/wifi-config/force");
  } catch (e) {
    showError("wifiError", e.message);
    return;
  }
  await refreshWifi().catch(() => {});
}

// -----------------------------
// Taster-Firmware
// -----------------------------
let fwInfo = null;

async function refreshFirmware() {
  fwInfo = await apiGet("/api/firmware/releases");
  const sel = byId("fwSelect");
  const previous = sel.value;
  sel.replaceChildren(...fwInfo.releases.map(r => {
    const o = document.createElement("option");
    o.value = r.tag;
    o.textContent = r.tag + (r.cached ? " (auf dem Pi gespeichert)" : "");
    return o;
  }));
  if (previous && [...sel.options].some(o => o.value === previous)) sel.value = previous;
  const err = byId("fwError");
  err.textContent = fwInfo.error || "";
  err.classList.toggle("d-none", !fwInfo.error);
  byId("fwLocked").classList.toggle("d-none", !fwInfo.competition_started);
  const target = fwInfo.target;
  const tbody = byId("fwTasters");
  tbody.replaceChildren(...fwInfo.tasters.map(t => {
    const tr = document.createElement("tr");
    let status = "–";
    if (target && target.macs.includes(t.mac)) {
      const st = (target.status || {})[t.mac];
      if (t.fw === target.tag) status = "fertig";
      else if (st && st.state === "failed") status = "fehlgeschlagen (" + (st.msg || "") + ")";
      else status = "wartet / lädt " + target.tag;
    }
    for (const text of [`${t.letter || ""} ${t.name || ""}`.trim(), t.online ? "ja" : "nein", t.fw || "?", status]) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    }
    return tr;
  }));
}

async function deployFirmware() {
  const tag = byId("fwSelect").value;
  if (!tag) return;
  const online = (fwInfo?.tasters || []).filter(t => t.online && t.fw !== tag).length;
  if (!window.confirm(`Firmware ${tag} auf ${online} online Taster laden?`)) return;
  let confirmText = "";
  if (fwInfo?.competition_started) {
    const typed = window.prompt(
      "ACHTUNG: Der Wettkampf läuft bereits. Ein Update kann Läufe stören.\n\n" +
      `Zur Bestätigung ${fwInfo.confirm_text} eintippen:`
    );
    if (typed !== fwInfo.confirm_text) return;
    confirmText = typed;
  }
  const btn = byId("btnFwDeploy");
  btn.disabled = true;
  try {
    await apiPost("/api/firmware/deploy", { tag, confirm: confirmText });
    await refreshFirmware();
  } catch (e) {
    alert("Update nicht gestartet: " + e.message);
  } finally {
    btn.disabled = false;
  }
}

// -----------------------------
// Pi-Software
// -----------------------------
let piInfo = null;

async function refreshPiUpdate() {
  piInfo = await apiGet("/api/pi-update/releases");
  const cur = piInfo.current || {};
  const where = cur.tag || (cur.branch ? cur.branch + " @ " : "") + (cur.commit || "");
  byId("piCurrent").textContent = `v${piInfo.version}` + (where ? ` (${where})` : "");
  const sel = byId("piSelect");
  const previous = sel.value;
  sel.replaceChildren(...piInfo.tags.map(tag => {
    const o = document.createElement("option");
    o.value = tag;
    o.textContent = tag + (tag === cur.tag ? " (läuft)" : "");
    return o;
  }));
  if (previous && [...sel.options].some(o => o.value === previous)) sel.value = previous;
  else if (cur.tag && [...sel.options].some(o => o.value === cur.tag)) sel.value = cur.tag;
  const err = byId("piError");
  err.textContent = piInfo.error || "";
  err.classList.toggle("d-none", !piInfo.error);
  byId("piLocked").classList.toggle("d-none", !piInfo.competition_started);
  byId("btnPiDeploy").disabled = !piInfo.supported;
}

async function deployPi() {
  const tag = byId("piSelect").value;
  if (!tag) return;
  if (!window.confirm(`Pi-Software auf ${tag} wechseln? Der Dienst startet neu.`)) return;
  let confirmText = "";
  if (piInfo?.competition_started) {
    const typed = window.prompt(
      "ACHTUNG: Der Wettkampf läuft bereits. Der Neustart unterbricht den Server kurz.\n\n" +
      `Zur Bestätigung ${piInfo.confirm_text} eintippen:`
    );
    if (typed !== piInfo.confirm_text) return;
    confirmText = typed;
  }
  const btn = byId("btnPiDeploy");
  btn.disabled = true;
  try {
    await apiPost("/api/pi-update/deploy", { tag, confirm: confirmText });
  } catch (e) {
    alert("Wechsel nicht möglich: " + e.message);
    btn.disabled = false;
    return;
  }
  btn.textContent = "Startet neu …";
  // Warten, bis der Dienst wieder antwortet, dann Seite neu laden
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 1000));
    try {
      await apiGet("/api/version");
      if (i >= 2) break;
    } catch (_) { /* noch nicht erreichbar */ }
  }
  location.reload();
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
  byId("starterIsFinishInput").checked = s.starter_is_finish === "1";
  byId("starterIsFinishQuick").checked = s.starter_is_finish === "1";
  byId("lowBatteryPctInput").value = s.low_battery_pct ?? "10";
  byId("lowBatteryMinInput").value = s.low_battery_min ?? "5";
  const rangeOn = s.range_test_on === "1";
  if (document.activeElement !== byId("rangeTestLetter")) byId("rangeTestLetter").value = s.range_test_letter || "";
  byId("btnRangeTest").textContent = rangeOn ? "Funktest beenden" : "Funktest starten";
  byId("btnRangeTest").classList.toggle("btn-danger", rangeOn);
  byId("btnRangeTest").classList.toggle("btn-outline-primary", !rangeOn);
  byId("rangeTestState").textContent = rangeOn ? `Läuft für Taster ${s.range_test_letter}` : "";
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
  if (data.finish) entries.push({ t: data.finish, role: "finish", lane: null });
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
  renderFinishBox();
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

// Wie vitalsText, aber Werte über/unter den Grenzwerten sind gelb oder rot
function vitalsHtml(btn) {
  if (!btn || !btn.online) return "offline";
  const lim = LIMITS.taster, parts = [];
  if (btn.battery_percent != null) {
    const bat = [limitLevel(btn.battery_percent, lim.battery), limitLevel(btn.vbat, lim.vbat)];
    const level = bat.includes("danger") ? "danger" : bat.includes("warning") ? "warning" : null;
    parts.push(levelHtml(escapeHtml(btn.battery_percent + "%" + (btn.vbat != null ? " (" + Number(btn.vbat).toFixed(2) + " V)" : "")), level));
  }
  if (btn.rssi_dbm != null) parts.push(levelHtml(escapeHtml(btn.rssi_dbm + " dBm"), limitLevel(btn.rssi_dbm, lim.rssi)));
  if (btn.ssid) parts.push(escapeHtml(btn.ssid));
  if (btn.temp != null) parts.push(levelHtml(escapeHtml(Number(btn.temp).toFixed(1) + " °C"), limitLevel(btn.temp, lim.temp)));
  if (btn.humidity != null) parts.push(levelHtml(escapeHtml(Number(btn.humidity).toFixed(0) + " % rF"), limitLevel(btn.humidity, lim.humidity)));
  return parts.join(" · ");
}

// Schlechtester Zustand eines Tasters: danger (rot), warning (gelb) oder "" (in Ordnung).
// Offline ist nur bei einem Taster mit Rolle (Starter oder Bahn) ein Problem.
function tasterLevel(btn, hasRole) {
  if (!btn) return "";
  if (!btn.online) return hasRole ? "danger" : "";
  const lim = LIMITS.taster;
  const levels = [limitLevel(btn.battery_percent, lim.battery), limitLevel(btn.vbat, lim.vbat),
    limitLevel(btn.temp, lim.temp), limitLevel(btn.humidity, lim.humidity), limitLevel(btn.rssi_dbm, lim.rssi)];
  return levels.includes("danger") ? "danger" : levels.includes("warning") ? "warning" : "";
}

// Bahnnummer als Zahl, Rollen (starter, ziel) als Text
function laneArg(lane) {
  return /^\d+$/.test(String(lane)) ? Number(lane) : String(lane);
}

async function swapNow(lane, mac) {
  try {
    await apiPost("/api/assign", { mac, lane: laneArg(lane), immediate: true });
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
  const lvl = tasterLevel(s, true);
  box.classList.remove("lvl-danger", "lvl-warning");
  if (lvl) box.classList.add("lvl-" + lvl);
  box.innerHTML = (s
    ? `<strong>Taster ${escapeHtml(s.letter || "?")}</strong> <span class="small text-muted">${escapeHtml(s.name)} · ${vitalsHtml(s)}</span>`
    : `<span class="text-muted small">kein Starter – Taster hierher ziehen</span>`) + pendingHtml;
}

function renderFinishBox() {
  const box = byId("finishDrop");
  const f = buttons.find(b => b.role === "finish");
  const p = buttons.find(b => b.role === "none" && b.pending_lane === "ziel");
  const pendingHtml = p
    ? `<div class="small text-warning">Bereitschaft: Taster ${escapeHtml(p.letter || "?")} wird beim ersten Druck Zieleinlauf</div>${pendingActionsHtml("ziel", p.mac)}`
    : "";
  const lvl = tasterLevel(f, true);
  box.classList.remove("lvl-danger", "lvl-warning");
  if (lvl) box.classList.add("lvl-" + lvl);
  box.innerHTML = (f
    ? `<strong>Taster ${escapeHtml(f.letter || "?")}</strong> <span class="small text-muted">${escapeHtml(f.name)} · ${vitalsHtml(f)}</span>`
    : `<span class="text-muted small">kein Zieleinlauf – Taster hierher ziehen (optional)</span>`) + pendingHtml;
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
    } else if (run.running && td.dataset.active === "1") {
      text = formatMs(now - run.starter_ts);
      cls += " text-primary";
    }
    if (td.textContent !== text) td.textContent = text;
    td.className = cls;
  });
  updateFinishUi(runKey, run);
}

function setHtmlIfChanged(el, html) {
  if (el._html === html) return;
  el._html = html;
  el.innerHTML = html;
}

// Zieleinlauf: Zuordnung je Bahn, nicht zugeordnete Zeiten, Übertragen-Button und Hinweis bei Abbruch durch den Starter
function updateFinishUi(runKey, run) {
  const fin = run.finish;
  document.querySelectorAll(".finish-cell").forEach(td => {
    const lane = td.dataset.lane;
    const m = fin && fin.matches[lane];
    let html = "";
    if (m) {
      const d = m.delta_ms;
      const diff = d == null ? "ohne Bahnzeit" : (d >= 0 ? "+" : "−") + (Math.abs(d) / 1000).toFixed(2) + " s";
      const level = d == null ? null : limitLevel(Math.abs(d) / 1000, LIMITS.finish.diff);
      const cls = d == null ? "text-primary" : level === "danger" ? "val-danger" : level === "warning" ? "val-warning" : "text-muted";
      html = `<span class="finish-chip" draggable="true" data-index="${m.index}" data-run-key="${escapeHtml(runKey || "")}">${formatMs(fin.times_ms[m.index])}</span> <span class="small ${cls}">(${diff})</span>`
        + ` <button type="button" class="btn btn-sm btn-link p-0 btn-finish-clear" data-lane="${escapeHtml(lane)}" title="Zeit parken">✕</button>`;
    }
    td.dataset.runKey = runKey || "";
    setHtmlIfChanged(td, html);
  });

  const pool = byId("finishPool");
  pool.dataset.runKey = runKey || "";
  const free = fin ? fin.unassigned : [];
  setHtmlIfChanged(pool, fin
    ? `<div class="small text-muted mb-1">Geparkte Zieleinlauf-Zeiten – per Drag &amp; Drop auf die Spalte „Zieleinlauf“ einer Bahn ziehen. Zugeordnete Zeiten lassen sich auf andere Bahnen oder hierher zurückziehen.</div>`
      + free.map(i => `<span class="finish-chip" draggable="true" data-index="${i}" data-run-key="${escapeHtml(runKey || "")}">${formatMs(fin.times_ms[i])}</span>`).join("")
      + (free.length ? "" : `<span class="small text-muted">keine</span>`)
    : "");

  // Übertragen: jedes Mal eine neue Laufversion (z. B. 5/2, 5/3); nicht zugeordnete Bahnen behalten ihre gestoppte Zeit
  const matches = fin ? Object.entries(fin.matches) : [];
  const versions = run.adopted || [];
  let transfer = "";
  if (matches.length || versions.length) {
    transfer = `<button type="button" class="btn btn-sm btn-primary btn-finish-transfer"${matches.length ? "" : " disabled"}>`
      + `Als neue Laufversion übertragen</button>`
      + (versions.length ? ` <button type="button" class="btn btn-sm btn-outline-secondary btn-finish-undo">Letzte Version zurücknehmen</button>` : "")
      + `<span class="small text-muted ms-2">${matches.length} Bahn(en) zugeordnet, übrige mit gestoppter Zeit`
      + (versions.length ? ` · übertragen: ${versions.map(v => escapeHtml(v.label)).join(", ")}` : "") + `</span>`;
  }
  const box = byId("finishTransfer");
  box.dataset.runKey = runKey || "";
  setHtmlIfChanged(box, transfer);

  let notice = "";
  if (run.stopped_by_starter) {
    const missing = [...document.querySelectorAll('.lane-time[data-active="1"]')]
      .filter(td => (run.times_ms || {})[td.dataset.lane] == null).map(td => td.dataset.lane);
    notice = `<div class="alert alert-warning py-1 px-2 small mb-2">Lauf ${escapeHtml(String(runKey))} wurde durch erneutes Drücken des Starters beendet.`
      + (missing.length ? ` Keine Zeit: Bahn ${missing.join(", ")}.` : "") + `</div>`;
  }
  setHtmlIfChanged(byId("runNotice"), notice);
}

document.addEventListener("dragstart", ev => {
  const chip = ev.target.closest && ev.target.closest(".finish-chip");
  if (!chip) return;
  ev.dataTransfer.setData("application/x-finish", JSON.stringify({ runKey: chip.dataset.runKey, index: Number(chip.dataset.index) }));
});

// Der Bereich der geparkten Zeiten nimmt Zeiten zurück
(function () {
  const pool = byId("finishPool");
  pool.addEventListener("dragover", ev => {
    if (!ev.dataTransfer.types.includes("application/x-finish")) return;
    ev.preventDefault();
    pool.classList.add("drop-hover");
  });
  pool.addEventListener("dragleave", () => pool.classList.remove("drop-hover"));
  pool.addEventListener("drop", ev => {
    ev.preventDefault();
    pool.classList.remove("drop-hover");
    let data;
    try { data = JSON.parse(ev.dataTransfer.getData("application/x-finish")); } catch (e) { return; }
    if (data && data.runKey) assignFinish(data.runKey, "park", data.index);
  });
})();

async function assignFinish(runKey, lane, index) {
  try {
    await apiPost("/api/finish/assign", { run_key: runKey, lane: String(lane), index });
    await loadRunStatus();
  } catch (e) {
    alert("Zuordnung fehlgeschlagen: " + e.message);
  }
}

async function transferFinish(runKey, undo) {
  try {
    await apiPost("/api/finish/transfer", { run_key: runKey, undo: !!undo });
    await loadRunStatus();
  } catch (e) {
    alert("Übertragen fehlgeschlagen: " + e.message);
  }
}

document.addEventListener("click", ev => {
  const clear = ev.target.closest(".btn-finish-clear");
  if (clear) assignFinish(clear.closest(".finish-cell").dataset.runKey, clear.dataset.lane, null);
  const box = byId("finishTransfer");
  if (ev.target.closest(".btn-finish-transfer")) transferFinish(box.dataset.runKey, false);
  if (ev.target.closest(".btn-finish-undo")) transferFinish(box.dataset.runKey, true);
});

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
    } else if (btn.role === "starter") {
      slotLabel = "STARTER (aktiv)";
    } else if (btn.role === "finish") {
      slotLabel = "ZIELEINLAUF (aktiv)";
    } else if (btn.pending_lane === "starter") {
      slotLabel = "STARTER (Bereitschaft)";
    } else if (btn.pending_lane === "ziel") {
      slotLabel = "ZIELEINLAUF (Bereitschaft)";
    }

    const letter = btn.letter || "?";
    const assigned = btn.role === "starter" || btn.role === "finish" || (btn.role === "bahn" && btn.lane != null);
    const lvl = tasterLevel(btn, assigned);
    if (lvl) div.classList.add("lvl-" + lvl);
    const unassignHtml = assigned
      ? `<button class="btn btn-sm btn-outline-secondary btn-unassign" data-lane="${btn.role === "starter" ? "starter" : btn.role === "finish" ? "ziel" : escapeHtml(String(btn.lane))}">Entfernen</button>`
      : "";
    div.innerHTML = `
      <div class="taster-header">
        <span>Taster ${escapeHtml(letter)}</span>
        ${unassignHtml}
        <span class="taster-badge">${escapeHtml(slotLabel)}</span>
      </div>
      <div class="taster-mac">${escapeHtml(btn.name ? btn.name + " · " + btn.mac : btn.mac)}</div>
      <div class="small mt-1 text-muted">
        ${vitalsHtml(btn)}
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
        apiPost("/api/assign", { mac: btn.mac, lane: laneArg(lane) })
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
    let laneLevel = "";
    if (activeBtn || pendingBtn) {
      let main = activeBtn ? (activeBtn.letter || "?") : (pendingBtn.letter || "?");
      let extra = "";
      if (activeBtn && pendingBtn && pendingBtn.id !== activeBtn.id) {
        extra = ` <span class="text-warning">(Bereitschaft: ${escapeHtml(pendingBtn.letter || "?")})</span>${pendingActionsHtml(b, pendingBtn.mac)}`;
      }
      const shown = activeBtn || pendingBtn;
      laneLevel = tasterLevel(shown, true);
      tasterHtml = `<div class="taster-assigned"><strong>Taster ${escapeHtml(main)}</strong>${extra}<div class="small text-muted">${vitalsHtml(shown)}</div></div>`;
    }

    tr.innerHTML = `
      <td>${b}</td>
      <td>${escapeHtml(name)}</td>
      <td>${escapeHtml(startnr)}</td>
      <td>${escapeHtml(disz)}</td>
      <td><div class="drop-target${laneLevel ? " lvl-" + laneLevel : ""}" data-lane="${b}">${tasterHtml}</div></td>
      <td class="lane-time" data-lane="${b}" data-active="${r ? 1 : 0}">–</td>
      <td class="finish-cell small" data-lane="${b}"></td>
    `;
    const finishCell = tr.querySelector(".finish-cell");
    finishCell.addEventListener("dragover", ev => {
      if (!ev.dataTransfer.types.includes("application/x-finish")) return;
      ev.preventDefault();
      finishCell.classList.add("drop-hover");
    });
    finishCell.addEventListener("dragleave", () => finishCell.classList.remove("drop-hover"));
    finishCell.addEventListener("drop", ev => {
      ev.preventDefault();
      finishCell.classList.remove("drop-hover");
      let data;
      try { data = JSON.parse(ev.dataTransfer.getData("application/x-finish")); } catch (e) { return; }
      if (data && data.runKey) assignFinish(data.runKey, b, data.index);
    });
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

  byId("starterIsFinishQuick").addEventListener("change", async ev => {
    try {
      await apiPost("/api/settings", { starter_is_finish: ev.target.checked });
      await loadSettingsIntoUI();
    } catch (e) {
      alert("Speichern fehlgeschlagen: " + e.message);
      await loadSettingsIntoUI();
    }
  });

  byId("btnRangeTest").addEventListener("click", async () => {
    const on = byId("btnRangeTest").textContent.includes("starten");
    try {
      await apiPost("/api/settings", { range_test_letter: byId("rangeTestLetter").value, range_test_on: on });
    } catch (e) {
      alert("Funktest: " + e.message);
    }
    await loadSettingsIntoUI();
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
        shutdown_grace_s: byId("shutdownGraceInput").value,
        starter_is_finish: byId("starterIsFinishInput").checked,
        low_battery_pct: byId("lowBatteryPctInput").value,
        low_battery_min: byId("lowBatteryMinInput").value
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
  byId("btnClearFinish").addEventListener("click", () => unassignLane("ziel"));
  byId("btnFwDeploy").addEventListener("click", deployFirmware);
  byId("btnPiDeploy").addEventListener("click", deployPi);
  byId("btnPiReload").addEventListener("click", () => refreshPiUpdate().catch(e => alert("Versionen laden fehlgeschlagen: " + e.message)));
  byId("btnFwReload").addEventListener("click", () => refreshFirmware().catch(e => alert("Firmware laden fehlgeschlagen: " + e.message)));
  byId("btnFwCancel").addEventListener("click", async () => {
    await apiPost("/api/firmware/cancel").catch(() => {});
    await refreshFirmware().catch(() => {});
  });
  byId("settings-tab").addEventListener("shown.bs.tab", () => {
    refreshFirmware().catch(() => {});
    refreshPiUpdate().catch(e => {
      const err = byId("piError");
      err.textContent = "Versionen konnten nicht geladen werden: " + e.message;
      err.classList.remove("d-none");
    });
    refreshWifi().catch(() => {});
    refreshAccount().catch(() => {});
  });
  byId("btnWifiSave").addEventListener("click", saveWifi);
  byId("btnWifiForce").addEventListener("click", forceWifi);
  byId("btnAccountSave").addEventListener("click", saveAccount);
  byId("btnLogout").addEventListener("click", logout);
  byId("vitals-tab").addEventListener("shown.bs.tab", () => refreshVitals().catch(() => {}));
  byId("vitalsHours").addEventListener("change", () => refreshVitals().catch(() => {}));
  window.addEventListener("resize", () => { if (vitalsData) drawVitals(); });
  setInterval(() => {
    if (byId("vitals").classList.contains("active")) refreshVitals().catch(() => {});
  }, 10000);
  setInterval(() => {
    if (byId("settings").classList.contains("active")) {
      refreshFirmware().catch(() => {});
      refreshWifi().catch(() => {});
    }
  }, 5000);
  byId("tasterList").addEventListener("click", ev => {
    const b = ev.target.closest(".btn-unassign");
    if (b) unassignLane(b.dataset.lane);
  });

  byId("btnRefreshTaster").addEventListener("click", () => loadButtons().catch(e => alert("Taster laden fehlgeschlagen: " + e.message)));
  byId("btnRefreshStatus").addEventListener("click", () => refreshSystemStatus().catch(e => alert("Status laden fehlgeschlagen: " + e.message)));

  // initial loads
  await refreshSystemStatus().catch(() => {});
  setInterval(() => refreshCluster().catch(() => {}), 10000);
  // Grenzwerte zuerst laden, damit Farben und Balken von Anfang an stimmen
  renderLimitsForm();
  await loadLimits().catch(() => {});
  byId("btnSaveLimits").addEventListener("click", () => saveLimits(false));
  byId("btnResetLimits").addEventListener("click", () => {
    if (window.confirm("Alle Grenzwerte auf die Standardwerte zurücksetzen?")) saveLimits(true);
  });
  refreshAllAlerts();
  setInterval(refreshAllAlerts, 10000);
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
  setInterval(() => { loadRunStatus().catch(() => {}); }, 250);
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
