#!/usr/bin/env bash
# Wird von keepalived bei jedem Rollenwechsel aufgerufen: $1=GROUP $2=Name $3=Zustand
source /etc/stoppuhr-zwei-pi.env

case "$3" in
  MASTER)
    # Kopie zum Hauptbestand machen und die Stoppuhr starten
    redis-cli replicaof no one >/dev/null
    systemctl start stoppuhr
    ;;
  BACKUP|FAULT)
    # Arbeit abgeben, Daten vom neuen Hauptpi als Kopie halten
    systemctl stop stoppuhr
    redis-cli replicaof "$PEER_IP" 6379 >/dev/null
    ;;
esac
