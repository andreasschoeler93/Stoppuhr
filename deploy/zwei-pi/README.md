# Zwei-Pi-Betrieb (Stufe 2, Backend v0.6.0 / Firmware v0.10.0)

Nicht für den ersten Wettkampf gedacht – der läuft mit v0.5.1 / v0.9.1. Diese Stufe liegt auf dem Branch `feature/zwei-pi`.

## Aufbau

```
Taster ohne Rolle ──Koffer-WLAN──► Koffer-Pi ──┐
                                               ├── VXLAN-Tunnel (Bridge br0, 192.168.50.0/24)
Taster mit Rolle  ──Bad-WLAN────► Bad-Pi ──────┘        durch das Router-Netz

PC ── Router/Internet ── eth0 beider Pis (DHCP, Name stoppuhr-koffer.local / stoppuhr-bad.local)
```

Das Taster-Netz ist abgeschottet: `eth0` hängt per DHCP am Router und gehört **nicht** zur Bridge. Der Tunnel `vxlan0` (Multicast `239.50.50.50`, bei Bedarf `VXLAN_REMOTE=<IP des anderen Pi>`) verbindet nur die beiden Taster-WLANs. Es gibt keine Weiterleitung ins Internet.

| Was | Adresse |
|---|---|
| Gemeinsame Server-Adresse (VIP, im Taster als `SECRET_PI_IP`) | 192.168.50.10 |
| Koffer-Pi (Haupt) | 192.168.50.11 |
| Bad-Pi (Notbetrieb + Kopie) | 192.168.50.12 |

- Beide Pis sind per Kabel verbunden. Jeder macht sein WLAN als Zugangspunkt (versteckt, WPA2) und hängt es in die Bridge `br0`. Alle Geräte liegen dadurch im selben Netz.
- Die Taster funken nur auf 2,4 GHz. Die Zugangspunkte sind deshalb fest auf 2,4 GHz eingestellt: Koffer-Pi Kanal 1, Bad-Pi Kanal 11. Die Kanäle 1, 6 und 11 sind nicht überlappend; vor Ort kann ein WLAN-Scan zeigen, ob ein anderer dieser Kanäle weniger belegt ist.
- Die VIP liegt immer auf dem Pi, der gerade arbeitet (keepalived). Die Taster merken von einem Wechsel nichts, ihre Wiederholungen und die Warteschlange fangen die Sekunden dazwischen ab.
- Der Koffer-Pi arbeitet normalerweise. Der Bad-Pi ist nur Zugangspunkt und hält über Redis-Replikation eine laufende Kopie.
- Fällt der Koffer-Pi aus oder startet neu, übernimmt der Bad-Pi automatisch (Stoppuhr-Dienst startet dort, Kopie wird zum Hauptbestand). Kommt der Koffer-Pi zurück, gleicht er zuerst die Daten vom Bad-Pi ab und übernimmt erst nach 10 s Wartezeit, wenn alles synchron ist.
- Zeit: Beide Pis sind NTP-Server, der Bad-Pi gleicht sich am Koffer-Pi ab. Die Taster holen die Zeit von der VIP.

## Taster

In `src/secrets.h`: `SECRET_WIFI_*` = Koffer-WLAN, `SECRET_WIFI2_*` = Bad-WLAN, `SECRET_PI_IP` = VIP.
Taster ohne Rolle sind im Koffer-WLAN. Mit Rollenzuweisung wechseln sie sofort ins Bad-WLAN, auch wenn es nicht erreichbar ist. Zurück ins Koffer-WLAN gehen sie nur, wenn die Rolle entzogen wird oder der Wettkampf beendet wird.

## Einrichtung (je Pi)

1. `bash deploy/install.sh` (wie bisher).
2. Bridge und WLAN-Zugangspunkt: das erledigt `install-zwei-pi.sh` selbst, wenn `AP_SSID` und `AP_PSK` gesetzt sind
   (`AP_SSID=KOFFER-SSID AP_PSK=PASSWORT bash deploy/zwei-pi/install-zwei-pi.sh koffer`). Kommt die Bridge nicht hoch, stellt es
   den alten Zustand wieder her. Per WLAN-SSH bricht es ab (Umbau würde die Sitzung kappen; `FORCE=1` übergeht das), besser per Kabel.
   Der Koffer-Pi verwendet standardmäßig Kanal 1, der Bad-Pi Kanal 11. Mit `AP_CHANNEL=6` lässt sich beim Einrichten ein anderer der üblichen überlappungsfreien 2,4-GHz-Kanäle wählen.
   Von Hand (Beispiel Koffer-Pi, beim Bad-Pi IP `.12`, andere SSID):

```bash
sudo nmcli con add type bridge ifname br0 con-name br0 ipv4.method manual ipv4.addresses 192.168.50.11/24 bridge.stp no
sudo nmcli con add type vxlan ifname vxlan0 con-name vxlan0 vxlan.id 50 vxlan.remote 239.50.50.50 \
  vxlan.parent eth0 vxlan.destination-port 4789 connection.master br0 connection.slave-type bridge
sudo nmcli con add type wifi ifname wlan0 con-name ap ssid KOFFER-SSID mode ap wifi.hidden yes \
  802-11-wireless.band bg 802-11-wireless.channel 1 \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk 'PASSWORT' connection.master br0 connection.slave-type bridge
sudo nmcli con up br0
```

### Bestehende Pis umstellen

Nach einem Update das folgende Skript **auf beiden Pis einzeln per Ethernet-SSH oder am Monitor** ausführen, nicht während eines Wettkampfs. Es setzt das WLAN-Band und den Kanal und startet den jeweiligen Zugangspunkt neu. Der WLAN-Zugriff der Taster kann dabei kurz unterbrochen werden.

```bash
cd ~/apps/stoppuhr
sudo bash deploy/zwei-pi/wlan-kanal-setzen.sh
```

Standard: Koffer-Pi Kanal 1, Bad-Pi Kanal 11. Ein anderer Kanal kann als Argument angegeben werden (nur 1, 6 oder 11), zum Beispiel `sudo bash deploy/zwei-pi/wlan-kanal-setzen.sh 6`. Vor einer abweichenden Kanalwahl beide Pis mit einem WLAN-Scanner am Einsatzort prüfen. Der Pi-Pi-Tunnel läuft über Ethernet; diese Änderung betrifft nur die Taster-WLANs.

3. DHCP und Name: übernimmt `install-zwei-pi.sh` (nächster Schritt) per `dnsmasq`. Koffer vergibt `.100`–`.149`, Bad `.150`–`.199`,
   damit auch bei Ausfall eines Pi Adressen vergeben werden. Beide antworten auf den Namen **`stoppuhr`** mit der gemeinsamen Adresse
   (anderer Name: `NAME=...`). Im Browser genügt dann `http://stoppuhr:1999`, es kommt immer die Oberfläche des arbeitenden Pi.
   Das gilt für Geräte in einem der beiden WLANs (sie nutzen den Pi als DNS-Server). Sonst `http://192.168.50.10:1999`.
   Das Skript setzt die Hostnamen `stoppuhr-koffer` bzw. `stoppuhr-bad` (per Avahi als `<name>.local` im Router-Netz erreichbar); der Name `stoppuhr` gehört der gemeinsamen Adresse.
4. Zwei-Pi-Dienste: `bash deploy/zwei-pi/install-zwei-pi.sh koffer` bzw. `... bad`. Abweichende Adressen über `VIP=`, `KOFFER_IP=`, `BAD_IP=`.
   Der normale Dienst `stoppuhr` wird dabei abgeschaltet; keepalived startet ihn nur auf dem arbeitenden Pi.

## Taster tauschen (Bereitschaft, ab Backend v0.6.2 / Firmware v0.10.2)

Ziehst du einen Taster (B) auf eine Bahn oder den Starter, die schon von einem anderen Taster (A) belegt ist, wird nicht sofort getauscht:

1. Taster B geht in **Bereitschaft**: Er wechselt ins Bad-WLAN und zeigt „Bereit: Bahn N“ (bzw. „Bereit: Start“).
2. Beim **ersten Druck auf Taster B** vor Ort tauschen die Rollen – aber nur, wenn gerade kein Lauf läuft (Start gedrückt, noch nicht abgeschlossen). Läuft einer, bleibt B in Bereitschaft; der Druck wird ignoriert und zählt nie als Messung.
3. Taster A verliert die Rolle und geht zurück ins Koffer-WLAN.

In der Weboberfläche zeigt die Bahn „Bereitschaft: B“ mit den Knöpfen „Sofort tauschen“ und „Abbrechen“. Eine freie Bahn wird weiterhin sofort belegt. Bei „Entfernen“ der Bahn und bei „Wettkampf beenden“ verfällt die Bereitschaft.
API: `POST /api/assign` (mit `"immediate": true` sofort), `POST /api/cancel-pending`; `/api/display` liefert `pending_lane`.

## Weboberfläche

Der Tab „Systemstatus“ zeigt im Zwei-Pi-Betrieb beide Pis: wer arbeitet, Hostname, WLAN-Name, IP-Adressen, Redis-Zustand (Hauptbestand/Kopie, synchron), Stoppuhr-Dienst, letzter Wechsel, CPU/Temperatur/RAM/Disk. Oben rechts steht ein Kennzeichen „Aktiv: Koffer-Pi/Bad-Pi“ (grün = alles gut, gelb = Partner fehlt oder Kopie nicht synchron, rot = niemand arbeitet). Zusätzlich: Anzahl Taster online je WLAN, und je Taster das aktuelle WLAN (ab Firmware v0.10.1).
Jeder Pi liefert seinen Zustand über den Dienst `stoppuhr-knoten` (Port 2000), der immer läuft; so ist der Partner auch im Standby sichtbar.

## Testreihenfolge vor dem Einsatz

1. Beide Pis einrichten, Kabel verbinden. Systemstatus: Koffer-Pi „arbeitet“, Bad-Pi „Bereitschaft“, Daten „Kopie (synchron)“.
2. Einen Taster ohne Rolle einschalten: Er erscheint im Koffer-WLAN. Rolle zuweisen: Er wechselt ins Bad-WLAN (Anzeige „Taster online je WLAN“).
3. Testlauf starten, ein paar Zeiten messen.
4. Koffer-Pi vom Strom trennen: Nach wenigen Sekunden steht oben „Aktiv: Bad-Pi“, Zeiten und Zuordnungen sind noch da, ein Lauf lässt sich starten.
5. Koffer-Pi wieder einschalten: Er gleicht ab (Daten „Kopie“, dann nach ca. 10 s „arbeitet“). Prüfen, dass die Zeiten aus Schritt 4 noch vorhanden sind.
6. Kabel ziehen und wieder anstecken, dann „Wettkampf beenden“: Taster kehren ins Koffer-WLAN zurück.

## Bekannte Grenzen

- Starten beide Pis gleichzeitig ohne Kabelverbindung, arbeiten kurz beide; nach dem Anstecken des Kabels gewinnt der Koffer-Pi, der Bad-Pi gleicht sich an ihm ab.
- Redis ist nur im internen Netz offen (kein Passwort). Das Netz nicht ans Internet anbinden.
- Der Wechsel dauert wenige Sekunden. Gerade gedrückte Taster senden danach erneut.
- Bitte vor dem Einsatz Ausfall und Rückkehr einmal mit Testdaten durchspielen.
