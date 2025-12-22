# Stoppuhr v0.4.1 (Rebuild)

Diese ZIP ist eine **Neu-Erstellung** der v0.4.1 als stabile Basis (kein Auto-Refresh Startkarten, Taster noch Demo/Stub).

## Installation auf dem Pi (empfohlen)

```bash
sudo systemctl stop stoppuhr || true
cd ~
rm -rf stoppuhr
unzip stoppuhr_v0_4_1_rebuild.zip
mv stoppuhr_v0_4_1 stoppuhr
cd stoppuhr

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Teststart:
```bash
.venv/bin/python app.py
```
Browser: `http://<pi-ip>:8000`

## Systemd Service

`/etc/systemd/system/stoppuhr.service`:
```
[Unit]
Description=Stoppuhr Webserver
After=network.target

[Service]
User=dlrg
WorkingDirectory=/home/dlrg/stoppuhr
ExecStart=/home/dlrg/stoppuhr/.venv/bin/python /home/dlrg/stoppuhr/app.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Aktivieren:
```bash
sudo systemctl daemon-reload
sudo systemctl enable stoppuhr
sudo systemctl restart stoppuhr
sudo systemctl status stoppuhr --no-pager
```

## GitHub (Empfehlung)

Wenn du willst, gebe ich dir die **konkreten Befehle**:
- Repo initialisieren
- ersten Commit
- Tag v0.4.1 setzen
- remote zu GitHub verbinden
