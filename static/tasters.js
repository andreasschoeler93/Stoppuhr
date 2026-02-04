(async function () {
    const stateBox = document.getElementById('stateBox');
    const grid = document.getElementById('grid');
    const reloadBtn = document.getElementById('reloadBtn');

    const laneMap = document.getElementById('laneMap');
    const triggerState = document.getElementById('triggerState');

    const runInput = document.getElementById('runInput');
    const setRunBtn = document.getElementById('setRunBtn');
    const runState = document.getElementById('runState');

    function escapeHtml(s) {
        return String(s ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#039;');
    }

    function setState(text) {
        stateBox.textContent = text;
        stateBox.style.display = 'block';
    }

    function clearGrid() {
        grid.innerHTML = '';
    }

    function showTriggerState(text, isError = false) {
        triggerState.style.display = 'block';
        triggerState.style.borderColor = isError ? 'rgba(220, 0, 0, 0.25)' : 'rgba(0, 0, 0, .12)';
        triggerState.style.color = isError ? 'rgba(160, 0, 0, 0.9)' : 'inherit';
        triggerState.textContent = text;
    }

    function hideTriggerState() {
        triggerState.style.display = 'none';
        triggerState.textContent = '';
    }

    function card({title, detail, badgeText, badgeVariant}) {
        const badgeClass = badgeVariant === 'active' ? 'badge active' : 'badge inactive';
        return `
      <div class="card">
        <div class="row">
          <div class="card-title">${escapeHtml(title)}</div>
          ${badgeText ? `<div class="${badgeClass}">${escapeHtml(badgeText)}</div>` : ''}
        </div>
        ${detail ? `<div class="detail">${escapeHtml(detail)}</div>` : ''}
      </div>
    `;
    }

    function buildViewModels(mappingResponse) {
        const byMac = new Map();

        const upsert = (t, badgeText, badgeVariant) => {
            if (!t || !t.mac) return;
            const existing = byMac.get(t.mac);
            if (existing && existing.badgeVariant === 'active') return;

            byMac.set(t.mac, {
                title: `Taster ${t.name ?? ''}`.trim(),
                detail: t.mac,
                badgeText,
                badgeVariant,
            });
        };

        for (const [lane, t] of Object.entries(mappingResponse.mapping || {})) {
            if (t) upsert(t, `BAHN ${lane}`, 'active');
        }

        if (mappingResponse.starter) {
            upsert(mappingResponse.starter, 'STARTER', 'active');
        }

        for (const t of (mappingResponse.unmapped_taster || [])) {
            upsert(t, 'NICHT ZUGEWIESEN', 'inactive');
        }

        return Array.from(byMac.values()).sort((a, b) =>
            a.title.localeCompare(b.title, undefined, {numeric: true})
        );
    }

    function extractLaneNumbers(mappingObj) {
        return Object.keys(mappingObj || {})
            .map(k => Number(k))
            .filter(n => Number.isFinite(n) && n > 0)
            .sort((a, b) => a - b);
    }

    function renderLaneMap(mappingResponse) {
        laneMap.innerHTML = '';

        const mapping = mappingResponse?.mapping || {};
        const lanes = extractLaneNumbers(mapping);

        const items = [];

        // Lanes 1..N (based on mapping keys)
        for (const laneNum of lanes) {
            const laneKey = String(laneNum);
            const t = mapping[laneKey];
            items.push({
                label: `Bahn ${laneKey}`,
                mac: t?.mac || null,
                tasterName: t?.name || null,
            });
        }

        // Starter
        items.push({
            label: 'Starter',
            mac: mappingResponse?.starter?.mac || null,
            tasterName: mappingResponse?.starter?.name || null,
        });

        for (const it of items) {
            const btn = document.createElement('button');
            btn.className = 'lane-btn';
            btn.type = 'button';
            btn.disabled = !it.mac;

            btn.innerHTML = `
        <div class="lane-name">${escapeHtml(it.label)}</div>
        <div class="lane-detail">
          ${it.mac
                ? `Taster: <b>${escapeHtml(it.tasterName ?? '–')}</b><br><code>${escapeHtml(it.mac)}</code>`
                : 'Kein Taster zugewiesen'}
        </div>
      `;

            btn.addEventListener('click', async () => {
                if (!it.mac) return;
                await sendTrigger(it.mac, it.label);
            });

            laneMap.appendChild(btn);
        }
    }

    async function setCurrentRun(runValue) {
        const v = String(runValue ?? '').trim();
        if (!v) {
            runState.textContent = 'Lauf: –';
            showTriggerState('Bitte einen Lauf eingeben (z.B. 1).', true);
            return;
        }

        hideTriggerState();
        setRunBtn.disabled = true;

        try {
            const resp = await fetch('/api/runs', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
                body: JSON.stringify({current_run: v}),
            });

            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || data.ok === false) {
                throw new Error(data.error || `HTTP ${resp.status}`);
            }

            runState.textContent = `Lauf: ${v}`;
            showTriggerState(`Aktueller Lauf gesetzt: ${v}`);
        } catch (e) {
            showTriggerState(`Fehler beim Setzen des Laufs: ${e?.message || e}`, true);
        } finally {
            setRunBtn.disabled = false;
        }
    }

    async function sendTrigger(mac, label) {
        hideTriggerState();

        // Disable all lane buttons briefly to prevent double-click storms
        const buttons = Array.from(laneMap.querySelectorAll('button.lane-btn'));
        buttons.forEach(b => (b.disabled = true));

        try {
            const resp = await fetch('/api/triggers', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
                body: JSON.stringify({mac}),
            });

            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || data.ok === false) {
                throw new Error(data.error || `HTTP ${resp.status}`);
            }

            const press = data.press || {};
            showTriggerState(
                `Trigger OK: ${label} · lane=${press.lane ?? '–'} · run=${press.run ?? '–'} · mac=${press.mac ?? '–'} · ts=${press.ts ?? '–'}`
            );
        } catch (e) {
            showTriggerState(`Trigger FEHLER (${label}): ${e?.message || e}`, true);
        } finally {
            // Re-enable only those that have a MAC
            // (We rebuild this properly on next reload; for now just re-enable all and let "disabled" state be corrected by render)
            buttons.forEach(b => (b.disabled = false));
        }
    }

    async function load() {
        try {
            reloadBtn.disabled = true;
            clearGrid();
            laneMap.innerHTML = '';
            setState('Lade…');
            hideTriggerState();

            const resp = await fetch('/api/mapping', {headers: {'Accept': 'application/json'}});
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            const data = await resp.json();

            // Lane map (simulation)
            renderLaneMap(data);

            // Cards (overview)
            const vms = buildViewModels(data);

            if (!vms.length) {
                setState('Keine Taster gefunden.');
                return;
            }

            stateBox.style.display = 'none';
            grid.innerHTML = vms.map(card).join('');
        } catch (e) {
            setState(`Fehler beim Laden: ${e?.message || e}`);
        } finally {
            reloadBtn.disabled = false;
        }
    }

    reloadBtn.addEventListener('click', load);

    setRunBtn.addEventListener('click', async () => {
        await setCurrentRun(runInput.value);
    });

    runInput.addEventListener('keydown', async (ev) => {
        if (ev.key === 'Enter') {
            await setCurrentRun(runInput.value);
        }
    });

    await load();
})();