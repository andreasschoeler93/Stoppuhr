(function () {
    const statusEl = document.getElementById('status');
    const gridEl = document.getElementById('grid');
    const reloadBtn = document.getElementById('reloadBtn');

    function setStatus(text, kind = 'info') {
        statusEl.textContent = text;
        statusEl.dataset.kind = kind;
    }

    async function loadMapping() {
        setStatus('Lade Mapping…', 'info');
        gridEl.innerHTML = '';

        let data;
        try {
            const resp = await fetch('/api/mapping', {headers: {'Accept': 'application/json'}});
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            data = await resp.json();
        } catch (e) {
            setStatus(`Fehler beim Laden von /api/mapping: ${String(e)}`, 'error');
            return;
        }

        const mapping = data && data.mapping ? data.mapping : {};
        const lanes = Object.keys(mapping)
            .map(k => String(k))
            .filter(k => /^\d+$/.test(k))
            .sort((a, b) => Number(a) - Number(b));

        const buttons = [];

        for (const lane of lanes) {
            const taster = mapping[lane]; // object or null
            if (!taster || !taster.mac) continue;

            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'lane-btn';
            btn.textContent = lane; // only show lane number
            btn.dataset.mac = taster.mac;

            btn.addEventListener('click', async () => {
                await emitPress(btn.dataset.mac, lane, btn);
            });

            buttons.push(btn);
        }

        if (buttons.length === 0) {
            setStatus('Keine gemappten Tasters gefunden (Mapping ist leer).', 'warn');
            return;
        }

        for (const b of buttons) gridEl.appendChild(b);
        setStatus(`Bereit. Buttons: ${buttons.length}`, 'ok');
    }

    async function emitPress(mac, lane, btnEl) {
        if (!mac) return;

        btnEl.disabled = true;
        setStatus(`Sende Trigger: Bahn ${lane}…`, 'info');

        try {
            const resp = await fetch('/api/triggers', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
                body: JSON.stringify({mac})
            });

            const payload = await resp.json().catch(() => ({}));

            if (!resp.ok || payload.ok === false) {
                const err = payload && payload.error ? payload.error : `HTTP ${resp.status}`;
                throw new Error(err);
            }

            setStatus(`OK: Bahn ${lane} (${new Date().toLocaleTimeString()})`, 'ok');
        } catch (e) {
            setStatus(`Fehler beim Senden: ${String(e)}`, 'error');
        } finally {
            btnEl.disabled = false;
        }
    }

    reloadBtn.addEventListener('click', loadMapping);
    loadMapping();
})();