# Stoppuhr – v0.4.3 (Stable Beta)

Webbasierte Wettkampf-Stoppuhr mit ESP-Tastern und Raspberry-Pi-Backend.

---

## Aktueller Stand (v0.4.3)

✅ Startkarten-Import (manuell geladen)  
✅ Dynamische Bahnanzahl (max aus CSV, Rest inaktiv)  
✅ Drag & Drop Taster-Zuordnung (immer möglich)  
✅ Start / Stopp / Auto-Next-Run  
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
http://<PI-IP>:8000
```

---

## Versionierung

- Produktive Basis: **v0.4.3**
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
