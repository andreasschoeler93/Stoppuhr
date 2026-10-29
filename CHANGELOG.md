# Versionsverlauf – Stoppuhr (Pi-Software)

Jede Version ist als Git-Tag `vX.Y.Z` markiert und kann in der Weboberfläche unter
**Einstellungen → Pi-Software** ausgewählt werden (ab `v0.5.1`). Gelistet sind nur Versionen mit eigenem Tag.

| Version | Datum | Änderung |
|---|---|---|
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
