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
NAME="${NAME:-stoppuhr}"

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
printf 'VIP=%s\nPEER_IP=%s\nROLLE=%s\n' "$VIP" "$PEER_IP" "$ROLLE" | sudo tee /etc/stoppuhr-zwei-pi.env >/dev/null
# Die Stoppuhr kennt damit Partner und VIP; der Knotenstatus-Dienst laeuft immer
sudo mkdir -p /etc/systemd/system/stoppuhr.service.d
printf '[Service]\nEnvironmentFile=/etc/stoppuhr-zwei-pi.env\n' | sudo tee /etc/systemd/system/stoppuhr.service.d/zwei-pi.conf >/dev/null
DIR="$(cd "$HIER/../.." && pwd)"
sed -e "s|__DIR__|$DIR|g" "$HIER/stoppuhr-knoten.service" | sudo tee /etc/systemd/system/stoppuhr-knoten.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now stoppuhr-knoten
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

echo "== Namen und DHCP: http://$NAME:1999 fuehrt immer zum arbeitenden Pi =="
sudo apt-get install -y dnsmasq
if [ "$ROLLE" = "koffer" ]; then DHCP_VON=100; DHCP_BIS=149; else DHCP_VON=150; DHCP_BIS=199; fi
sudo tee /etc/dnsmasq.d/stoppuhr.conf >/dev/null <<EOF
interface=br0
bind-interfaces
dhcp-authoritative
dhcp-range=192.168.50.$DHCP_VON,192.168.50.$DHCP_BIS,12h
# Geraete nutzen die gemeinsame Adresse als DNS-Server; dort antwortet immer der arbeitende Pi
dhcp-option=option:dns-server,$VIP
# Hostname des Pi nicht ausliefern, nur den gemeinsamen Namen
no-hosts
address=/$NAME/$VIP
EOF
sudo systemctl enable dnsmasq
sudo systemctl restart dnsmasq

echo "== Dienste: keepalived entscheidet, wer die Stoppuhr startet =="
sudo systemctl disable --now stoppuhr
sudo systemctl enable --now keepalived
echo "Fertig. Pruefen: ip -4 addr show br0  (die Adresse $VIP liegt nur auf dem Pi, der arbeitet)"
echo "Oberflaeche: http://$NAME:1999 (oder http://$VIP:1999)"
