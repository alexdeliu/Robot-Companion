import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
DEBUG = os.getenv("DEBUG", "1") == "1"

# Modele AI (gemini-3.5-flash asigură gramatică și ortografie română fără cuvinte pocite)
MODEL_PRINCIPAL = os.getenv("MODEL_PRINCIPAL", "gemini-3.5-flash")
MODELE_REZERVA = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest"
]
GEMINI_TIMEOUT_MS = 15000

# Setări Voce (TTS) - +8% este viteza nativă la care EmilNeural articulează curat consoanele finale (-n, -m)
VOCE_RO = os.getenv("TTS_VOICE_RO", "ro-RO-EmilNeural")
VOCE_EN = os.getenv("TTS_VOICE_EN", "en-US-ChristopherNeural")
VITEZA_VOCE = os.getenv("TTS_RATE", "+8%")

# Setări Microfon
SAMPLE_RATE_MIC = 8000
PAUSE_THRESHOLD = 0.85