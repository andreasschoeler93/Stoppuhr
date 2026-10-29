#!/usr/bin/env bash
# Wird von keepalived bei jedem Rollenwechsel aufgerufen: $1=GROUP $2=Name $3=Zustand
source /etc/stoppuhr-zwei-pi.env

# Zeitpunkt des Wechsels merken (wird in der Weboberflaeche angezeigt)
echo "$(date +%s) $3" > /var/lib/stoppuhr-rollenwechsel

case "$3" in
  MASTER)
    # Kopie zum Hauptbestand machen und die Stoppuhr starten
    redis-cli replicaof no one >/dev/null
    systemctl start stoppuhr
    ;;
  BACKUP|FAULT)
    # Arbeit abgeben, Daten vom neuen Hauptpi als Kopie halten.
    # Hat dieser Pi aber mehr neue Daten (Kabel war getrennt, Lauf lief hier), nicht ueberschreiben:
    # Der Partner gleicht sich dann selbst an uns an (stoppuhr-pruefen.sh).
    systemctl stop stoppuhr
    off() { timeout 2 redis-cli "$@" info replication 2>/dev/null | tr -d '\r' | awk -F: '/^master_repl_offset:/{print $2}'; }
    mine=$(off); peer=$(off -h "$PEER_IP")
    if [ "${mine:-0}" -gt "${peer:-0}" ] && [ -n "$peer" ]; then
      exit 0
    fi
    redis-cli replicaof "$PEER_IP" 6379 >/dev/null
    ;;
esac
