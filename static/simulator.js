// Simulator JS: rendert die Display-Ansichten (Bahn 1-5 + Start) und sendet Taster-Trigger
(function () {
    // config
    const letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']; // 10 simulated tasters
    let isRunning = false;
    let startTs = Date.now();
    let lastStopMs = 4056;
    let currentLauf = 1;
    let swimmerName = "Max Mustermann";
    let discipline = "50m Freistil";

    // Create taster buttons
    const btnContainer = document.getElementById('taster-buttons');
    letters.forEach((l, idx) => {
        const b = document.createElement('button');
        b.className = 'taster-btn';
        b.textContent = l;
        b.dataset.taster = l;
        b.addEventListener('click', async () => {
            b.classList.add('active');
            setTimeout(() => b.classList.remove('active'), 120);
            await sendTrigger(l);
        });
        btnContainer.appendChild(b);
    });

    // keyboard mapping
    window.addEventListener('keydown', (e) => {
        const k = e.key;
        let idx = null;
        if (k >= '1' && k <= '9') idx = parseInt(k, 10) - 1;
        else if (k === '0') idx = 9;
        else {
            const up = k.toUpperCase();
            idx = letters.indexOf(up);
        }
        if (idx !== null && idx >= 0 && idx < letters.length) {
            const l = letters[idx];
            const btn = document.querySelector(`.taster-btn[data-taster="${l}"]`);
            if (btn) {
                btn.classList.add('active');
                setTimeout(() => btn.classList.remove('active'), 120);
            }
            sendTrigger(l);
        }
    });

    // controls
    document.getElementById('toggle-run').addEventListener('click', () => {
        isRunning = !isRunning;
        if (isRunning) {
            startTs = Date.now();
        } else {
            lastStopMs = Date.now() - startTs;
        }
        renderAllDisplays();
    });
    document.getElementById('reset-time').addEventListener('click', () => {
        startTs = Date.now();
        lastStopMs = 0;
        renderAllDisplays();
    });

    // send trigger to server (if endpoint present)
    async function sendTrigger(taster) {
        const payload = {
            taster,
            ts: Date.now(),
            stopwatch_ms: (isRunning ? (Date.now() - startTs) : lastStopMs),
            run_id: currentLauf
        };
        try {
            await fetch('/api/triggers', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            console.log('trigger sent', payload);
        } catch (e) {
            console.warn('POST /api/triggers failed (server may not provide endpoint).', e);
        }
    }

    // Build display HTML for each device-display element
    function renderAllDisplays() {
        const elems = document.querySelectorAll('.device-display');
        elems.forEach(el => {
            const mode = el.dataset.mode || 'bahn';
            if (mode === 'bahn') {
                const bahn = +el.dataset.bahn || 1;
                renderBahn(el, bahn);
            } else if (mode === 'start') {
                renderStart(el);
            }
        });
    }

    // helpers
    function fmtTimeMs(ms) {
        const totalSec = Math.floor(ms / 1000);
        const m = Math.floor(totalSec / 60);
        const s = totalSec % 60;
        const milli = ms % 1000;
        return `${pad(m, 2)}:${pad(s, 2)},${pad(milli, 3)}`;
    }

    function pad(n, len) {
        let s = String(n);
        while (s.length < len) s = '0' + s;
        return s;
    }

    function renderTopBar(el, leftText, rightText, accent) {
        let top = el.querySelector('.topbar');
        if (!top) {
            top = document.createElement('div');
            top.className = 'topbar';
            el.appendChild(top);
        }
        top.innerHTML = `<div class="left">${leftText}</div><div class="right">${rightText}</div>`;
        // color handled by parent background
    }

    function renderMaindisplay(el, mainTime, name, disciplineText) {
        let md = el.querySelector('.maindisplay');
        if (!md) {
            md = document.createElement('div');
            md.className = 'maindisplay';
            el.appendChild(md);
        }
        md.innerHTML = `<div class="time">${mainTime}</div><div class="name">${name}</div><div class="discipline">${disciplineText}</div>`;
    }

    function renderSeparator(el) {
        let s = el.querySelector('.separator');
        if (!s) {
            s = document.createElement('div');
            s.className = 'separator';
            el.appendChild(s);
        }
    }

    function renderLastBlock(el, label, lasttime, meta) {
        let lb = el.querySelector('.lastblock');
        if (!lb) {
            lb = document.createElement('div');
            lb.className = 'lastblock';
            el.appendChild(lb);
        }
        lb.innerHTML = `<div class="label">${label}</div><div class="lasttime">${lasttime}</div><div class="meta">${meta}</div>`;
        // position adjustments to emulate "raise one line"
        lb.style.top = '150px'; // slightly raised under line
    }

    function renderBottomBar(el, humidity, temp, battery, letter, rssi) {
        let bot = el.querySelector('.bottombar');
        if (!bot) {
            bot = document.createElement('div');
            bot.className = 'bottombar';
            el.appendChild(bot);
        }
        // Wifi bars
        const bars = wifiHtml(rssi);
        bot.innerHTML = `<div class="vitals">H ${Math.round(humidity)}%  T ${temp.toFixed(1)}°C  ${battery}%  ${letter}</div><div class="wifi">${bars}</div>`;
        // set vitals color (in CSS)
    }

    function wifiHtml(rssi) {
        // decide how many bars: emulate firmware thresholds
        let bars = 1;
        if (rssi >= -60) bars = 4;
        else if (rssi >= -70) bars = 3;
        else if (rssi >= -80) bars = 2;
        else bars = 1;
        let html = '';
        for (let i = 0; i < 4; i++) {
            const h = 6 + i * 6;
            html += `<div class="bar ${i < bars ? 'on' : ''}" style="height:${h}px"></div>`;
        }
        return html;
    }

    // specific renderers
    function renderBahn(el, bahn) {
        // background mode styles
        el.classList.remove('mode-red', 'mode-blue', 'mode-green');
        el.classList.add('mode-green');
        const topLeft = `Bahn ${bahn}`;
        const topRight = `Lauf ${currentLauf}`;
        renderTopBar(el, topLeft, topRight, 'green');

        const mainTime = isRunning ? fmtTimeMs(Date.now() - startTs) : fmtTimeMs(lastStopMs);
        renderMaindisplay(el, mainTime, swimmerName, discipline);
        renderSeparator(el);
        renderLastBlock(el, 'Letzte Zeit', fmtTimeMs(lastStopMs), `${swimmerName} / Lauf ${currentLauf}`);
        renderBottomBar(el, 47.0, 23.5, 87, 'B', -63);
    }

    function renderStart(el) {
        el.classList.remove('mode-red', 'mode-blue', 'mode-green');
        el.classList.add('mode-red');
        const topLeft = 'Start';
        const topRight = `Lauf ${currentLauf}`;
        renderTopBar(el, topLeft, topRight, 'red');

        const mainTime = isRunning ? fmtTimeMs(Date.now() - startTs) : '00:00,000';
        renderMaindisplay(el, mainTime, swimmerName, discipline);
        renderSeparator(el);
        renderLastBlock(el, 'Massenstart', '--:--,--', '');
        renderBottomBar(el, 47.0, 23.5, 87, 'B', -63);
    }

    // initial render + update ticker
    renderAllDisplays();
    setInterval(() => {
        // update time display smoothly when running
        renderAllDisplays();
    }, 200);

})();