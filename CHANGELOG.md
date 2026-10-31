# Versionsverlauf – Stoppuhr (Pi-Software)

Jede Version ist als Git-Tag `vX.Y.Z` markiert und kann in der Weboberfläche unter
**Einstellungen → Pi-Software** ausgewählt werden (ab `v0.5.1`). Gelistet sind nur Versionen mit eigenem Tag.

| Version | Datum | Änderung |
|---|---|---|
| v0.22.0 | 2026-10-31 | Vitaldaten-Tab: neue Zeile „Online seit“ je Taster (Uhrzeit und Dauer). Eine Lücke von mehr als 30 s startet die Online-Phase neu. |
| v0.21.1 | 2026-10-31 | Oberfläche lädt wieder schnell: Lesende Abfragen (Browser, Taster-Displays) warten nicht mehr auf die globale Zustandssperre; nur schreibende Anfragen und das Weiterschalten des Laufs sperren. |
| v0.21.0 | 2026-10-31 | Vitaldaten bleiben nach „Wettkampf beenden“ erhalten: Die Diagramme zeigen auch Taster, die nicht mehr angemeldet sind (Beschriftung „Taster X (früher)“, der Buchstabe wird je MAC gemerkt). Der Verlauf wird jetzt 48 Stunden gespeichert (vorher 6; Auswahl 12/24/48 h im Vitaldaten-Tab, lange Verläufe werden für die Anzeige ausgedünnt), das Archiv sichert entsprechend mehr. |
| v0.20.0 | 2026-10-31 | **Fehlerbehebung:** Gleichzeitige Tasterdrücke (z. B. Zieleinlauf, mehrere Bahnen) gingen teilweise verloren, obwohl der Taster quittierte: Anfragen luden und speicherten den Zustand gleichzeitig und überschrieben sich. Alle API-Anfragen laufen jetzt nacheinander (Sperre; langsame Routen wie GitHub/Cluster ausgenommen). Ladekoffer-Firmware wie bei den Tastern aus einer Liste der GitHub-Releases wählen (der Pi lädt die Datei selbst); eigener Upload bleibt als Alternative. Koffer-Firmware ab v0.5.0. |
| v0.19.0 | 2026-10-31 | Ladekoffer-Firmware per WLAN aktualisieren: Einstellungen → „Ladekoffer-Firmware“ (`firmware.bin` hochladen). Der Pi liest die Version aus der Datei und bietet sie dem Koffer in der Antwort auf `POST /api/charger` an (`ota`), Download über `GET /api/charger/firmware`. Koffer-Firmware ab v0.4.0. |
| v0.18.0 | 2026-10-31 | Der Ton für gelbe/rote Dashboard-Meldungen kommt jetzt aus dem Pieper des Ladekoffers (Firmware ab v0.3.0, nicht mehr aus dem Browser; das Dashboard muss dafür offen sein). Wettkampf beenden fragt nach einem Namen und legt alles im neuen Tab **Archiv** ab (Ergebnisse, XML, Rohdaten, Vitaldaten; Vitaldaten höchstens die letzten 6 h). Vitaldaten: Zeitfenster lässt sich mit ◀ früher / später ▶ / Jetzt verschieben, auch für archivierte Wettkämpfe. |
| v0.17.0 | 2026-10-31 | Ton im Dashboard: neue gelbe Meldung = kurzer Piepton, anstehende rote Meldung = langer Ton (Standard 2 s, alle 10 s); jeweils einzeln abschaltbar, Länge und Intervall einstellbar. Neue Einstellungen für das Aufwecken der Taster im Ladekoffer (Magnet-Pins je Slot, Impulslänge, Abstand); der Koffer (Firmware ab v0.2.0) holt sie aus der Antwort auf `POST /api/charger`. |
| v0.16.1 | 2026-10-30 | Fehlerbehebung zu v0.16.0: Taster ohne Zuordnung bekamen keine Zuordnungsseite (Buchstabe und Akku) mehr, sondern zeigten „Bahn 0“. |
| v0.16.0 | 2026-10-30 | Funktest (Reichweite): In den Einstellungen Tasterbuchstaben eingeben und „Funktest starten“. Der Taster (Firmware ab v0.15.0) wechselt ins Bad-WLAN, zeigt die Signalstärke in dBm (grün/gelb/rot nach den Grenzwerten „Taster: WLAN-Signal“) und piept bei kritischem Signal. Tastendrücke dieses Tasters werden währenddessen ignoriert. |
| v0.15.0 | 2026-10-30 | Neue Einstellungen für die Taster-Akkuwarnung: „Akku-Warnung ab (%)“ (Standard 10, 0 = aus) und „automatisch ausschalten nach (Minuten)“ (Standard 5, 0 = nie). Die Werte gehen über `/api/display` an die Taster (Firmware ab v0.14.0). |
| v0.14.2 | 2026-10-30 | „Starter ist auch Zieleinlauf“ als Kontrollkästchen direkt unter der Starter-Zeile auf der Startseite (wirkt sofort, ohne Speichern). |
| v0.14.1 | 2026-10-30 | Fix: Syntaxfehler in `app.js` aus v0.14.0 (Oberfläche blieb leer, keine Versionsanzeige). |
| v0.14.0 | 2026-10-30 | Neu: einstellbarer Grenzwert „Zieleinlauf: Abweichung zur Bahnzeit“ (Einstellungen → Grenzwerte, Standard gelb ab 0,5 s, rot ab 1 s, je ±). Neu: Option „Starter / Zieleinlauf“ (Einstellungen): der Starter-Taster behält die Starteransicht, sammelt aber nach dem Start jeden weiteren Druck als Zieleinlauf-Zeit (der Doppeldruck-Stopp entfällt dann). |
| v0.13.4 | 2026-10-30 | Zieleinlauf-Übertragen legt bei jedem Klick eine **neue** Unterversion an (5/2, 5/3, …). Bahnen ohne zugeordnete Zieleinlauf-Zeit übernehmen ihre normal gestoppte Zeit. „Letzte Version zurücknehmen“ entfernt die jeweils neueste. |
| v0.13.3 | 2026-10-30 | Zieleinlauf dynamischer: zugeordnete Zeiten (auch automatisch vorsortierte) lassen sich per Drag & Drop auf andere Bahnen ziehen oder in den Bereich „Geparkte Zeiten“ zurückziehen („✕“ parkt ebenfalls). Eine überschriebene Zeit wandert in den Parkplatz. Geparkte Zeiten werden nicht automatisch zugeordnet. |
| v0.13.2 | 2026-10-30 | Zieleinlauf: schnelle Druckfolge möglich (Entprellung 50 ms). Zugeordnete Zeiten dienen nur dem Vergleich; der Button unter der Tabelle überträgt alle zugeordneten Zeiten als neue Laufversion (z. B. 5/2) an JAuswertung, erneutes Übertragen aktualisiert sie, „Version zurücknehmen“ entfernt sie. Neu: `POST /api/finish/transfer`. |
| v0.13.1 | 2026-10-30 | Anzeige für den Zieleinlauf-Taster (`role: "finish"` mit Liste in `/api/display`). |
| v0.13.0 | 2026-10-30 | Neue Rolle **Zieleinlauf**: ein Taster (Drag & Drop wie der Starter) sammelt jeden Anschlag. Die Zeiten werden automatisch den Bahnzeiten zugeordnet (Abweichung in der Spalte „Zieleinlauf“), nicht passende per Drag & Drop auf eine Bahn ziehen; hat die Bahn keine Zeit, wird die Zieleinlauf-Zeit übernommen. Die Bahnzeit bleibt die Hauptzeit. Zweiter Druck des Starters bei laufender Uhr beendet den Lauf (mit Hinweis). Neu: `POST /api/finish/assign`, Modul `backend/finish.py`. |
| v0.12.6 | 2026-10-30 | Taster-Seite: Der als Starter zugewiesene Taster zeigt „STARTER (aktiv)“ statt „–“. |
| v0.12.5 | 2026-10-30 | Einstellungen: Neue Karte „Grenzwerte“. Die gelben und roten Schwellwerte für Taster, Pis und Ladekoffer (Akku, Spannung, Temperatur, Luftfeuchte, WLAN, CPU, Speicher, SD-Karte) sind einstellbar und lassen sich auf Standardwerte zurücksetzen. Neu: `GET/POST /api/limits`, Modul `backend/limits.py`. |
| v0.12.4 | 2026-10-30 | Oberfläche: Auf der Seite Stoppuhr werden Taster-Karten, Starter und Bahnen gelb oder rot hinterlegt, wenn ein Wert den Grenzwert erreicht oder ein Taster mit Rolle offline ist. Die einzelnen Werte sind ebenfalls farbig. |
| v0.12.3 | 2026-10-30 | Oberfläche: Roter Balken oben, wenn ein Taster mit Rolle (Starter oder Bahn) offline ist. Taster ohne Rolle lösen keine Meldung aus. |
| v0.12.2 | 2026-10-30 | Oberfläche: Rote bzw. gelbe Balken oben auch für Taster, Pis und Messwerte des Ladekoffers (Akku, Spannung, Temperatur, Luftfeuchte, WLAN, CPU, Speicher, SD-Karte, Pi nicht erreichbar). In der Übersicht „Zustand“ werden Werte über bzw. unter den Grenzwerten gelb oder rot. Grenzwerte stehen in `LIMITS` in `backend/static/app.js`. |
| v0.12.1 | 2026-10-30 | Repositories heißen jetzt `Stoppuhr-2.0-Stoppuhr`, `Stoppuhr-2.0-Taster` und `Stoppuhr-2.0-Ladekoffer`. Standard für `FIRMWARE_REPO` und die Klon-Adressen in der Doku angepasst. |
| v0.12.0 | 2026-10-30 | Ladekoffer-Anbindung: Neue Schnittstellen `POST /api/charger` (offen, für die Ladeplatine) und `GET /api/charger`. Statusmeldungen (Fehler, Übertemperatur, fehlende oder ladende Taster, offline) in Kopfzeile, Meldungsleiste und Tab „Vitaldaten“. Neues Modul `ladekoffer.py` mit Tests. |
| v0.11.3 | 2026-10-30 | Zwei-Pi-WLAN: Die Taster-Zugangspunkte sind fest auf 2,4 GHz eingestellt (Koffer Kanal 1, Bad Kanal 11). Neues Skript `wlan-kanal-setzen.sh` stellt auch vorhandene Installationen um; Kanäle 1, 6 oder 11 sind wählbar. Außerdem Syntaxfehler im Zwei-Pi-Installer behoben. |
| v0.11.2 | 2026-10-29 | Vitaldaten: CPU-Temperatur und CPU-Last der Pis stehen gemeinsam in einem Diagramm (Temperatur durchgezogen, Last gestrichelt, Skala 0–100). |
| v0.11.1 | 2026-10-29 | Vitaldaten: Das Diagramm „Pi CPU-Last“ entfällt. Es bleibt ein Pi-Diagramm (CPU-Temperatur, beide Pis), die Box „Zustand“ läuft über die volle Breite. |
| v0.11.0 | 2026-10-29 | Vitaldaten: Die Pis erscheinen im Vitaldaten-Tab. Neue Diagramme „Pi CPU-Temperatur“ und „Pi CPU-Last“ (je Pi eine Linie, Verlauf wie bei den Tastern), und die Box „Zustand der Taster und Pis“ zeigt zusätzlich Status, CPU, Speicher, SD-Karte und Laufzeit beider Pis. Neu: `/api/vitals/pi`. |
| v0.10.1 | 2026-10-29 | Vitaldaten: Box „Zustand der Taster“ steht unten rechts (hinter den fünf Diagrammen). |
| v0.10.0 | 2026-10-29 | Vitaldaten: Box „Zustand der Taster“ (Tabelle: Taster nebeneinander nach Buchstabe, darunter Status online/offline und aktuelle Werte). `/api/taster` liefert zusätzlich die Vitaldaten. |
| v0.9.9 | 2026-10-29 | Ausfallübernahme: Nach getrenntem Kabel behält der Pi mit den neueren Daten seinen Bestand, der andere gleicht sich daran an. Vorher überschrieb der zurückkehrende Koffer-Pi die Läufe des Bad-Pi. |
| v0.9.8 | 2026-10-29 | Ausfallübernahme: Zeitlimit des Prüfskripts auf 1 s (unter dem keepalived-Intervall), sonst übersprang keepalived die Prüfung und der Bad-Pi übernahm nicht. |
| v0.9.7 | 2026-10-29 | Ausfallübernahme: Stehen beide Pis als Redis-Kopie voneinander, wird der Koffer-Pi Hauptbestand (vorher übernahm keiner). |
| v0.9.6 | 2026-10-29 | Ausfallübernahme: Das Prüfskript hängt nicht mehr, wenn der Partner-Pi ausfällt (Zeitlimit für die Redis-Abfrage). Vorher übernahm der Bad-Pi bei gezogenem Kabel des Koffer-Pi nicht. |
| v0.9.5 | 2026-10-29 | Aktiver Pi wird erkannt, auch wenn die gemeinsame Adresse die zweite Adresse einer Schnittstelle ist („Aktiver Pi unbekannt“). Zwei-Pi-Skript entfernt die alte dnsmasq-Konfiguration des Einzelbetriebs. |
| v0.9.4 | 2026-10-29 | Zwei-Pi-Netz: `eth0` bleibt per DHCP am Router (Namen `stoppuhr-koffer.local`/`stoppuhr-bad.local`), das Taster-Netz verbindet die Pis über einen VXLAN-Tunnel und ist vom Internet abgeschottet. |
| v0.9.3 | 2026-10-29 | Vitaldaten: zusätzlich Zeitraum „letzte 15 Minuten“ und „letzte 30 Minuten“. |
| v0.9.2 | 2026-10-29 | Vitaldaten: senkrechte gestrichelte Linien mit „L<Nr>“ bei jedem Laufstart (Redis `RUN_STARTS`, die letzten 200 Starts). |
| v0.9.1 | 2026-10-29 | Vitaldaten: alle Taster in einem Diagramm je Messwert, jeder Taster in eigener Farbe. |
| v0.9.0 | 2026-10-29 | Neuer Tab „Vitaldaten“: Diagramme für Akku, Akkuspannung, Temperatur, Luftfeuchte und WLAN-Stärke je Taster (letzte 6 Stunden, in Redis gespeichert). |
| v0.8.0 | 2026-10-29 | Anmeldung (Benutzer und Kennwort) für die Oberfläche. WLAN-Namen und -Kennwörter in den Einstellungen ändern und an die Taster verteilen; danach stellen die Pis ihren Zugangspunkt um. Installer richtet Bridge und Zugangspunkt ein. |
| v0.7.2 | 2026-10-28 | Gemeinsamer Name `stoppuhr` (dnsmasq) im Zwei-Pi-Betrieb, gleiche Software auf beiden Pis, Rolle in `/etc/stoppuhr-zwei-pi.env`. |
| v0.7.1 | 2026-10-28 | Pi-Software per Dropdown auf eine Git-Version wechseln. |
| v0.7.0 | 2026-10-28 | Taster-Firmware aus GitHub-Releases wählen und per Pi auf die Taster laden (OTA). |
| v0.6.3 | 2026-10-28 | Laufstatus alle 250 ms abfragen (schnellere Anzeige). |
| v0.6.2 | 2026-10-28 | Taster tauschen über „Bereitschaft“ beim ersten Tastendruck. |
| v0.6.1 | 2026-10-28 | Zwei-Pi: Cluster-Status in der Oberfläche, Rollenwechsel-Protokoll, Testplan. |
| v0.6.0 | 2026-10-28 | Zwei-Pi-Betrieb: Ausfallübernahme (keepalived), Redis-Kopie. |
| v0.5.1 | 2026-10-28 | Abbruch und Wiederholung von Läufen, Wettkampf beenden, Umlaute, Installation ohne Docker. |
| v0.4.3 | 2025-12-23 | Docker, Redis-Zustand, API für Trigger, Vitaldaten, Läufe. |
| v0.4.2 | 2025-12-22 | Erste Weboberfläche. |
| v0.4.1 | 2025-12-17 | Stabile Ausgangsversion. |

Die Firmware der Taster hat einen eigenen Verlauf im Repository `Taster` (`CHANGELOG.md`).
Welche Firmware zu welcher Pi-Version passt, steht dort in der Spalte „Pi“.
