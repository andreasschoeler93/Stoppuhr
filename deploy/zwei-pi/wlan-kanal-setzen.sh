#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo ausfuehren: sudo bash $0 [Kanal]"
  exit 1
fi

ENV_FILE="/etc/stoppuhr-zwei-pi.env"
if [ ! -r "$ENV_FILE" ]; then
  echo "$ENV_FILE fehlt; zuerst den Zwei-Pi-Betrieb einrichten."
  exit 1
fi
source "$ENV_FILE"

case "${ROLLE:-}" in
  koffer) DEFAULT_CHANNEL=1 ;;
  bad)    DEFAULT_CHANNEL=11 ;;
  *) echo "Unbekannte oder fehlende Pi-Rolle in $ENV_FILE."; exit 1 ;;
esac

CHANNEL="${1:-${AP_CHANNEL:-$DEFAULT_CHANNEL}}"
case "$CHANNEL" in
  1|6|11) ;;
  *) echo "Kanal muss 1, 6 oder 11 sein."; exit 1 ;;
esac

if ! nmcli -t -f NAME connection show | grep -Fxq ap; then
  echo "NetworkManager-Verbindung 'ap' nicht gefunden."
  exit 1
fi

nmcli connection modify ap 802-11-wireless.band bg 802-11-wireless.channel "$CHANNEL"
nmcli connection down ap
nmcli connection up ap
echo "Zugangspunkt auf 2,4 GHz, Kanal $CHANNEL eingestellt."
