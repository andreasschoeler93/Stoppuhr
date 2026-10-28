# Zwei-Pi-Betrieb (Stufe 2, Backend v0.6.0 / Firmware v0.10.0)

Nicht für den ersten Wettkampf gedacht – der läuft mit v0.5.1 / v0.9.1. Diese Stufe liegt auf dem Branch `feature/zwei-pi`.

## Aufbau

```
Taster ohne Rolle ──Koffer-WLAN──► Koffer-Pi ──┐
                                               ├── LAN-Kabel (Bridge br0, 192.168.50.0/24)
Taster mit Rolle  ──Bad-WLAN────► Bad-Pi ──────┘
```

| Was | Adresse |
|---|---|
| Gemeinsame Server-Adresse (VIP, im Taster als `SECRET_PI_IP`) | 192.168.50.10 |
| Koffer-Pi (Haupt) | 192.168.50.11 |
| Bad-Pi (Notbetrieb + Kopie) | 192.168.50.12 |

- Beide Pis sind per Kabel verbunden. Jeder macht sein WLAN als Zugangspunkt (versteckt, WPA2) und hängt es in die Bridge `br0`. Alle Geräte liegen dadurch im selben Netz.
- Die VIP liegt immer auf dem Pi, der gerade arbeitet (keepalived). Die Taster merken von einem Wechsel nichts, ihre Wiederholungen und die Warteschlange fangen die Sekunden dazwischen ab.
- Der Koffer-Pi arbeitet normalerweise. Der Bad-Pi ist nur Zugangspunkt und hält über Redis-Replikation eine laufende Kopie.
- Fällt der Koffer-Pi aus oder startet neu, übernimmt der Bad-Pi automatisch (Stoppuhr-Dienst startet dort, Kopie wird zum Hauptbestand). Kommt der Koffer-Pi zurück, gleicht er zuerst die Daten vom Bad-Pi ab und übernimmt erst nach 10 s Wartezeit, wenn alles synchron ist.
- Zeit: Beide Pis sind NTP-Server, der Bad-Pi gleicht sich am Koffer-Pi ab. Die Taster holen die Zeit von der VIP.

## Taster

In `src/secrets.h`: `SECRET_WIFI_*` = Koffer-WLAN, `SECRET_WIFI2_*` = Bad-WLAN, `SECRET_PI_IP` = VIP.
Taster ohne Rolle sind im Koffer-WLAN. Mit Rollenzuweisung wechseln sie sofort ins Bad-WLAN, auch wenn es nicht erreichbar ist. Zurück ins Koffer-WLAN gehen sie nur, wenn die Rolle entzogen wird oder der Wettkampf beendet wird.

## Einrichtung (je Pi)

1. `bash deploy/install.sh` (wie bisher).
2. Bridge und WLAN-Zugangspunkt (Beispiel Koffer-Pi, beim Bad-Pi IP `.12`, andere SSID):

```bash
sudo nmcli con add type bridge ifname br0 con-name br0 ipv4.method manual ipv4.addresses 192.168.50.11/24 bridge.stp no
sudo nmcli con add type bridge-slave ifname eth0 master br0
sudo nmcli con add type wifi ifname wlan0 con-name ap ssid KOFFER-SSID mode ap wifi.hidden yes \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk 'PASSWORT' connection.master br0 connection.slave-type bridge
sudo nmcli con up br0
```

3. DHCP: auf beiden Pis `dnsmasq` mit getrennten Bereichen, damit auch bei Ausfall eines Pi Adressen vergeben werden:
   Koffer `dhcp-range=192.168.50.100,192.168.50.149,12h`, Bad `dhcp-range=192.168.50.150,192.168.50.199,12h`, jeweils `interface=br0`.
4. Zwei-Pi-Dienste: `bash deploy/zwei-pi/install-zwei-pi.sh koffer` bzw. `... bad`. Abweichende Adressen über `VIP=`, `KOFFER_IP=`, `BAD_IP=`.
   Der normale Dienst `stoppuhr` wird dabei abgeschaltet; keepalived startet ihn nur auf dem arbeitenden Pi.

## Bekannte Grenzen

- Starten beide Pis gleichzeitig ohne Kabelverbindung, arbeiten kurz beide; nach dem Anstecken des Kabels gewinnt der Koffer-Pi, der Bad-Pi gleicht sich an ihm ab.
- Redis ist nur im internen Netz offen (kein Passwort). Das Netz nicht ans Internet anbinden.
- Der Wechsel dauert wenige Sekunden. Gerade gedrückte Taster senden danach erneut.
- Bitte vor dem Einsatz Ausfall und Rückkehr einmal mit Testdaten durchspielen.
