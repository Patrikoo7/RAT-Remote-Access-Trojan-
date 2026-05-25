# 🐀 RAT — Remote Access Tool
> Progetto scolastico · Sicurezza Informatica · Python 3

![edu](https://img.shields.io/badge/scopo-educativo-red) ![python](https://img.shields.io/badge/Python-3.x-blue) ![status](https://img.shields.io/badge/status-stable-green)

Implementazione didattica di un **Remote Access Tool** in Python. Due moduli comunicanti via rete locale o internet, sviluppati per esplorare concetti fondamentali di networking, architettura client/server e sicurezza informatica.

---

## 📦 Componenti

| File | Ruolo |
|------|-------|
| `server.py` | Pannello di controllo con interfaccia grafica. Gestisce le connessioni e invia comandi al client remoto. |
| `client.py` | Agente eseguito sul dispositivo remoto. Riceve ed esegue i comandi, trasmette i dati al server. |

---

## ⚡ Funzionalità

- 🖥️ **Live screen streaming** — visualizzazione del desktop remoto in tempo reale
- 💻 **Terminale remoto** — esecuzione di comandi di sistema via shell
- ⌨️ **Keylogger** — monitoraggio degli input da tastiera del client
- 📷 **Webcam** — accesso alla videocamera del dispositivo remoto
- 🎙️ **Audio streaming** — ascolto del microfono in tempo reale
- 🎨 **GUI custom** — interfaccia grafica realizzata in Python

---

## 🗂️ Struttura
rat-project/
├── server.py    # pannello di controllo + GUI
├── client.py    # agente remoto
└── README.md

---

## 🛠️ Tecnologie utilizzate

`Python 3` · `socket` · `threading` · `tkinter` · `opencv` · `Pillow` · `pyaudio` · `pynput`

---

## 📚 Concetti esplorati

- **Networking** — socket TCP/IP, protocolli, gestione latenza
- **Architettura client/server** — design pattern, serializzazione, heartbeat
- **Processi remoti** — subprocess, threading, I/O stream
- **Sicurezza informatica** — vettori di attacco, difesa, etica nell'hacking

---

## ⚠️ Avviso legale ed etico

> Questo strumento è stato sviluppato **esclusivamente per fini didattici e scolastici**.
> L'installazione su dispositivi altrui senza consenso esplicito costituisce una violazione della privacy
> e può essere perseguita penalmente ai sensi del **D.Lgs. 196/2003** e dell'**art. 615-ter c.p.**
>
> **Usare solo in ambienti controllati e con il permesso esplicito del proprietario.**
