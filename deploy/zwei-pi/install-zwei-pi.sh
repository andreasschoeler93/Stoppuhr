#!/usr/bin/env bash
# Richtet Redis-Kopie, Ausfallübernahme (keepalived) und Zeitabgleich fuer den Zwei-Pi-Betrieb ein.
# Voraussetzung: deploy/install.sh lief bereits auf diesem Pi.
# Aufruf:  bash deploy/zwei-pi/install-zwei-pi.sh koffer|bad
set -euo pipefail

ROLLE="${1:-}"
HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VIP="${VIP:-192.168.50.10}"
KOFFER_IP="${KOFFER_IP:-192.168.50.11}"
BAD_IP="${BAD_IP:-192.168.50.12}"

case "$ROLLE" in
  koffer) OWN_IP="$KOFFER_IP"; PEER_IP="$BAD_IP";    PRIO=150 ;;
  bad)    OWN_IP="$BAD_IP";    PEER_IP="$KOFFER_IP"; PRIO=100 ;;
  *) echo "Aufruf: $0 koffer|bad"; exit 1 ;;
esac

echo "== Pakete =="
sudo apt-get install -y keepalived redis-tools

echo "== Redis: im LAN erreichbar, damit die Kopie funktioniert =="
sudo sed -i 's/^bind .*/bind 127.0.0.1 '"$OWN_IP"'/' /etc/redis/redis.conf
sudo sed -i 's/^protected-mode .*/protected-mode no/' /etc/redis/redis.conf
if [ "$ROLLE" = "bad" ]; then
  # Bad-Pi startet als Kopie des Koffer-Pi
  grep -q '^replicaof ' /etc/redis/redis.conf || echo "replicaof $KOFFER_IP 6379" | sudo tee -a /etc/redis/redis.conf >/dev/null
fi
sudo systemctl restart redis-server

echo "== Umgebung und Skripte =="
printf 'VIP=%s\nPEER_IP=%s\n' "$VIP" "$PEER_IP" | sudo tee /etc/stoppuhr-zwei-pi.env >/dev/null
sudo install -m 755 "$HIER/stoppuhr-pruefen.sh" /usr/local/bin/stoppuhr-pruefen.sh
sudo install -m 755 "$HIER/stoppuhr-rolle.sh" /usr/local/bin/stoppuhr-rolle.sh
sed -e "s|__PRIORITY__|$PRIO|" -e "s|__OWN_IP__|$OWN_IP|" -e "s|__PEER_IP__|$PEER_IP|" -e "s|__VIP__|$VIP|" \
  "$HIER/keepalived.conf" | sudo tee /etc/keepalived/keepalived.conf >/dev/null

echo "== Zeit: Taster holen die Zeit von der gemeinsamen Adresse $VIP =="
sudo tee /etc/chrony/conf.d/stoppuhr-zwei-pi.conf >/dev/null <<EOF
allow 192.168.50.0/24
local stratum 10
EOF
if [ "$ROLLE" = "bad" ]; then
  echo "server $KOFFER_IP iburst prefer" | sudo tee -a /etc/chrony/conf.d/stoppuhr-zwei-pi.conf >/dev/null
fi
sudo systemctl restart chrony

echo "== Dienste: keepalived entscheidet, wer die Stoppuhr startet =="
sudo systemctl disable --now stoppuhr
sudo systemctl enable --now keepalived
echo "Fertig. Pruefen: ip -4 addr show br0  (die Adresse $VIP liegt nur auf dem Pi, der arbeitet)"
