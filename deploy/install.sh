#!/usr/bin/env bash
# Installiert die Stoppuhr ohne Docker auf einem Raspberry Pi (Raspberry Pi OS / Debian).
# Aufruf im Projektordner:  bash deploy/install.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un)"

echo "== Pakete installieren (Python, Redis, chrony) =="
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip redis-server chrony

echo "== Redis dauerhaft speichern =="
# Wie im Docker-Aufbau: alle 10 s sichern, wenn sich mindestens ein Wert geaendert hat
sudo sed -i 's/^save .*/# &/' /etc/redis/redis.conf
if ! grep -q '^save 10 1' /etc/redis/redis.conf; then
  echo 'save 10 1' | sudo tee -a /etc/redis/redis.conf >/dev/null
fi
sudo systemctl enable --now redis-server
sudo systemctl restart redis-server

echo "== Python-Umgebung anlegen =="
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install --upgrade pip
"$DIR/.venv/bin/pip" install -r "$DIR/deploy/requirements.txt"
mkdir -p "$DIR/results"

echo "== Dienst einrichten =="
sed -e "s|__USER__|$USER_NAME|g" -e "s|__DIR__|$DIR|g" "$DIR/deploy/stoppuhr.service" \
  | sudo tee /etc/systemd/system/stoppuhr.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now stoppuhr
sudo systemctl restart stoppuhr

echo "== Knotendienst (Systemstatus und WLAN-Umstellung) =="
sed -e "s|__DIR__|$DIR|g" "$DIR/deploy/zwei-pi/stoppuhr-knoten.service" \
  | sudo tee /etc/systemd/system/stoppuhr-knoten.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable stoppuhr-knoten
sudo systemctl restart stoppuhr-knoten

sleep 3
systemctl --no-pager --lines=5 status stoppuhr || true
echo
echo "Fertig. Oberflaeche: http://$(hostname -I | awk '{print $1}'):1999"
echo "Hinweis: Fuer die Taster in /etc/chrony/chrony.conf 'allow <Taster-Netz>' ergaenzen (siehe README)."
