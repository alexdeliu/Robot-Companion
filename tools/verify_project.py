import os
import sys
import json
import shutil
import platform
import py_compile
import subprocess
import importlib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

FISIERE_OBLIGATORII = [
    "main.py",
    "config.py",
    "config.json",
    "system_health.py",
    "diag_mic.py",
    "requirements.txt",
    "robot-companion.service",
    ".gitignore",
    ".gitattributes",
    "voice/speak.py",
    "voice/pronuntie_ro.json",
    "ears/listen.py",
    "ears/wake_word.py",
    "brain/ai_brain.py",
    "brain/mock_brain.py",
    "brain/abilities/weather.py",
    "brain/abilities/wikipedia_ro.py",
    "brain/abilities/youtube_player.py",
    "brain/abilities/timers.py",
]

CHEI_CONFIG_OBLIGATORII = {
    "ai": ["model_principal", "modele_rezerva", "timeout_ms", "temperatura", "max_istoric"],
    "audio_out": ["tts_voice_ro", "tts_voice_en", "tts_rate", "volum_normal", "volum_ducking"],
    "microphone": [
        "sample_rate", "chunk_size", "auto_gain_alsa_percent", "highpass_cutoff_hz",
        "target_rms", "max_dsp_gain", "ambient_multiplier", "min_energy_threshold",
        "max_energy_threshold", "pause_threshold", "phrase_time_limit", "listen_timeout"
    ],
    "wake_word": [
        "enabled_by_default", "preferred_strategy", "strategies_order",
        "sensitivity_rms_ratio", "min_trigger_rms", "fuzzy_threshold",
        "ignore_after_speak_sec", "vosk_gain", "custom_triggers"
    ],
    "youtube": ["max_video_height", "max_video_fps", "search_timeout_sec", "ytdlp_timeout_sec", "cache_ttl_sec"],
    "ui": ["debounce_ms", "clock_refresh_ms", "health_refresh_ms"]
}

DEPENDENTE_EXTERNE = [
    ("dotenv", "python-dotenv"),
    ("google.genai", "google-genai"),
    ("edge_tts", "edge-tts"),
    ("speech_recognition", "SpeechRecognition"),
    ("pyaudio", "PyAudio"),
    ("PIL", "pillow"),
    ("vosk", "vosk"),
    ("yt_dlp", "yt-dlp"),
]


def ruleaza_verificare():
    erori = []
    avertismente = []
    ok_list = []

    print("=" * 68)
    print("   VERIFICARE AUTOMATĂ PROIECT - ROBOT COMPANION (PC & PI)")
    print("=" * 68)
    print(f"Folder proiect : {BASE_DIR}")
    print(f"Sistem / Python: {platform.system()} {platform.machine()} | Python {sys.version.split()[0]}\n")

    # 1. Verificare existență fișiere (și detecție .service.txt)
    svc_txt = os.path.join(BASE_DIR, "robot-companion.service.txt")
    svc_clean = os.path.join(BASE_DIR, "robot-companion.service")
    if os.path.exists(svc_txt) and not os.path.exists(svc_clean):
        try:
            shutil.copyfile(svc_txt, svc_clean)
            avertismente.append("Am găsit 'robot-companion.service.txt' și l-am copiat automat ca 'robot-companion.service'.")
        except Exception as e:
            erori.append(f"Nu am putut copia robot-companion.service.txt -> robot-companion.service: {e}")

    for rel_path in FISIERE_OBLIGATORII:
        full_p = os.path.join(BASE_DIR, rel_path)
        if not os.path.exists(full_p):
            erori.append(f"Fișier lipsă: {rel_path}")
        elif os.path.getsize(full_p) == 0:
            erori.append(f"Fișier gol (0 bytes): {rel_path}")
        else:
            ok_list.append(f"Fișier prezent: {rel_path}")

    # 2. Compilare statică (py_compile) pe toate fișierele .py
    py_files = []
    for radacina, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in ("venv", ".venv", "__pycache__", ".git", "logs")]
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(radacina, f))

    compile_ok = True
    for py_f in sorted(py_files):
        rel_py = os.path.relpath(py_f, BASE_DIR)
        try:
            py_compile.compile(py_f, doraise=True)
        except Exception as e:
            compile_ok = False
            erori.append(f"Eroare de sintaxă/indentare în {rel_py}: {e}")
    if compile_ok:
        ok_list.append(f"Toate cele {len(py_files)} fișiere Python au trecut testul py_compile (0 erori de sintaxă).")

    # 3. Verificare config.json și chei
    cale_cfg = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(cale_cfg):
        try:
            with open(cale_cfg, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
            for sectiune, chei in CHEI_CONFIG_OBLIGATORII.items():
                if sectiune not in cfg_data:
                    erori.append(f"Secțiune lipsă în config.json: '{sectiune}'")
                else:
                    for c in chei:
                        if c not in cfg_data[sectiune]:
                            avertismente.append(f"Cheie lipsă în config.json -> {sectiune}.{c} (se va folosi default din config.py)")
            ok_list.append("Structura config.json este validă.")
        except Exception as e:
            erori.append(f"config.json nu este un JSON valid: {e}")

    # 4. Verificare securitate .env și Git
    cale_env = os.path.join(BASE_DIR, ".env")
    if os.path.exists(cale_env):
        with open(cale_env, "r", encoding="utf-8", errors="ignore") as f:
            env_txt = f.read()
        if "GEMINI_API_KEY=" in env_txt and len(env_txt.split("GEMINI_API_KEY=")[1].strip()) > 10:
            ok_list.append("Fișierul local .env conține GEMINI_API_KEY.")
        else:
            avertismente.append("Fișierul .env există, dar GEMINI_API_KEY pare necompletat.")
    else:
        avertismente.append("Fișierul .env nu există încă (creează-l din .env.example înainte de rulare).")

    if shutil.which("git") and os.path.isdir(os.path.join(BASE_DIR, ".git")):
        try:
            out_git = subprocess.check_output(
                ["git", "ls-files", ".env"], cwd=BASE_DIR, stderr=subprocess.DEVNULL, text=True
            ).strip()
            if out_git:
                erori.append("RISC SECURITATE: Fișierul '.env' este urmărit de Git! Rulează: git rm --cached .env")
            else:
                ok_list.append("Securitate Git: '.env' NU este urmărit de Git.")
        except Exception:
            pass

    # 5. Verificare pachete Python instalate
    for mod_name, pip_name in DEPENDENTE_EXTERNE:
        try:
            importlib.import_module(mod_name)
            ok_list.append(f"Bibliotecă instalată: {pip_name}")
        except Exception:
            avertismente.append(f"Bibliotecă Python neinstalată în mediul curent: {pip_name} (rulează: pip install -r requirements.txt)")

    # 6. Verificări specifice Raspberry Pi / Linux ARM
    este_linux_arm = (platform.system() == "Linux") and any(a in platform.machine().lower() for a in ("arm", "aarch64"))
    if este_linux_arm:
        print("\n[DETECȚIE RASPBERRY PI / LINUX ARM ACTIVĂ]")
        for utilitar in ("mpv", "ffmpeg", "mpg123", "amixer", "arecord", "aplay"):
            if shutil.which(utilitar):
                ok_list.append(f"Utilitar Linux găsit: {utilitar}")
            else:
                erori.append(f"Utilitar Linux lipsă pe Pi: {utilitar} (instalează cu sudo apt-get install)")

        # Verificare spațiu liber pe cardul SD
        total_b, used_b, free_b = shutil.disk_usage(BASE_DIR)
        free_mb = free_b // (1024 * 1024)
        if free_mb < 300:
            erori.append(f"Spațiu critic pe cardul SD: doar {free_mb} MB liberi!")
        else:
            ok_list.append(f"Spațiu liber pe cardul SD: {free_mb} MB.")

        # Verificare SPI și Framebuffer
        spidev_list = [f for f in os.listdir("/dev") if f.startswith("spidev") or f.startswith("fb")]
        if spidev_list:
            ok_list.append(f"Interfețe grafice/SPI detectate în /dev: {', '.join(sorted(spidev_list))}")
        else:
            avertismente.append("Nu s-au găsit /dev/spidev* sau /dev/fb* (verifică raspi-config dacă folosești ecran SPI).")

        # Verificare dispozitive audio ALSA
        try:
            out_rec = subprocess.check_output(["arecord", "-l"], stderr=subprocess.STDOUT, text=True)
            if "card" in out_rec.lower():
                ok_list.append("Microfon ALSA detectat de 'arecord -l'.")
            else:
                erori.append("Niciun microfon detectat de 'arecord -l'!")
        except Exception as e:
            avertismente.append(f"Nu am putut rula 'arecord -l': {e}")

    # Afișare raport final
    print("\n" + "-" * 68)
    print(f" ELEMENTE OK ({len(ok_list)}):")
    for item in ok_list:
        print(f"  [OK] {item}")

    if avertismente:
        print("\n" + "-" * 68)
        print(f" AVERTISMENTE ({len(avertismente)}):")
        for av in avertismente:
            print(f"  [AVERTISMENT] {av}")

    if erori:
        print("\n" + "-" * 68)
        print(f" ERORI CRITICE ({len(erori)}):")
        for er in erori:
            print(f"  [EROARE] {er}")

    print("\n" + "=" * 68)
    status_general = "EROARE" if erori else ("AVERTISMENT" if avertismente else "OK PERFECT")
    print(f" REZULTAT FINAL VERIFICARE: {status_general}")
    print("=" * 68)
    return 1 if erori else 0


if __name__ == "__main__":
    sys.exit(ruleaza_verificare())