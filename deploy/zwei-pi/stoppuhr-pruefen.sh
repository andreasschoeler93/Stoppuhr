#!/usr/bin/env bash
# Wird von keepalived regelmaessig aufgerufen (vrrp_script).
# Exit 0 = dieser Pi darf die Arbeit uebernehmen, Exit 1 = Daten noch nicht aktuell.
# Ein Pi, dessen Partner gerade arbeitet, wird erst "bereit", wenn seine Redis-Kopie
# vollstaendig synchron ist. So geht nach einem Neustart nichts verloren.
source /etc/stoppuhr-zwei-pi.env

info() { timeout 2 redis-cli "$@" info replication 2>/dev/null | tr -d '\r'; }  # Zeitlimit: ein ausgefallener Partner darf das Skript nicht blockieren
peer_role=$(info -h "$PEER_IP" | awk -F: '/^role:/{print $2}')
my_role=$(info | awk -F: '/^role:/{print $2}')
[ -z "$my_role" ] && exit 1   # eigenes Redis laeuft nicht

if [ "$peer_role" = "master" ] && [ "$my_role" = "master" ] && ! ip -4 addr show | grep -q " ${VIP}/"; then
  # Partner arbeitet, wir haben nur alte Daten: erst von ihm abgleichen
  redis-cli replicaof "$PEER_IP" 6379 >/dev/null
  exit 1
fi

if [ "$my_role" = "slave" ] && [ -n "$peer_role" ]; then
  link=$(info | awk -F: '/^master_link_status:/{print $2}')
  [ "$link" = "up" ] && exit 0
  exit 1
fi
# Master ohne Partner-Konflikt, oder Partner ausgefallen: die eigene Kopie ist die beste vorhandene
exit 0
