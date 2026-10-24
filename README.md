<div align="center">

# 🤖 Robot Companion — v1.0.0

**AI-Powered Physical Desktop Companion Robot for Raspberry Pi 3 B+ & SPI Display**  
*Asistent fizic inteligent de birou pentru Raspberry Pi 3 B+ și ecran SPI în mod Kiosk*

[![Release](https://img.shields.io/badge/version-1.0.0-brightgreen.svg)](./VERSION)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi%203%20B%2B-C51A4A.svg?logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/)
[![AI](https://img.shields.io/badge/AI-Google%20Gemini%203.5%20Flash-4285F4.svg?logo=google&logoColor=white)](https://ai.google.dev/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

[**🇬🇧 English**](#-english-overview) • [**🚀 Installation (EN)**](#-quick-installation-raspberry-pi-os) • [**🇷🇴 Română**](#-prezentare-în-română) • [**🛠️ Instalare (RO)**](#-instalare-pas-cu-pas-pe-raspberry-pi) • [**🔍 Diagnostics**](#-diagnostics--testing-tools)

</div>

---

## 🇬🇧 English Overview

**Robot Companion** is a modular, low-memory AI desktop assistant engineered for the **Raspberry Pi 3 Model B+ (1 GB RAM)** equipped with a small **SPI display** (fullscreen Kiosk mode), a USB microphone (webcam mic), and 3.5mm jack speakers.

### ✨ Key Features
* **🧠 Streaming AI Brain (`brain/ai_brain.py`):** Real-time responses powered by `gemini-3.5-flash` with an automatic multi-model fallback chain (`gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`), short-term memory, and offline degraded mode.
* **🗣️ Neural Voice & Barge-In (`voice/speak.py`):** Natural Romanian (`ro-RO-EmilNeural`) and English (`en-US-ChristopherNeural`) TTS synthesized in RAM (`/dev/shm`), featuring a phonetic dictionary (`pronuntie_ro.json`) and instant **Barge-In** interruption.
* **👂 Multi-Strategy Wake Word (`ears/wake_word.py`):** Hands-free activation on **"Robot"** using an automatic fallback chain:
  1. `vosk_phonetic`: Offline 16 kHz Vosk recognizer with a stateful DSP pipeline (`_StreamDSP16k`: DC-offset removal + 100 Hz High-Pass filter + AGC + upsampling) and fuzzy matching.
  2. `openwakeword`: Neural wake-word fallback (if installed).
  3. `energy_vad_stt`: Acoustic RMS Voice Activity Detection + short STT verification.
  * Includes self-trigger suppression during robot speech and an on-screen **Push-to-Talk (`🎤 MIC`)** button.
* **🎬 YouTube Music & SPI Video Player (`brain/abilities/youtube_player.py`):**
  * **Music:** Audio-only stream (`bestaudio`) with cover art, queue counter, prefetching, and instant control (`Play/Pause`, `Seek ±10s`, `Next/Prev`, `Vol -/+`) via an `mpv` UNIX IPC socket (`/tmp/robot_mpv_ipc.sock`).
  * **SPI Video:** Decodes 360p video via `ffmpeg` directly into the Tkinter `Canvas` (`12 fps`) while playing audio through `mpv`, ensuring smooth playback on any SPI display without hiding UI buttons.
* **📚 Interactive Wikipedia, Weather, Timers & Health Monitor:** Romanian/English Wikipedia cards with pagination (`MAI MULT ▶`), 5-day Open-Meteo forecast (`weather.py`), voice timers (`timers.py`), Do-Not-Disturb (`DND`) mode, and real-time CPU temp / RAM / 5V undervoltage monitoring (`system_health.py`).

### 🖥️ Hardware & Architecture
* **Target Hardware:** Raspberry Pi 3 Model B+ (1 GB RAM), SPI Display (`DISPLAY=:0`), USB Microphone (`8000 Hz` / `16000 Hz`), 3.5mm Speakers, 5V/2.5A PSU.
* **Structure:** `main.py` (Adaptive Kiosk UI & `RobotState`), `config.py` / `config.json` (Settings), `brain/` (Gemini AI & Abilities), `ears/` (Mic Lock, DSP & Wake Word), `voice/` (Edge-TTS), `tools/` (Audit & Diagnostics).

### 🚀 Quick Installation (Raspberry Pi OS)
```bash
# 1. Clone repo & install Linux system dependencies
cd ~
git clone https://github.com/alexdeliu/Robot-Companion.git
cd Robot-Companion
sudo apt-get update
sudo apt-get install -y mpv ffmpeg mpg123 alsa-utils portaudio19-dev libjpeg-dev zlib1g-dev \
    python3-venv python3-dev python3-pil.imagetk dos2unix

# 2. Create virtual environment & install Python packages
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -U -r requirements.txt
pip install -U yt-dlp

# 3. Configure local API keys (.env is git-ignored)
cp .env.example .env
nano .env   # Add GEMINI_API_KEY=your_key_here

# 4. Run release check & enable auto-start Kiosk systemd service
python tools/release_check.py
sudo cp robot-companion.service /etc/systemd/system/robot-companion.service
sudo systemctl daemon-reload
sudo systemctl enable robot-companion.service
sudo systemctl start robot-companion.service
```

---

## 🇷🇴 Prezentare în Română

**Robot Companion** este un asistent fizic cu inteligență artificială, proiectat și optimizat pentru **Raspberry Pi 3 Model B+ (1 GB RAM)**, cu afișaj pe **ecran SPI** în mod Kiosk (fullscreen), microfon USB și boxe pe mufa jack de 3.5mm.

### ✨ Funcționalități Principale
* **🧠 Creier AI cu Streaming (`brain/ai_brain.py`):** Răspunsuri în timp real cu `gemini-3.5-flash`, lanț automat de modele de rezervă, memorie conversațională și mod degradat offline.
* **🗣️ Voce Neurală în Română & Barge-In (`voice/speak.py`):** Sinteză vocală `ro-RO-EmilNeural` generată în RAM (`/dev/shm`), dicționar fonetic pentru termenii tehnici din engleză (`voice/pronuntie_ro.json`), volum logaritmic ALSA (`amixer -M`) și întrerupere instantanee (**Barge-In**).
* **👂 Wake Word Hands-Free „Robot” (`ears/wake_word.py`):**
  * Lanț cu 3 strategii și fallback automat (`vosk_phonetic` cu filtru continuu High-Pass 100 Hz + AGC + potrivire fuzzy → `openwakeword` → `energy_vad_stt`).
  * Previne auto-declanșarea cât timp robotul vorbește și oferă butonul **Push-to-Talk (`🎤 MIC`)** activ în orice stare.
* **🎬 YouTube Music & Video pe Ecranul SPI (`brain/abilities/youtube_player.py`):**
  * **Muzică:** Redare `bestaudio` prin `mpv` controlat instantaneu prin socket UNIX IPC (`/tmp/robot_mpv_ipc.sock`) pentru Pauză, Derulare ±10s, Piesa Următoare/Anterioară și Volum.
  * **Video pe SPI:** Decodează fluxul video 360p cu `ffmpeg` direct în `Canvas`-ul Tkinter la rezoluția ecranului SPI (`12 fps`) în timp ce sunetul rulează prin `mpv`, păstrând toate butoanele vizibile.
* **📚 Wikipedia, Meteo, Cronometre & Sănătate Sistem:** Carduri Wikipedia cu imagine și paginare (*„Spune-mi mai mult”* / `MAI MULT ▶`), prognoză meteo pe 5 zile (`weather.py`), cronometre vocale (`timers.py`), mod **Nu Deranja (`DND`)** și monitorizare temperatură CPU, RAM și alimentare 5V (`vcgencmd get_throttled`).

### 🎙️ Exemple de Comenzi Vocale
| Categorie | Exemple de comenzi (după ce spui **„Robot!”** sau apeși **`🎤 MIC`**) |
| :--- | :--- |
| **Conversație & Glume** | *„Salut! Cum te simți azi?”*, *„Spune-mi o glumă scurtă.”* |
| **Vremea (One-Shot)** | *„Cum e vremea în Timișoara?”*, *„Plouă mâine la Cluj?”* |
| **Wikipedia (Paginat)** | *„Caută pe Wikipedia despre Mihai Eminescu”* → *„Spune-mi mai mult”* |
| **YouTube Music** | *„Pune o melodie rock”*, *„Următoarea melodie”*, *„Dă mai tare”*, *„Oprește muzica”* |
| **YouTube Video** | *„Caută pe YouTube documentare natură”* → *„Primul”* / *„Al doilea”* |
| **Timere & Sistem** | *„Pune un timer de 2 minute”*, *„Cât e ceasul?”*, *„Status sistem”*, *„Ce versiune ești?”* |

### 🛠️ Instalare Pas cu Pas pe Raspberry Pi
```bash
# 1. Clonare proiect și instalare pachete Linux și utilitare media
cd ~
git clone https://github.com/alexdeliu/Robot-Companion.git
cd Robot-Companion
sudo apt-get update
sudo apt-get install -y mpv ffmpeg mpg123 alsa-utils portaudio19-dev libjpeg-dev zlib1g-dev \
    python3-venv python3-dev python3-pil.imagetk dos2unix

# 2. Creare mediu virtual Python și instalare dependențe
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -U -r requirements.txt
pip install -U yt-dlp

# 3. Configurare cheie API în .env (fișier local ignorat de Git)
cp .env.example .env
nano .env   # Completează GEMINI_API_KEY=cheia_ta_reala

# 4. Audit de verificare și pornire serviciu systemd (auto-start Kiosk la boot)
python tools/release_check.py
sudo cp robot-companion.service /etc/systemd/system/robot-companion.service
sudo systemctl daemon-reload
sudo systemctl enable robot-companion.service
sudo systemctl start robot-companion.service
```

---

## 🔍 Diagnostics & Testing Tools (`tools/*`)

| Command / Comandă | Purpose / Rol |
| :--- | :--- |
| `python tools/release_check.py` | Verifies all required files, Python syntax, indentation, config keys, and scans for leaked secrets. |
| `DISPLAY=:0 python tools/ui_selftest.py` | Measures all UI buttons across all 6 screens/overlays to ensure zero text clipping on SPI displays. |
| `DISPLAY=:0 python tools/diag_youtube.py` | Tests YouTube search, `yt-dlp` format extraction, `mpv` audio, and `ffmpeg` SPI frame decoding. |
| `python diag_mic.py` | Lists audio devices, tests supported hardware sample rates, measures live RMS, and tests Wake Word. |
| `python tools/wake_eval.py /tmp` | Benchmarks recorded `.wav` files against Vosk and STT strategies, reporting accuracy and latency. |

## 📄 License / Licență
Distributed under the **MIT License**. Copyright (c) 2026 **Deliu Alexandru-Darius**. See [`LICENSE`](./LICENSE) for details.