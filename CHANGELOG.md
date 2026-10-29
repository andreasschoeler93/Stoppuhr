# Versionsverlauf – Stoppuhr (Pi-Software)

Jede Version ist als Git-Tag `vX.Y.Z` markiert und kann in der Weboberfläche unter
**Einstellungen → Pi-Software** ausgewählt werden (ab `v0.5.1`). Gelistet sind nur Versionen mit eigenem Tag.

| Version | Datum | Änderung |
|---|---|---|
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
