import os
import json
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

CONFIG_JSON_PATH = os.path.join(BASE_DIR, "config.json")
CONFIG_LOCAL_PATH = os.path.join(BASE_DIR, "config.local.json")

_DEFAULT_CFG = {
    "debug": True,
    "ai": {
        "model_principal": "gemini-3.5-flash",
        "modele_rezerva": ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-latest"],
        "timeout_ms": 15000,
        "temperatura": 0.45,
        "max_istoric": 8
    },
    "audio_out": {
        "tts_voice_ro": "ro-RO-EmilNeural",
        "tts_voice_en": "en-US-ChristopherNeural",
        "tts_rate": "+8%",
        "volum_normal": 95,
        "volum_ducking": 30
    },
    "microphone": {
        "preferred_device_index": None,
        "preferred_keywords": ["USB", "Camera", "Webcam", "Audio", "Mic"],
        "sample_rate": 8000,
        "chunk_size": 512,
        "auto_gain_alsa_percent": 75,
        "highpass_cutoff_hz": 100,
        "target_rms": 3200,
        "max_dsp_gain": 3.5,
        "ambient_multiplier": 1.25,
        "min_energy_threshold": 280,
        "max_energy_threshold": 3200,
        "pause_threshold": 0.85,
        "phrase_time_limit": 10.0,
        "listen_timeout": 6.0
    },
    "wake_word": {
        "enabled_by_default": True,
        "preferred_strategy": "auto",
        "strategies_order": ["vosk_phonetic", "openwakeword", "energy_vad_stt"],
        "sensitivity_rms_ratio": 1.35,
        "min_trigger_rms": 260,
        "fuzzy_threshold": 0.72,
        "ignore_after_speak_sec": 0.9,
        "vosk_gain": 3.0,
        "custom_triggers": [
            "robot", "robotul", "robotule", "robote", "robo", "robert", "robbie",
            "rob", "ropot", "rombot", "raw bought", "row boat", "row bought",
            "rah bought", "roar boat", "rabat", "rub out", "hey robot", "ok robot"
        ]
    },
    "youtube": {
        "max_video_height": 360,
        "max_video_fps": 25,
        "search_timeout_sec": 6,
        "ytdlp_timeout_sec": 12,
        "cache_ttl_sec": 1800,
        "prefetch_next": True
    },
    "ui": {
        "debounce_ms": 250,
        "clock_refresh_ms": 10000,
        "health_refresh_ms": 15000
    }
}


def _imbina_dict(baza, nou):
    for k, v in nou.items():
        if isinstance(v, dict) and k in baza and isinstance(baza[k], dict):
            baza[k].update(v)
        else:
            baza[k] = v


def incarca_config():
    cfg = json.loads(json.dumps(_DEFAULT_CFG))
    cfg["youtube"].setdefault("video_mode", "auto")
    cfg["youtube"].setdefault("video_vo_chain", ["tk_canvas", "x11", "xv", "wlshm", "sdl"])
    cfg["youtube"].setdefault("spi_canvas_fps", 12)
    cfg["youtube"].setdefault("log_errors", True)
    cfg["wake_word"].setdefault("telemetry_interval_sec", 5.0)
    cfg["wake_word"].setdefault("debug_wake_in_ui", True)
    cfg["ui"].setdefault("min_button_height_px", 36)
    cfg["ui"].setdefault("dnd_enabled", False)
    for cale in (CONFIG_JSON_PATH, CONFIG_LOCAL_PATH):
        if os.path.exists(cale):
            try:
                with open(cale, "r", encoding="utf-8") as f:
                    _imbina_dict(cfg, json.load(f))
            except Exception as e:
                print(f"[AVERTISMENT CONFIG]: Eroare la citirea {os.path.basename(cale)} ({e}).")
    return cfg


def salveaza_config_local(sectiune, cheie, valoare):
    """Salvează persistent volumul sau starea DND în config.local.json fără a modifica config.json din Git."""
    try:
        CFG.setdefault(sectiune, {})[cheie] = valoare
        date_locale = {}
        if os.path.exists(CONFIG_LOCAL_PATH):
            with open(CONFIG_LOCAL_PATH, "r", encoding="utf-8") as f:
                date_locale = json.load(f)
        date_locale.setdefault(sectiune, {})[cheie] = valoare
        with open(CONFIG_LOCAL_PATH, "w", encoding="utf-8") as f:
            json.dump(date_locale, f, indent=2)
    except Exception as e:
        print(f"[AVERTISMENT CONFIG LOCAL]: Nu am putut salva {sectiune}.{cheie}: {e}")


CFG = incarca_config()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "").strip()
DEBUG = os.getenv("DEBUG", "1" if CFG.get("debug", True) else "0") == "1"

if not GEMINI_API_KEY or "PUNE_CHEIA" in GEMINI_API_KEY:
    print("[AVERTISMENT SECURITATE/CONFIG]: GEMINI_API_KEY lipsește din fișierul .env! Creează .env din .env.example.")

MODEL_PRINCIPAL = os.getenv("MODEL_PRINCIPAL", CFG["ai"]["model_principal"])
MODELE_REZERVA = CFG["ai"]["modele_rezerva"]
GEMINI_TIMEOUT_MS = int(CFG["ai"]["timeout_ms"])

VOCE_RO = os.getenv("TTS_VOICE_RO", CFG["audio_out"]["tts_voice_ro"])
VOCE_EN = os.getenv("TTS_VOICE_EN", CFG["audio_out"]["tts_voice_en"])
VITEZA_VOCE = os.getenv("TTS_RATE", CFG["audio_out"]["tts_rate"])

SAMPLE_RATE_MIC = int(CFG["microphone"]["sample_rate"])
PAUSE_THRESHOLD = float(CFG["microphone"]["pause_threshold"])