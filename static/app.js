async function apiGet(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error("HTTP " + r.status);
  return await r.json();
}
async function apiPost(path, body) {
  const r = await fetch(path, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body||{})});
  if (!r.ok) throw new Error("HTTP " + r.status);
  return await r.json();
}

async function loadSettings() {
  const s = await apiGet("/api/settings");
  document.getElementById("baseUrl").value = s.startcards_base_url || "";
  document.getElementById("suffix").value = s.startcards_suffix || "/export/CSV/Startkarten.csv";
}

async function saveSettings() {
  const baseUrl = document.getElementById("baseUrl").value.trim();
  const suffix = document.getElementById("suffix").value.trim();
  await apiPost("/api/settings", {startcards_base_url: baseUrl, startcards_suffix: suffix});
}

async function reloadStartcards() {
  const r = await apiPost("/api/startcards/reload", {});
  document.getElementById("startcardsInfo").textContent = JSON.stringify(r.startcards || {}, null, 2);
}

async function loadTasters() {
  const r = await apiGet("/api/taster-list");
  const list = document.getElementById("tasterList");
  list.innerHTML = "";
  (r.tasters || []).forEach(t => {
    const div = document.createElement("div");
    div.className = "border rounded p-2 mb-2 bg-white";
    div.innerHTML = `<div><strong>Taster ${t.letter || "?"}</strong> <span class="text-muted">${t.mac || ""}</span></div>
                     <div class="text-muted">Rolle: ${t.role} / Bahn: ${t.lane ?? "-"}</div>
                     <div class="text-muted">Akku: ${t.last_battery_percent ?? "-"}% | RSSI: ${t.last_rssi_dbm ?? "-"} dBm</div>`;
    list.appendChild(div);
  });
}

async function loadStatus() {
  const sys = await apiGet("/api/system-status");
  const net = await apiGet("/api/network-status");
  document.getElementById("statusBox").textContent = JSON.stringify({system: sys, network: net}, null, 2);
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    await loadSettings();
    document.getElementById("btnSave").addEventListener("click", async () => {
      try { await saveSettings(); await reloadStartcards(); } catch(e){ alert(e.message); }
    });
    document.getElementById("btnReload").addEventListener("click", async () => {
      try { await reloadStartcards(); } catch(e){ alert(e.message); }
    });
    document.getElementById("btnTas").addEventListener("click", async () => {
      try { await loadTasters(); } catch(e){ alert(e.message); }
    });
    document.getElementById("btnStatus").addEventListener("click", async () => {
      try { await loadStatus(); } catch(e){ alert(e.message); }
    });

    await reloadStartcards();
    await loadTasters();
    await loadStatus();
  } catch (e) {
    console.error(e);
    alert("Init-Fehler: " + e.message);
  }
});
