# Stoppuhr – v0.5.1 (Stable Beta)

Webbasierte Wettkampf-Stoppuhr mit ESP-Tastern und Raspberry-Pi-Backend.

---

## Aktueller Stand (v0.5.1)

✅ Startkarten-Import (manuell geladen)

✅ Dynamische Bahnanzahl (max aus CSV, Rest inaktiv)

✅ Drag & Drop Taster-Zuordnung (immer möglich)

✅ Start / Stopp / Auto-Next-Run

✅ Wiederholungsläufe ohne Überschreiben vorheriger Zeiten

✅ GitHub-fähig & reproduzierbar

---

## Installation (Raspberry Pi)

```bash
cd /home/dlrg
git clone https://github.com/andreasschoeler93/Stoppuhr.git stoppuhr
cd stoppuhr

# Start application via Docker Compose
docker compose up --build -d
```

Weboberfläche:
```
http://<PI-IP>:1999
```

### Alternative: ohne Docker (direkt auf dem Pi)

Installiert Python-Umgebung, Redis und einen systemd-Dienst, der beim Booten startet:

```bash
sudo apt-get install -y git
git clone https://github.com/andreasschoeler93/Stoppuhr.git
cd Stoppuhr
bash deploy/install.sh
```

- Dienst: `sudo systemctl status stoppuhr`, Log: `journalctl -u stoppuhr -f`.
- Update: `git pull && sudo systemctl restart stoppuhr`.
- Die Daten liegen in Redis (`save 10 1`), nicht im Projektordner.
- Konfiguriert wird über Umgebungsvariablen in `deploy/stoppuhr.service`
  (`REDIS_HOST`, `REDIS_PORT`, `PORT`, `HEATS_XML_PATH`); die Voreinstellungen entsprechen Docker.
- Zeitserver für die Taster: in `/etc/chrony/chrony.conf` `allow <Taster-Netz>` ergänzen
  (ohne Internet zusätzlich `local stratum 10`), danach `sudo systemctl restart chrony`.

### Taster-Anzeige

`GET /api/display` liefert Namen und Disziplinen unverändert mit deutschen Umlauten als UTF-8.
Die Firmware kann dadurch `ä`, `ö`, `ü`, `Ä`, `Ö` und `Ü` korrekt darstellen.

Über **Einstellungen → Wettkampf beenden** lässt sich nach einer Bestätigung der Wettkampf zurücksetzen.
Dabei werden Startkarten, Zeiten/Ergebnisse, Taster und Bahnzuordnungen gelöscht; der XML-Export wird geleert.
Der Server sendet den Abschaltbefehl während der eingestellten Dauer (Standard: 10 Sekunden) bei den
regelmäßigen Display-Abfragen mit. Taster, die in dieser Zeit nicht mit dem Pi verbunden sind, können ihn
nicht empfangen. Die Buchstaben werden bei der nächsten Anmeldung wieder ab A vergeben.

### Abbruch und Wiederholung eines Laufs

Ein langer Druck (2 Sekunden) auf den Starter-Taster bricht den laufenden Versuch ab und bereitet
die nächste Version desselben Laufs vor. Die Stopp-Sperre beginnt mit dem Abbruch; vor ihrem Ablauf
wird ein kurzer Startdruck abgewiesen. Über **Versuch vorbereiten** lässt sich im Webinterface
ebenfalls eine neue Version eines ausgewählten Laufs anlegen. Bereits gespeicherte Zeiten bleiben
erhalten; Versionen werden separat nummeriert (z. B. `5/2`) und im XML-Export als eigener Heat
ausgegeben.

### Taster-Firmware aktualisieren (ab v0.7.0)

Unter **Einstellungen → Taster-Firmware** listet der Pi alle Firmware-Releases aus GitHub
(`andreasschoeler93/Taster`, änderbar mit `FIRMWARE_REPO`). **Auf Taster laden** speichert die gewählte
`firmware.bin` unter `backend/firmware_cache/` (`FIRMWARE_DIR`) und bietet sie allen Tastern an, die gerade online
sind. Die Taster laden sie selbst vom Pi, prüfen die MD5 und starten neu. Ohne Internet stehen die bereits
gespeicherten Versionen zur Verfügung.

- Es werden nur Releases ab `v0.11.0` angeboten (frühere Firmware kann sich so nicht installieren lassen).
- Sobald im Wettkampf ein Lauf gestartet wurde, ist das Update gesperrt und nur nach Eintippen von `UPDATE` möglich.
- Ein Taster bekommt die Datei nie, solange ein Lauf läuft. Ein fehlgeschlagenes Update wird in der Tabelle angezeigt.
- Releases entstehen automatisch, wenn im Taster-Repo ein Tag `vX.Y.Z` hochgeladen wird.

## Versionierung

- Produktive Basis: **v0.5.1**
- Entwicklung ab jetzt **nur über GitHub**
- Neue Features → neue Minor-Version

---

## Roadmap (Checklist)

### v0.4.x
- [x] Dynamische Bahnen
- [x] Persistente Taster-Zuordnung
- [ ] Backup-Zieleinlauf (Differenzanzeige)
- [ ] Warnlogik (gelb / rot / ok)

### v0.5.x
- [ ] Lauf-Historie
- [ ] Nachträgliche Korrektur per Drag & Drop
- [ ] Wiederaufnahme nach Neustart

### v1.0
- [ ] Wettkampftauglich
- [ ] Dokumentation
- [ ] Freeze

---

## Philosophie

**Der Pi wertet aus.  
Die Taster messen Zeit.  
Nichts geht verloren.**
