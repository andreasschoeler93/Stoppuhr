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

AP_SSID="${AP_SSID:-}"
AP_PSK="${AP_PSK:-}"

if ! { ip -4 addr show br0 2>/dev/null | grep -q "$OWN_IP" && nmcli -t -f NAME con show | grep -qx vxlan0; }; then
  if [ -z "$AP_SSID" ] || [ -z "$AP_PSK" ]; then
    echo "br0 mit $OWN_IP fehlt. Entweder Bridge selbst einrichten (README) oder neu starten mit:"
    echo "  AP_SSID=NAME AP_PSK=PASSWORT bash $0 $ROLLE"
    exit 1
  fi
  if [ "${#AP_PSK}" -lt 8 ]; then echo "AP_PSK braucht mindestens 8 Zeichen."; exit 1; fi
  # Laeuft die SSH-Sitzung ueber das WLAN, wuerde sie beim Umbau abreissen
  SSH_DEV=""
  if [ -n "${SSH_CONNECTION:-}" ]; then
    SSH_IP="$(echo "$SSH_CONNECTION" | awk '{print $3}')"
    SSH_DEV="$(ip -o -4 addr show | awk -v ip="$SSH_IP" '$4 ~ "^"ip"/" {print $2}')"
  fi
  if [ "$SSH_DEV" = "wlan0" ] && [ "${FORCE:-0}" != "1" ]; then
    echo "Du bist per WLAN verbunden; der Umbau wuerde die Sitzung beenden."
    echo "Bitte per Kabel/Monitor ausfuehren (oder FORCE=1 setzen)."
    exit 1
  fi
  echo "== Netz: eth0 per DHCP am Router, Taster-Netz br0 ($OWN_IP) nur WLAN + Tunnel =="
  # Altlast aus frueheren Staenden: eth0 war direkt in der Bridge
  sudo nmcli con delete br0-eth0 >/dev/null 2>&1 || true
  if ! nmcli -t -f TYPE con show | grep -q '^802-3-ethernet$'; then
    sudo nmcli con add type ethernet ifname eth0 con-name lan ipv4.method auto
  fi
  LAN="$(nmcli -t -f NAME,TYPE con show | awk -F: '$2=="802-3-ethernet"{print $1; exit}')"
  sudo nmcli con up "$LAN" || true
  sudo nmcli con delete br0 vxlan0 ap >/dev/null 2>&1 || true
  sudo nmcli con add type bridge ifname br0 con-name br0 ipv4.method manual ipv4.addresses "$OWN_IP/24" bridge.stp no
  # Tunnel zwischen den beiden Pis ueber das Router-Netz: verbindet nur die beiden Taster-WLANs
  # (Standard: Multicast-Gruppe; VXLAN_REMOTE=<IP des anderen Pi> nutzt stattdessen Unicast)
  sudo nmcli con add type vxlan ifname vxlan0 con-name vxlan0 vxlan.id 50 \
    vxlan.remote "${VXLAN_REMOTE:-239.50.50.50}" vxlan.parent eth0 vxlan.destination-port 4789 \
    connection.master br0 connection.slave-type bridge
  sudo nmcli con add type wifi ifname wlan0 con-name ap ssid "$AP_SSID" mode ap wifi.hidden yes \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$AP_PSK" connection.master br0 connection.slave-type bridge
  if ! { sudo nmcli con up br0 && sudo nmcli con up vxlan0 && sudo nmcli con up ap; }; then
    sleep 3
  fi
  OK=0
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ip -4 addr show br0 2>/dev/null | grep -q "$OWN_IP"; then OK=1; break; fi
    sleep 1
  done
  if [ "$OK" != "1" ]; then
    echo "Bridge kam nicht hoch. Taster-Netz wird entfernt, eth0 bleibt am Router."
    sudo nmcli con delete ap vxlan0 br0 >/dev/null 2>&1 || true
    exit 1
  fi
fi

echo "== Name im Router-Netz: stoppuhr-$ROLLE.local =="
sudo apt-get install -y avahi-daemon
sudo hostnamectl set-hostname "stoppuhr-$ROLLE"
sudo sed -i '/^127\.0\.1\.1 /d' /etc/hosts
echo "127.0.1.1 stoppuhr-$ROLLE" | sudo tee -a /etc/hosts >/dev/null
sudo systemctl enable --now avahi-daemon
sudo systemctl restart avahi-daemon

echo "== Pakete =="
sudo apt-get install -y keepalived redis-tools

echo "== Redis: im LAN erreichbar, damit die Kopie funktioniert =="
if ! ip -4 addr show br0 2>/dev/null | grep -q "$OWN_IP"; then
  echo "Hinweis: br0 mit $OWN_IP fehlt noch (Bridge zuerst einrichten, siehe README). Redis startet trotzdem."
fi
# "-" vor der Adresse: Redis startet auch, wenn die Adresse noch nicht existiert
sudo sed -i 's/^bind .*/bind 127.0.0.1 -'"$OWN_IP"'/' /etc/redis/redis.conf
sudo sed -i 's/^protected-mode .*/protected-mode no/' /etc/redis/redis.conf
if [ "$ROLLE" = "bad" ]; then
  # Bad-Pi startet als Kopie des Koffer-Pi
  sudo grep -q '^replicaof ' /etc/redis/redis.conf || echo "replicaof $KOFFER_IP 6379" | sudo tee -a /etc/redis/redis.conf >/dev/null
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
# Altlast aus dem Einzelbetrieb: bindet an wlan0, das jetzt in der Bridge steckt
if [ -f /etc/dnsmasq.d/taster.conf ]; then
  sudo mkdir -p /root/dnsmasq-alt
  sudo mv /etc/dnsmasq.d/taster.conf /root/dnsmasq-alt/
fiif [ "$ROLLE" = "koffer" ]; then DHCP_VON=100; DHCP_BIS=149; else DHCP_VON=150; DHCP_BIS=199; fi
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
