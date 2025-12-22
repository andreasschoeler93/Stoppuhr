# Stoppuhr – Raspberry-Pi Webserver (v0.4.2)

Webbasierte Wettkampf-Stoppuhr für DLRG-Schwimmwettkämpfe  
mit ESP-Tastern, Raspberry Pi und externer Auswertungssoftware.

---

## 🔢 Version

**v0.4.2 – stabile Basis**

- Dynamische Ermittlung der maximalen Bahnen aus den Startkarten
- Anzeige aller Bahnen `1 … max(Bahn)`
- Bahnen ohne Starter werden automatisch als **inaktiv** markiert
- Läufe werden über die Spalte **„Lauf“** aus den Startkarten erkannt
- Stabile GitHub-Basis zum Weiterentwickeln (v0.4.3+)

---

## 🧩 Projektübersicht

**Bestandteile**

- Raspberry Pi (Zentrale)
- Weboberfläche (Flask + HTML/JS)
- ESP-Taster (Start / Bahn / Zieleinlauf)
- Externe Auswertungssoftware (liefert Startkarten als CSV)

**Grundidee**

- Die Stoppuhr arbeitet **zeitstempelbasiert**
- Der Pi ist führend für Anzeige, Zuordnung und Export
- Taster funktionieren robust auch bei temporären Verbindungsproblemen

---

## 🌐 Weboberfläche

Standard-Adresse:

http:/IP-IP/:8000



### Tabs

- **Stoppuhr**
  - Lauf auswählen
  - Start / Abbruch
  - Bahnzeiten live
- **Einstellungen**
  - Startkarten-Pfad konfigurieren
- **Systemstatus**
  - System- & Netzwerkdiagnose

---

## 🏁 Startkarten (CSV)

Die Startkarten kommen aus der Auswertungssoftware.

### Erwartete Spalten

Mindestens erforderlich:

- `Lauf`
- `Bahn`

Optional (Anzeige):

- Name
- Startnummer
- Disziplin
- Altersklasse
- Geschlecht
- Gliederung

### Verhalten

- Höchste gefundene **Bahn-Nummer = maximale Bahnanzahl**
- Bahnen ohne Starter → **inaktiv**
- Keine automatische Neuladung  
  → Startkarten werden **nur manuell** aktualisiert

---

## ⚙️ Installation (Kurzfassung)

```bash
cd /home/dlrg/stoppuhr
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt


Start:
python app.py

Oder über systemd:
sudo systemctl restart stoppuhr


🛣️ Roadmap & Entwicklungsstand
✅ Erledigt (v0.4.2 – stabile Basis)

 Flask-Webserver lauffähig auf Raspberry Pi

 Weboberfläche mit Tabs (Stoppuhr / Einstellungen / Status)

 Startkarten-Import (CSV)

 Dynamische Ermittlung der maximalen Bahnen
→ höchste vorkommende Bahnnummer

 Bahnen ohne Starter werden automatisch als inaktiv markiert

 Läufe werden über Spalte „Lauf“ erkannt

 Kein automatischer Reload der Startkarten (nur manuell)

 GitHub-Repository eingerichtet

 Versionierung (v0.4.x)

🚧 In Arbeit / Ziel v0.4.3 (nächster Meilenstein)

Ziel: Funktionale Wettkampf-Durchführung ohne Server-Neustart-Probleme

 Übersicht aller Läufe (Laufnummer + Status)

 abgeschlossen (alle Bahnen gestoppt)

 unterbrochen (fehlende Zeiten)

 Persistenter Zustand:

 laufende Läufe werden nach Pi-Neustart wieder geladen

 Startkarten werden nur einmal gelesen

 erneutes Laden nur per Button

 Vorbereitung möglich, auch wenn:

 noch nicht alle Bahnen belegt sind

 Drag & Drop trotzdem erlaubt

 Alte Taster-Zuordnungen bleiben erhalten

 UI-Verbesserungen:

 klare Statusanzeige pro Bahn

 verständliche Fehlermeldungen

🧪 Geplant v0.4.4 (Backup-Zieleinlauf)

Ziel: Absicherung bei Bedienfehlern („Taster pennt“)

 Zweiter Zieleinlauf als Backup-Zeitquelle

 Vergleich:

 Bahnzeit vs. Zieleinlaufzeit

 Anzeige der Differenz

 Farbige Kennzeichnung der Differenz:

 normal (schwarz)

 Warnung (gelb)

 kritisch (rot)

 Schwellwerte einstellbar (Einstellungen)

 Wenn Bahnzeit fehlt:

 Zieleinlaufzeit als Ersatz vorschlagen

 Manuelle Entscheidung:

 Übernahme bestätigen

🧲 Geplant v0.4.5 (Nachkorrektur & Historie)

 Drag & Drop:

 Zieleinlauf-Zeiten manuell Bahnen zuordnen

 Rücksetzen möglich

 Übernahme nur nach Bestätigung

 Historien-Seite:

 alte Läufe per Dropdown auswählbar

 gleiche Ansicht wie Live-Lauf

 nachträgliche Korrektur erlaubt

🔐 Robustheit & Sicherheit (Modell A – bestätigt)

 Zeitstempel immer lokal sichern

 Taster speichern Events selbst zwischen

 Pi arbeitet nur mit Zeitstempeln

 Kein Datenverlust bei Neustart

 Ziel: Wettkampf kann immer zu Ende geführt werden

🧱 Langfristig (optional)

 Export an Auswertungssoftware

 Benutzerrollen (Anzeige / Admin)

 Mehrere Wettkämpfe parallel

 Offline-Archiv

🧠 Entwicklungsprinzipien

Kleine Schritte

Jede Version lauffähig

Kein Feature ohne stabile Basis

Erst Robustheit, dann Komfort
