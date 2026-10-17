import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "")
DEBUG = os.getenv("DEBUG", "1") == "1"

# Modele AI
MODEL_PRINCIPAL = os.getenv("MODEL_PRINCIPAL", "gemini-3.5-flash-lite")
MODELE_REZERVA = ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.1-flash-lite"]
GEMINI_TIMEOUT_MS = 15000

# Setări Voce (TTS)
VOCE_RO = os.getenv("TTS_VOICE_RO", "ro-RO-EmilNeural")
VOCE_EN = os.getenv("TTS_VOICE_EN", "en-US-ChristopherNeural")
VITEZA_VOCE = os.getenv("TTS_RATE", "+0%")

# Setări Microfon & Wake Word
SAMPLE_RATE_MIC = 8000
PAUSE_THRESHOLD = 0.85
WAKE_WORD_SILENCE_TIMEOUT_SEC = 20