import os
import re
import json
import time
import shutil
import asyncio
import tempfile
import subprocess
import unicodedata
import edge_tts

DEBUG = os.getenv("DEBUG", "1") == "1"
VOCE_RO = os.getenv("TTS_VOICE_RO", "ro-RO-EmilNeural")
VOCE_EN = os.getenv("TTS_VOICE_EN", "en-US-ChristopherNeural")
VITEZA_VOCE = os.getenv("TTS_RATE", "+8%")

_MIXER_INITIALIZAT = False
_PROCES_CURENT_MPG123 = None
_CALE_DICT = os.path.join(os.path.dirname(__file__), "pronuntie_ro.json")

_DICT_IMPLICIT = {
    "raspberry pi": "razberi pai",
    "youtube music": "iutub miuzic",
    "youtube": "iutub",
    "wi-fi": "uaifai",
    "wifi": "uaifai",
    "bluetooth": "blutut",
    "wireless": "uairles",
    "folder": "foldăr",
    "folderul": "foldărul",
    "python": "paiton",
    "google": "gugăl",
    "gemini": "geminai",
    "github": "ghithab"
}


def _incarca_dictionar():
    try:
        with open(_CALE_DICT, "r", encoding="utf-8") as f:
            date = json.load(f)
        return sorted(date.items(), key=lambda x: len(x[0]), reverse=True)
    except Exception:
        return sorted(_DICT_IMPLICIT.items(), key=lambda x: len(x[0]), reverse=True)


_PERECHI_PRONUNTIE = _incarca_dictionar()

_ABREVIERI_RO = [
    (re.compile(r"(?<!\w)-(\d+(?:[.,]\d+)?)\s*°\s*C\b", re.IGNORECASE), r"minus \1 grade Celsius"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*°\s*C\b", re.IGNORECASE), r"\1 grade Celsius"),
    (re.compile(r"(?<!\w)-(\d+(?:[.,]\d+)?)\s*°", re.IGNORECASE), r"minus \1 grade "),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*°", re.IGNORECASE), r"\1 grade "),
    (re.compile(r"(\d+)\s*%"), r"\1 la sută"),
    (re.compile(r"\bkm/h\b", re.IGNORECASE), "kilometri pe oră"),
]


def _obtine_cale_audio_temp():
    if os.path.isdir("/dev/shm"):
        return "/dev/shm/robot_tts.mp3"
    return os.path.join(tempfile.gettempdir(), "robot_tts.mp3")


def _curata_si_adapteaza_text(text, limba="ro"):
    """
    Curăță simbolurile Markdown și păstrează 100% intacte cuvintele și cratimele românești,
    exact ca în prima versiune, adaptând doar termenii tehnici englezești.
    """
    if not text:
        return ""

    text_curat = unicodedata.normalize("NFC", text)
    text_curat = (
        text_curat.replace("ş", "ș").replace("Ş", "Ș")
        .replace("ţ", "ț").replace("Ţ", "Ț")
    )
    text_curat = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2212]", "-", text_curat)
    text_curat = re.sub(r"\b([a-zăâîșțA-ZĂÂÎȘȚ]{1,3})\s*-\s*([a-zăâîșțA-ZĂÂÎȘȚ]+)\b", r"\1-\2", text_curat)
    text_curat = re.sub(r"^\s*\[[^\]]+\]\s*", "", text_curat)
    text_curat = re.sub(r"[\*\#\_\`\~]", "", text_curat)

    if limba == "ro":
        for regex_abrev, inlocuire in _ABREVIERI_RO:
            text_curat = regex_abrev.sub(inlocuire, text_curat)

        for eng, fonetic_ro in _PERECHI_PRONUNTIE:
            pattern = re.compile(rf"(?<![\w\-]){re.escape(eng)}(?![\w\-])", re.IGNORECASE)
            text_curat = pattern.sub(fonetic_ro, text_curat)

    return re.sub(r"\s+", " ", text_curat).strip()


async def _genereaza_fisier_async(text, voce, cale_fisier):
    communicate = edge_tts.Communicate(text, voice=voce, rate=VITEZA_VOCE)
    await communicate.save(cale_fisier)


def opreste_voce():
    """Oprește imediat redarea vocală curentă (Barge-In)."""
    global _PROCES_CURENT_MPG123
    if _PROCES_CURENT_MPG123 and _PROCES_CURENT_MPG123.poll() is None:
        try:
            _PROCES_CURENT_MPG123.terminate()
        except Exception:
            pass
    if _MIXER_INITIALIZAT:
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass


def _reda_fisier_audio(cale_fisier):
    global _MIXER_INITIALIZAT, _PROCES_CURENT_MPG123

    if os.name != "nt" and shutil.which("mpg123"):
        _PROCES_CURENT_MPG123 = subprocess.Popen(
            ["mpg123", "-q", cale_fisier],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        _PROCES_CURENT_MPG123.wait()
        _PROCES_CURENT_MPG123 = None
        return

    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    import pygame
    if not _MIXER_INITIALIZAT:
        pygame.mixer.init(frequency=24000, buffer=1024)
        _MIXER_INITIALIZAT = True

    pygame.mixer.music.load(cale_fisier)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(0.03)
    pygame.mixer.music.unload()


def vorbeste(text, limba="ro"):
    t0 = time.perf_counter()
    text_adaptat = _curata_si_adapteaza_text(text, limba=limba)
    if not text_adaptat:
        return

    voce = VOCE_RO if limba == "ro" else VOCE_EN
    cale_temp = _obtine_cale_audio_temp()

    try:
        asyncio.run(_genereaza_fisier_async(text_adaptat, voce, cale_temp))
        if DEBUG:
            print(f"[TIMPI DEBUG]: Sinteză TTS gata în {time.perf_counter() - t0:.2f}s -> Redau în boxe...")
        _reda_fisier_audio(cale_temp)
    except Exception as e:
        print(f"[EROARE VOCE]: Nu am putut reda sunetul ({e})")
    finally:
        try:
            if os.path.exists(cale_temp):
                os.remove(cale_temp)
        except Exception:
            pass


if __name__ == "__main__":
    vorbeste("Salut! Acum vorbesc din nou clar, cursiv și natural în limba română, cu un plan bun pe ecran!", limba="ro")