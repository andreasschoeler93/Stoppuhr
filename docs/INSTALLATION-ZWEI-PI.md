# Erstinstallation: zwei Raspberry Pis (Koffer-Pi und Bad-Pi)

Diese Anleitung richtet beide Pis von Grund auf ein. Ergebnis: Der Koffer-Pi arbeitet, der Bad-Pi hält eine Kopie und übernimmt bei einem Ausfall.
Die Oberfläche erreichst du danach unter `http://stoppuhr:1999` (oder `http://192.168.50.10:1999`).

> Der Aufbau ist noch nicht im Dauerbetrieb erprobt. Spiele vor dem Einsatz einmal die Testreihenfolge am Ende durch.

## 0. Überblick

| Was | Koffer-Pi | Bad-Pi |
|---|---|---|
| Rolle (Argument des Skripts) | `koffer` | `bad` |
| Hostname | `koffer-pi` | `bad-pi` |
| Feste Adresse (Taster-Netz) | 192.168.50.11 | 192.168.50.12 |
| Eigenes WLAN (versteckt, WPA2) | Koffer-WLAN | Bad-WLAN |
| DHCP-Bereich | .100–.149 | .150–.199 |
| Normalerweise | arbeitet | Kopie, Notbetrieb |

Gemeinsame Adresse (VIP): **192.168.50.10**. Sie liegt immer auf dem Pi, der gerade arbeitet.

## 1. Was du brauchst

- 2 × Raspberry Pi mit WLAN (getestet mit Raspberry Pi OS Lite, Debian 13 „trixie“), SD-Karten, Netzteile
- 1 × Netzwerkkabel zwischen den beiden Pis (direkt oder über einen Switch)
- Heimnetz mit Internet, **nur für die Installation**
- Zwei WLAN-Namen und zwei Kennwörter (je mindestens 8 Zeichen, nur druckbare ASCII-Zeichen ohne `"` und `\`). Sie müssen zu `secrets.h` der Taster passen (Schritt 7).
- PC mit SSH (PuTTY oder `ssh`)

## 2. Betriebssystem vorbereiten (je Pi)

1. Mit dem Raspberry Pi Imager „Raspberry Pi OS Lite (64 Bit)“ auf die SD-Karte schreiben.
2. In den Einstellungen des Imagers setzen: Hostname `koffer-pi` bzw. `bad-pi`, Benutzer `stoppuhr` mit Kennwort, SSH aktiv, WLAN-Land `DE`.
3. Pi starten. Für die Installation hängt er **per Kabel im Heimnetz mit Internet** (nicht schon am anderen Pi).
4. Per SSH verbinden (`ssh stoppuhr@koffer-pi.local` oder über die IP aus der Router-Liste).

## 3. Software installieren (je Pi, einzeln)

```bash
sudo apt-get update
sudo apt-get install -y git
mkdir -p ~/apps && cd ~/apps
git clone https://github.com/andreasschoeler93/Stoppuhr.git stoppuhr
cd stoppuhr
bash deploy/install.sh
```

Das Skript installiert Python, Redis und chrony, legt die Python-Umgebung an und startet die Dienste `stoppuhr` und `stoppuhr-knoten`.
Danach läuft die Oberfläche auf `http://<IP des Pi>:1999`. Prüfen: `curl -s localhost:1999/api/version`.

Ein Fehler „Permission denied“ bei `.venv` bedeutet, dass der Ordner einmal als `root` angelegt wurde:
`sudo chown -R stoppuhr:stoppuhr ~/apps/stoppuhr && rm -rf ~/apps/stoppuhr/.venv`, danach das Skript wiederholen.

Eine bestimmte Version statt `main`: `git fetch --tags && git checkout v0.8.0` (oder später in der Oberfläche unter Einstellungen → Pi-Software).

## 4. Zwei-Pi-Betrieb einrichten

Führe diesen Schritt **per SSH über das Kabel (`eth0`) oder am Monitor** aus. Das Skript bricht ab, wenn deine Sitzung über das WLAN läuft.
`eth0` bleibt am Router (DHCP), die SSH-Sitzung reißt also nicht ab. Beide Pis müssen dazu im Router-Netz hängen.
Dein PC bleibt unverändert im Heimnetz mit Internet, eine feste IP ist nicht nötig. Nach dem Skript erreichst du die Pis als
`ssh stoppuhr@stoppuhr-koffer.local` bzw. `stoppuhr-bad.local` und die Oberfläche als `http://stoppuhr-koffer.local:1999`.
Die Taster-WLANs sind davon getrennt und haben kein Internet.

### 4a. Koffer-Pi

Eine vorhandene alte Zugangspunkt-Verbindung vorher löschen (z. B. aus einem Einzelbetrieb): `nmcli con show`, dann `sudo nmcli con delete <Name>`.

```bash
cd ~/apps/stoppuhr
AP_SSID='Koffer-WLAN-Name' AP_PSK='Koffer-Kennwort' bash deploy/zwei-pi/install-zwei-pi.sh koffer
```

### 4b. Bad-Pi

```bash
cd ~/apps/stoppuhr
AP_SSID='Bad-WLAN-Name' AP_PSK='Bad-Kennwort' bash deploy/zwei-pi/install-zwei-pi.sh bad
```

Das Skript erledigt:

- Bridge `br0` mit fester Adresse, versteckter WLAN-Zugangspunkt (`ap`) und VXLAN-Tunnel `vxlan0` zum anderen Pi (über `eth0`, nur Taster-Verkehr). `eth0` selbst bleibt per DHCP am Router. Kommt die Bridge nicht hoch, wird das Taster-Netz wieder entfernt.
- Hostname `stoppuhr-koffer` bzw. `stoppuhr-bad` und Avahi (`.local`-Namen im Router-Netz)
- Redis im internen Netz erreichbar; der Bad-Pi wird Kopie (`replicaof 192.168.50.11`)
- Rolle in `/etc/stoppuhr-zwei-pi.env`
- keepalived (Koffer-Pi Priorität 150, Bad-Pi 100) für die gemeinsame Adresse
- chrony (beide Pis sind Zeitserver, der Bad-Pi gleicht sich am Koffer-Pi ab)
- dnsmasq (DHCP und der Name `stoppuhr` → 192.168.50.10)
- schaltet den Dienst `stoppuhr` auf Start durch keepalived um

Andere Adressen oder ein anderer Name: `VIP=`, `KOFFER_IP=`, `BAD_IP=`, `NAME=` vor den Aufruf setzen (auf beiden Pis gleich).

## 5. Prüfen

Auf jedem Pi:

```bash
cat /etc/stoppuhr-zwei-pi.env            # ROLLE=koffer bzw. bad
ip -4 addr show br0                      # Koffer-Pi: .11 (und .10, wenn er arbeitet); Bad-Pi: .12
nmcli -f NAME,DEVICE con show --active   # br0, vxlan0, ap, dazu die LAN-Verbindung (eth0)
systemctl is-active stoppuhr-knoten keepalived dnsmasq redis-server
redis-cli info replication | head -5     # Koffer: role:master, Bad: role:slave und master_link_status:up
```

Im Browser `http://192.168.50.10:1999` öffnen:

1. Beim ersten Öffnen **Benutzername und Kennwort festlegen** (mindestens 6 Zeichen). Der Zugang liegt in Redis und gilt dadurch auch auf dem Bad-Pi.
2. Tab „Systemstatus“: Koffer-Pi „arbeitet“, Bad-Pi „Bereitschaft“, Daten „Kopie (synchron)“.

## 6. Einstellungen in der Oberfläche

- **WLAN-Netze:** Namen und Kennwörter müssen den Werten aus Schritt 4 entsprechen. Spätere Änderungen werden erst an die Taster und dann an beide Pis verteilt.
  Der Koffer-Pi nutzt das Koffer-WLAN, der Bad-Pi das Bad-WLAN (Rolle aus `/etc/stoppuhr-zwei-pi.env`).
- **Taster-Firmware:** Firmware aus GitHub laden und an die Taster verteilen (ab v0.11.0).
- **Pi-Software:** wechselt die Version nur des Pi, in dessen Oberfläche du bist. Bei beiden Pis einzeln, nicht im Wettkampf.

## 7. Taster einrichten

1. Im Repository `Taster` `src/secrets.example.h` nach `src/secrets.h` kopieren und ausfüllen:
   - `SECRET_WIFI_SSID` / `SECRET_WIFI_PASS`: Koffer-WLAN
   - `SECRET_WIFI2_SSID` / `SECRET_WIFI2_PASS`: Bad-WLAN
   - `SECRET_PI_IP`: `"192.168.50.10"` (VIP) oder `"stoppuhr"`
2. Per USB flashen: `pio run -e seeed_xiao_esp32s3 -t upload`. Weitere Updates und WLAN-Änderungen laufen drahtlos über den Pi.
3. Taster einschalten: Er erscheint in der Oberfläche und bekommt einen Buchstaben.

## 8. Testreihenfolge vor dem Einsatz

1. Systemstatus: Koffer-Pi „arbeitet“, Bad-Pi „Bereitschaft“, Daten synchron.
2. Taster ohne Rolle einschalten: Er ist im Koffer-WLAN. Rolle zuweisen: Er wechselt ins Bad-WLAN.
3. Testlauf starten, Zeiten messen.
4. Koffer-Pi vom Strom trennen: Nach wenigen Sekunden steht oben „Aktiv: Bad-Pi“. Zeiten und Zuordnungen sind noch da, ein Lauf lässt sich starten.
5. Koffer-Pi wieder einschalten: Er gleicht ab und arbeitet nach etwa 10 s wieder. Die Zeiten aus Schritt 4 sind noch vorhanden.
6. „Wettkampf beenden“: Taster kehren ins Koffer-WLAN zurück.

## 9. Updates

Ohne Oberfläche, auf jedem Pi:

```bash
cd ~/apps/stoppuhr && git fetch origin --tags && git switch main && git pull --ff-only origin main
bash deploy/install.sh                 # nur nötig, wenn sich Installationsdateien geändert haben (siehe CHANGELOG)
sudo systemctl restart stoppuhr-knoten
sudo systemctl restart stoppuhr        # beim Bad-Pi startet keepalived den Dienst nur bei Bedarf; dann überspringen
```

## 10. Fehlersuche

| Problem | Ursache und Hilfe |
|---|---|
| `install.sh`: Permission denied bei `.venv` | Ordner gehört `root`: `sudo chown -R stoppuhr:stoppuhr ~/apps/stoppuhr` |
| Installer: „Du bist per WLAN verbunden“ | Per Kabel oder Monitor ausführen |
| Pi nach dem Umbau nicht erreichbar | `ping stoppuhr-koffer.local` bzw. IP in der Router-Liste suchen. Notfalls mit Monitor: `sudo nmcli con delete ap vxlan0 br0 br0-eth0` und `sudo nmcli con up "Wired connection 1"` |
| Redis startet nicht | `journalctl -xeu redis-server`; neueste Version des Skripts holen (`git pull`) |
| Bad-Pi: `master_link_status:down` | Beide Pis im selben Router-Netz? `ping 192.168.50.11` (läuft über den Tunnel). Hilft nichts: Multicast geht nicht durch den Router, dann `VXLAN_REMOTE=<LAN-IP des anderen Pi>` beim Skriptaufruf setzen (beide Pis, Router-Adresse reservieren) |
| Beide Pis „arbeiten“ | Kabel nicht verbunden. Nach dem Anstecken gewinnt der Koffer-Pi |
| Name `stoppuhr` löst nicht auf | Das Gerät nutzt nicht das Pi-WLAN als DNS. `http://192.168.50.10:1999` verwenden |
| Kennwort der Oberfläche vergessen | Auf dem Koffer-Pi `redis-cli del AUTH`, dann neu festlegen |
| WLAN-Umstellung wirkt nicht | Verbindung heißt nicht `ap`: `AP_CONNECTION=<Name>` mit `sudo systemctl edit stoppuhr-knoten` setzen (`[Service]`, `Environment=AP_CONNECTION=<Name>`) |
| Logs | `journalctl -u stoppuhr -f`, `journalctl -u stoppuhr-knoten -f`, `journalctl -u keepalived -f` |

Hintergründe, Taster-Tausch und Grenzen: [deploy/zwei-pi/README.md](../deploy/zwei-pi/README.md).
