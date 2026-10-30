# Stoppuhr – Pi-Software (v0.16.1)

Webbasierte Wettkampf-Stoppuhr: ESP32-Taster messen die Zeit, der Raspberry Pi sammelt, wertet aus und
liefert die Ergebnisse an JAuswertung. Die Taster-Firmware liegt im Repository `Taster`.

> **Der Pi wertet aus. Die Taster messen Zeit. Nichts geht verloren.**

Versionsverlauf: [CHANGELOG.md](CHANGELOG.md). Zwei-Pi-Betrieb (Koffer und Bad): Schritt-für-Schritt-Anleitung in
[docs/INSTALLATION-ZWEI-PI.md](docs/INSTALLATION-ZWEI-PI.md), Hintergründe in [deploy/zwei-pi/README.md](deploy/zwei-pi/README.md).

## Funktionen

- Startkarten-Import (manuell), dynamische Bahnanzahl, Drag & Drop der Taster auf Bahnen und Starter
- Start, Stopp, automatisch nächster Lauf, Abbruch und Wiederholung eines Laufs
- Taster tauschen über „Bereitschaft“, Systemstatus, Zwei-Pi-Betrieb mit Ausfallübernahme
- Anmeldung für die Oberfläche, WLAN-Daten und Updates (Pi und Taster) aus der Oberfläche
- Tab „Vitaldaten“ (ab v0.9.0): je ein Diagramm für Akku, Akkuspannung, Temperatur, Luftfeuchte und WLAN-Stärke mit allen Tastern in eigenen Farben (letzte 15/30 Minuten, 1/3/6 Stunden). Senkrechte gestrichelte Linien „L<Nr>“ markieren jeden Laufstart.
  Die Werte kommen aus den ohnehin alle 10 s gesendeten Vitaldaten (kein Mehraufwand am Taster) und liegen in Redis (`VITALS_HIST:<MAC>`, höchstens 6 Stunden).
  Schnittstelle: `GET /api/vitals/history?mac=…&hours=…`.
- Ladekoffer (ab v0.12.0): Die Ladeplatine (Projekt `Ladekoffer`) sendet alle 5 s per `POST /api/charger` (JSON) Ladezustand der 10 Plätze, Temperatur, Luftfeuchte und Ampel. Der Pi wertet daraus Statusmeldungen aus (Kopfzeile, Meldungen oben, Tabelle im Tab „Vitaldaten“). Nach 30 s ohne Meldung gilt der Ladekoffer als offline. `GET /api/charger` liefert den ausgewerteten Zustand. Die Taster sind davon nicht betroffen.

## Installation

### Auf dem Raspberry Pi (ohne Docker, empfohlen)

Installiert Python-Umgebung, Redis, chrony und systemd-Dienste, die beim Booten starten:

```bash
sudo apt-get install -y git
git clone https://github.com/andreasschoeler93/Stoppuhr-2.0-Stoppuhr.git
cd Stoppuhr
bash deploy/install.sh
```

- Oberfläche: `http://<PI-IP>:1999`. Beim ersten Öffnen legst du Benutzername und Kennwort fest.
- Dienste: `stoppuhr` (Server) und `stoppuhr-knoten` (Systemstatus, WLAN-Umstellung). Log: `journalctl -u stoppuhr -f`.
- Die Daten liegen in Redis (`save 10 1`), nicht im Projektordner.
- Einstellungen per Umgebungsvariable in `deploy/stoppuhr.service`: `REDIS_HOST`, `REDIS_PORT`, `PORT`, `HEATS_XML_PATH`.
- Zeitserver für die Taster: in `/etc/chrony/chrony.conf` `allow <Taster-Netz>` ergänzen
  (ohne Internet zusätzlich `local stratum 10`), danach `sudo systemctl restart chrony`.

### Mit Docker (Entwicklung)

```bash
docker compose up --build -d
```

Pi-Software-Wechsel und WLAN-Umstellung funktionieren nur ohne Docker.

### Tests

```bash
docker run --rm -v "$PWD/backend:/backend" -w /backend stoppuhr-app:latest python -m unittest discover -s tests
```

## Bedienung

### Anmeldung

Die ganze Oberfläche ist durch Benutzername und Kennwort geschützt. Beim ersten Öffnen legst du beide fest.
Ändern: **Einstellungen → Zugang zur Oberfläche** (das alte Kennwort wird abgefragt; andere Sitzungen werden abgemeldet).
Ohne Anmeldung bleiben nur erreichbar: die Schnittstellen der Taster (`/api/taster`, `/api/vitals`, `/api/charger` (nur POST), `/api/triggers`,
`/api/display`, `/api/abort-run`, Firmware-Download, `/api/ota-status`), `/api/version` und der Export `/heats.xml` für JAuswertung.
Die Sitzung bleibt 30 Tage; nach fünf Fehlversuchen pro Minute sperrt der Server die Anmeldung kurz.
Der Schlüssel der Sitzungen und der Kennwort-Hash liegen in Redis und werden im Zwei-Pi-Betrieb mitkopiert.
Kennwort vergessen: auf dem Pi `redis-cli del AUTH`, danach beim nächsten Öffnen neu festlegen.

### Wettkampf beenden

**Einstellungen → Wettkampf beenden** löscht nach Bestätigung Startkarten, Zeiten, Taster und Bahnzuordnungen und leert den XML-Export.
Der Server sendet den Abschaltbefehl während der eingestellten Dauer (Standard 10 s) bei den Display-Abfragen mit.
Taster, die in dieser Zeit nicht verbunden sind, empfangen ihn nicht. Buchstaben werden danach ab A neu vergeben.

### Abbruch und Wiederholung

Ein langer Druck (2 s) am Starter bricht den Versuch ab (dreimal langes Piepen) und bereitet die nächste Version desselben Laufs vor.
Die Stopp-Sperre beginnt mit dem Abbruch. Über **Versuch vorbereiten** geht das auch in der Oberfläche.
Gespeicherte Zeiten bleiben; Versionen werden getrennt nummeriert (z. B. `5/2`) und im XML-Export als eigener Heat ausgegeben.

### Taster-Anzeige

`GET /api/display` liefert Namen und Disziplinen als UTF-8 mit Umlauten; die Firmware stellt `ä ö ü Ä Ö Ü` korrekt dar.

### Zieleinlauf und Abbruch durch den Starter (ab v0.13.0)

- **Zieleinlauf-Taster** (optional): wie den Starter per Drag & Drop auf „Zieleinlauf“ ziehen. Jeder Druck nach dem Start wird gesammelt; die **Bahnzeit bleibt die Hauptzeit**.
- Die gesammelten Zeiten werden automatisch der nächstliegenden Bahnzeit zugeordnet (höchstens 3 s Abstand). In der Spalte „Zieleinlauf“ steht die Abweichung (Zieleinlauf minus Bahn, ab 0,5 s rot).
- Geparkte (nicht zugeordnete) Zeiten erscheinen unter der Tabelle und lassen sich per Drag & Drop auf die Spalte „Zieleinlauf“ einer Bahn ziehen. Auch bereits zugeordnete Zeiten (automatisch oder händisch) lassen sich auf eine andere Bahn ziehen oder zurück in den Parkbereich ziehen; „✕“ parkt ebenfalls. Eine Zeit, die auf eine belegte Bahn fällt, ersetzt die dortige, diese wandert in den Parkbereich. Die Zuordnung ändert die Bahnzeiten nicht.
- Die Abweichung zur Bahnzeit wird ab dem Grenzwert gelb bzw. rot (Standard 0,5 s / 1 s, einstellbar unter Einstellungen → Grenzwerte).
- **Starter / Zieleinlauf (ab v0.14.0):** Einstellungen → Option „Starter-Taster erfasst zusätzlich den Zieleinlauf“. Der Starter-Taster behält die Starteransicht; der erste Druck startet, jeder weitere (auch bis 5 s nach Lauf-Ende) wird im Hintergrund als Zieleinlauf-Zeit gesammelt. Der Doppeldruck-Stopp entfällt dabei.
- **Übertragen (ab v0.13.2):** Der Button unter der Tabelle legt bei jedem Klick eine **neue Laufversion** an (Lauf 5/2, dann 5/3 …) und schickt sie an JAuswertung. Bahnen mit zugeordneter Zieleinlauf-Zeit bekommen diese, alle anderen Bahnen ihre normal gestoppte Zeit (ab v0.13.4). „Letzte Version zurücknehmen“ entfernt die jeweils neueste.
- Der Zieleinlauf-Taster nimmt auch schnelle Druckfolgen an (mehrere Schwimmer kurz hintereinander).
- **Zweiter Druck des Starters** bei laufender Uhr (frühestens 1,5 s nach dem Start) beendet den Lauf. Bahnen ohne Zeit bleiben leer; oben erscheint ein Hinweis.

## Einstellungen: WLAN, Zugang und Updates

### Grenzwerte (ab v0.12.5)

**Einstellungen → Grenzwerte**: Je Messwert (Akku, Spannung, Temperatur, Luftfeuchte, WLAN-Signal von Tastern; CPU-Temperatur, CPU-Last, Speicher, SD-Karte der Pis;
Temperatur, Luftfeuchte und WLAN des Ladekoffers) ein gelber und ein roter Wert. Danach richten sich die Schriftfarben in der Übersicht,
die Hinterlegung bei Bahnen und Tastern und die Balken oben. Bei „Wert darunter ist schlecht“ (Akku, Spannung, WLAN) muss der rote Wert kleiner oder gleich dem gelben sein, sonst umgekehrt.
**Standardwerte** setzt alles zurück. Gespeichert wird in den Einstellungen des Servers (`GET/POST /api/limits`).

### WLAN-Netze (ab v0.8.0)

**Einstellungen → WLAN-Netze**: Name und Kennwort von Koffer- und Bad-WLAN. Leeres Kennwortfeld = unverändert.
Ablauf nach **Übernehmen**:

1. Die online Taster holen sich die neuen Daten, speichern sie vor und bestätigen sie (Anzeige „n von m bestätigt“).
2. Erst wenn alle online Taster bestätigt haben, stellt jeder Pi sein WLAN um (`nmcli con modify ap …`, Dienst `stoppuhr-knoten`).
   Der Koffer-Pi nimmt das Koffer-WLAN, der Bad-Pi das Bad-WLAN, ein einzelner Pi das Koffer-WLAN.
3. Die Taster verlieren kurz die Verbindung, probieren dann die neuen Daten und übernehmen sie dauerhaft.

Hinweise:

- **Jetzt auch am Pi umstellen** erzwingt Schritt 2, auch wenn nicht alle Taster bestätigt haben.
  Taster, die offline waren, finden das Netz danach nicht mehr und müssen per USB neu geflasht werden.
- Die Verbindung zur Oberfläche bricht beim Umstellen kurz ab, wenn du über das umgestellte WLAN verbunden bist.
- Während eines Laufs gesperrt; nach dem ersten gestarteten Lauf nur nach Eintippen von `UPDATE`.
- Die Daten gehen im Klartext über das interne Netz an die Taster (`GET /api/display`, nur bekannte Taster).
- Voraussetzung: Die WLAN-Verbindung des Pi heißt `ap` (so legt sie `deploy/zwei-pi/install-zwei-pi.sh` an).
  Ändere eine WLAN-Verbindung von Hand, den Namen über `AP_CONNECTION` setzen.
- Taster mit Firmware vor `v0.12.0` bestätigen nicht; sie bleiben bei den alten Daten.

### Taster-Firmware (ab v0.7.0)

**Einstellungen → Taster-Firmware** listet die Firmware-Releases aus GitHub (`andreasschoeler93/Stoppuhr-2.0-Taster`, änderbar mit `FIRMWARE_REPO`).
**Auf Taster laden** speichert die `firmware.bin` unter `backend/firmware_cache/` (`FIRMWARE_DIR`) und bietet sie allen online Tastern an.
Diese laden sie vom Pi, prüfen die MD5 und starten neu. Ohne Internet stehen bereits gespeicherte Versionen zur Verfügung.

- Angeboten werden nur Releases ab `v0.11.0`.
- Gesperrt, sobald ein Lauf gestartet wurde (nur mit `UPDATE`); ein Taster bekommt die Datei nie während eines Laufs.
- Fehlgeschlagene Updates stehen in der Tabelle. Releases entstehen automatisch, wenn im Taster-Repo ein Tag `vX.Y.Z` hochgeladen wird.

### Pi-Software (ab v0.7.1)

**Einstellungen → Pi-Software**: Version (Git-Tag ab `v0.5.1`) wählen und **Übernehmen und neu starten**.
Der Pi holt die Tags von GitHub, wechselt darauf (`git checkout`), installiert geänderte Abhängigkeiten und startet den Dienst neu (ca. 5 s).

- Nur ohne Docker. Bei lokalen Änderungen im Ordner bricht der Wechsel mit Fehlermeldung ab.
- Gesperrt während eines Laufs; nach dem ersten gestarteten Lauf nur mit `UPDATE`.
- Wechselt nur den Pi, dessen Oberfläche du bedienst (im Zwei-Pi-Betrieb beide einzeln).
- Danach steht der Pi „detached“ auf dem Tag. Zurück zum Branch: `cd ~/apps/stoppuhr && git switch main`.
- Bleibt die Liste leer: `curl -s localhost:1999/api/pi-update/releases` zeigt Fehler (z. B. kein Internet beim Abholen der Tags). Voraussetzung ist Version ab v0.7.1.

## Versionierung

Schema `MAJOR.MINOR.PATCH`, die Version steht in `backend/app.py` (`APP_VERSION`). Jede Änderung erhöht sie und bekommt einen Tag:
`git tag vX.Y.Z && git push origin vX.Y.Z`. Der Verlauf steht in [CHANGELOG.md](CHANGELOG.md).

- **PATCH**: Fehlerkorrekturen
- **MINOR**: neue Funktionen, abwärtskompatibel
- **MAJOR**: grundlegende Änderungen; `1.0.0` = Wettkampf-Freigabe

Update auf dem Pi ohne Oberfläche:

```bash
cd ~/apps/stoppuhr && git fetch origin --tags && git switch main && git pull --ff-only origin main && sudo systemctl restart stoppuhr
```

## Roadmap

- [x] Dynamische Bahnen, persistente Taster-Zuordnung
- [x] Zwei-Pi-Betrieb, Updates aus der Oberfläche, Anmeldung
- [ ] Backup-Zieleinlauf (Differenzanzeige)
- [ ] Warnlogik (gelb / rot / ok)
- [ ] Lauf-Historie, nachträgliche Korrektur per Drag & Drop
- [ ] 1.0: wettkampftauglich, Dokumentation, Freeze
