import os
import re
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
    "VERSION",
    "README.md",
    "CHANGELOG.md",
    "main.py",
    "config.py",
    "config.json",
    "system_health.py",
    "diag_mic.py",
    "requirements.txt",
    "robot-companion.service",
    ".gitignore",
    ".gitattributes",
    ".env.example",
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
    "tools/release_check.py",
    "tools/verify_project.py",
    "tools/diag_youtube.py",
    "tools/ui_selftest.py",
    "tools/wake_eval.py",
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

# Tipare pentru scanarea de secrete în fișierele care ar ajunge pe GitHub
REGEX_SECRETE = [
    ("Cheie Google API (AIza...)", re.compile(r"AIza[0-9A-Za-z\-_]{30,}")),
    ("Cheie Gemini/Token (AQ.Ab8...)", re.compile(r"AQ\.[0-9A-Za-z\-_]{25,}")),
    ("GitHub Token (ghp_...)", re.compile(r"ghp_[0-9A-Za-z]{25,}")),
    ("Parolă/Secret hardcodat", re.compile(r"(?i)(?:wifi_password|parola_wifi|secret_key)\s*=\s*['\"][^'\"]{4,}['\"]")),
]


def ruleaza_verificare():
    erori = []
    avertismente = []
    ok_list = []

    print("=" * 70)
    print("   AUDIT FINAL DE RELEASE & SECURITATE - ROBOT COMPANION v1.0.0")
    print("=" * 70)
    print(f"Folder proiect : {BASE_DIR}")
    print(f"Sistem / Python: {platform.system()} {platform.machine()} | Python {sys.version.split()[0]}\n")

    # 1. Verificare fișiere obligatorii și conținut requirements.txt
    for rel_path in FISIERE_OBLIGATORII:
        full_p = os.path.join(BASE_DIR, rel_path)
        if not os.path.exists(full_p):
            erori.append(f"Fișier obligatoriu lipsă: {rel_path}")
        elif os.path.getsize(full_p) == 0:
            erori.append(f"Fișier gol (0 bytes): {rel_path}")
        else:
            ok_list.append(f"Fișier valid: {rel_path}")

    cale_req = os.path.join(BASE_DIR, "requirements.txt")
    if os.path.exists(cale_req):
        with open(cale_req, "r", encoding="utf-8") as f:
            linii_req = [l.strip() for l in f.readlines() if l.strip() and not l.startswith("#")]
        if len(linii_req) < 8:
            erori.append(f"requirements.txt are doar {len(linii_req)} pachete (trebuie minim 8)!")
        else:
            ok_list.append(f"requirements.txt conține {len(linii_req)} pachete configurate.")

    # 2. Compilare statică (py_compile) + Verificare Taburi amestecate în toate fișierele .py
    py_files = []
    for radacina, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in ("venv", ".venv", "__pycache__", ".git", "logs")]
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(radacina, f))

    compile_ok = True
    tabs_ok = True
    for py_f in sorted(py_files):
        rel_py = os.path.relpath(py_f, BASE_DIR)
        try:
            py_compile.compile(py_f, doraise=True)
        except Exception as e:
            compile_ok = False
            erori.append(f"Eroare de sintaxă/indentare în {rel_py}: {e}")

        try:
            with open(py_f, "r", encoding="utf-8", errors="ignore") as f:
                for idx_l, linie in enumerate(f, start=1):
                    if "\t" in linie:
                        tabs_ok = False
                        erori.append(f"Tab găsit în loc de 4 spații în {rel_py} la linia {idx_l}")
                        break
        except Exception as e:
            avertismente.append(f"Nu am putut citi {rel_py}: {e}")

    if compile_ok:
        ok_list.append(f"Toate cele {len(py_files)} fișiere Python au trecut py_compile (0 erori sintaxă).")
    if tabs_ok:
        ok_list.append("Indentare curată (4 spații, 0 taburi în tot proiectul).")

    # 3. Scanare de secrete în toate fișierele care ar ajunge pe GitHub
    secrete_gasite = False
    fisiere_excluse_scan = {".env", "config.local.json"}
    for radacina, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in ("venv", ".venv", "__pycache__", ".git", "logs", "model_ro", "model_wake")]
        for f in files:
            if f in fisiere_excluse_scan or f.endswith((".pyc", ".wav", ".mp3", ".zip")):
                continue
            cale_f = os.path.join(radacina, f)
            rel_f = os.path.relpath(cale_f, BASE_DIR)
            try:
                with open(cale_f, "r", encoding="utf-8", errors="ignore") as fp:
                    continut = fp.read()
                for nume_sec, rgx in REGEX_SECRETE:
                    if rgx.search(continut):
                        secrete_gasite = True
                        erori.append(f"SECRET DETECTAT în fișier public ({rel_f}): {nume_sec}!")
            except Exception:
                pass
    if not secrete_gasite:
        ok_list.append("Scanare securitate: 0 chei API sau parole hardcodate în fișierele proiectului.")

    # 4. Verificare .gitignore și Git tracking pentru .env și config.local.json
    cale_gitignore = os.path.join(BASE_DIR, ".gitignore")
    if os.path.exists(cale_gitignore):
        with open(cale_gitignore, "r", encoding="utf-8", errors="ignore") as f:
            gi_txt = f.read()
        for elem_sensibil in (".env", "config.local.json", "logs/"):
            if elem_sensibil not in gi_txt:
                erori.append(f"'{elem_sensibil}' lipsește din .gitignore!")

    if shutil.which("git") and os.path.isdir(os.path.join(BASE_DIR, ".git")):
        for f_sens in (".env", "config.local.json"):
            try:
                out_git = subprocess.check_output(
                    ["git", "ls-files", f_sens], cwd=BASE_DIR, stderr=subprocess.DEVNULL, text=True
                ).strip()
                if out_git:
                    erori.append(f"RISC SECURITATE: '{f_sens}' este urmărit de Git! Rulează: git rm --cached {f_sens}")
                else:
                    ok_list.append(f"Protecție Git: '{f_sens}' este ignorat corect de Git.")
            except Exception as e:
                avertismente.append(f"Verificare git ls-files ({f_sens}): {e}")

    # 5. Verificare config.json și import de test pe modulele interne
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
                            avertismente.append(f"Cheie lipsă în config.json: {sectiune}.{c}")
            ok_list.append("Structura config.json este completă și validă.")
        except Exception as e:
            erori.append(f"config.json invalid: {e}")

    for mod_intern in ("config", "system_health", "brain.abilities.weather", "brain.abilities.wikipedia_ro", "brain.abilities.timers"):
        try:
            importlib.import_module(mod_intern)
            ok_list.append(f"Import modul intern OK: {mod_intern}")
        except Exception as e:
            erori.append(f"Eșec la importul modulului intern {mod_intern}: {e}")

    for mod_name, pip_name in DEPENDENTE_EXTERNE:
        try:
            importlib.import_module(mod_name)
            ok_list.append(f"Bibliotecă externă instalată: {pip_name}")
        except Exception:
            avertismente.append(f"Bibliotecă Python neinstalată în mediul curent: {pip_name}")

    # 6. Verificări specifice Raspberry Pi
    este_linux_arm = (platform.system() == "Linux") and any(a in platform.machine().lower() for a in ("arm", "aarch64"))
    if este_linux_arm:
        for utilitar in ("mpv", "ffmpeg", "mpg123", "amixer", "arecord", "aplay"):
            if shutil.which(utilitar):
                ok_list.append(f"Utilitar Linux găsit: {utilitar}")
            else:
                erori.append(f"Utilitar Linux lipsă pe Pi: {utilitar}")
        _, _, free_b = shutil.disk_usage(BASE_DIR)
        free_mb = free_b // (1024 * 1024)
        if free_mb < 300:
            erori.append(f"Spațiu critic pe cardul SD: doar {free_mb} MB liberi!")
        else:
            ok_list.append(f"Spațiu liber pe cardul SD: {free_mb} MB.")

    print("-" * 70)
    print(f" ELEMENTE OK ({len(ok_list)}):")
    for item in ok_list:
        print(f"  [OK] {item}")

    if avertismente:
        print("\n" + "-" * 70)
        print(f" AVERTISMENTE ({len(avertismente)}):")
        for av in avertismente:
            print(f"  [AVERTISMENT] {av}")

    if erori:
        print("\n" + "-" * 70)
        print(f" ERORI CRITICE ({len(erori)}):")
        for er in erori:
            print(f"  [EROARE] {er}")

    print("\n" + "=" * 70)
    status_general = "EROARE" if erori else ("AVERTISMENT" if avertismente else "OK PERFECT")
    print(f" REZULTAT FINAL RELEASE CHECK: {status_general}")
    print("=" * 70)
    return 1 if erori else 0


if __name__ == "__main__":
    sys.exit(ruleaza_verificare())