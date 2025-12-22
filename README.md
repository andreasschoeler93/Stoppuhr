# Stoppuhr – Raspberry‑Pi‑basierte Wettkampf‑Stoppuhr

## Projektstatus
Aktuelle stabile Version: **v0.4.2**

Dieses Projekt stellt eine robuste, netzwerkfähige Stoppuhr für Wettkämpfe dar.
Schwerpunkt liegt auf **Ausfallsicherheit**, **klarer Bedienung** und
**nachträglicher Korrigierbarkeit**.

---

## 🛣️ Roadmap & Entwicklungsstand

### ✅ Erledigt (v0.4.2 – stabile Basis)

- [x] Flask-Webserver lauffähig auf Raspberry Pi
- [x] Weboberfläche mit Tabs (Stoppuhr / Einstellungen / Status)
- [x] Startkarten-Import (CSV)
- [x] Dynamische Ermittlung der maximalen Bahnen  
- [x] Bahnen ohne Starter automatisch **inaktiv**
- [x] Läufe werden über Spalte **„Lauf“** erkannt
- [x] Kein automatischer Reload der Startkarten
- [x] GitHub-Repository eingerichtet
- [x] Versionierung v0.4.x

---

### 🚧 In Arbeit / Ziel v0.4.3

- [ ] Übersicht aller Läufe mit Status
- [ ] Persistenter Zustand nach Pi-Neustart
- [ ] Vorbereitung möglich bei unvollständigen Bahnen
- [ ] Alte Taster-Zuordnungen übernehmen
- [ ] UI-Statusverbesserungen

---

### 🧪 Geplant v0.4.4 – Backup‑Zieleinlauf

- [ ] Zweiter Zieleinlauf als Backup
- [ ] Vergleich Bahnzeit ↔ Zieleinlauf
- [ ] Farbige Differenzanzeige (ok / warn / kritisch)
- [ ] Einstellbare Schwellwerte
- [ ] Manuelle Übernahme bei Fehlern

---

### 🧲 Geplant v0.4.5 – Historie & Nachkorrektur

- [ ] Drag & Drop Zuordnung von Backup-Zeiten
- [ ] Rücksetz- & Bestätigungsfunktion
- [ ] Historienansicht alter Läufe
- [ ] Nachträgliche Korrekturen

---

### 🔐 Robustheit (Modell A)

- [ ] Lokale Zeitstempel
- [ ] Taster puffern Events
- [ ] Kein Datenverlust bei Neustart
- [ ] Wettkampf immer abschließbar

---

## Entwicklungsprinzipien

- Jede Version lauffähig
- Kleine, getestete Schritte
- Erst Robustheit, dann Komfort
