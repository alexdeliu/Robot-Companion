import os
import io
import re
import json
import time
import queue
import shutil
import asyncio
import threading
import subprocess
import edge_tts

DEBUG = os.getenv("DEBUG", "1") == "1"
VOCE_RO = os.getenv("TTS_VOICE_RO", "ro-RO-EmilNeural")
VOCE_EN = os.getenv("TTS_VOICE_EN", "en-US-ChristopherNeural")
VITEZA_VOCE = os.getenv("TTS_RATE", "+0%")

_MIXER_INITIALIZAT = False
_CALE_DICT = os.path.join(os.path.dirname(__file__), "pronuntie_ro.json")


def _incarca_dictionar():
    try:
        with open(_CALE_DICT, "r", encoding="utf-8") as f:
            date = json.load(f)
        # Sortăm descrescător după lungime ca expresiile ("raspberry pi") să fie înlocuite înaintea cuvintelor simple
        return sorted(date.items(), key=lambda x: len(x[0]), reverse=True)
    except Exception:
        return []


_PERECHI_PRONUNTIE = _incarca_dictionar()

_ABREVIERI_RO = [
    (re.compile(r"(?<!\w)-(\d+(?:[.,]\d+)?)\s*°\s*C\b", re.IGNORECASE), r"minus \1 grade Celsius"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*°\s*C\b", re.IGNORECASE), r"\1 grade Celsius"),
    (re.compile(r"(?<!\w)-(\d+(?:[.,]\d+)?)\s*°", re.IGNORECASE), r"minus \1 grade "),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*°", re.IGNORECASE), r"\1 grade "),
    (re.compile(r"\b(\d{1,2}):(\d{2})\b"), r"\1 și \2 de minute"),
    (re.compile(r"(\d+)\s*%"), r"\1 la sută"),
    (re.compile(r"\bkm/h\b", re.IGNORECASE), "kilometri pe oră"),
    (re.compile(r"\bm/s\b", re.IGNORECASE), "metri pe secundă"),
    (re.compile(r"\bnr\.\s*", re.IGNORECASE), "numărul "),
    (re.compile(r"\bex:\s*", re.IGNORECASE), "de exemplu "),
]


def _curata_si_adapteaza_text(text, limba="ro"):
    """Normalizează simboluri, numere, Markdown și aplică dicționarul fonetic doar pe cuvinte întregi."""
    if not text:
        return ""

    # Eliminăm tag-uri reziduale și simboluri Markdown/emoji
    text_curat = re.sub(r"^\s*\[[^\]]+\]\s*", "", text)
    text_curat = re.sub(r"[\*\#\_\`\~]", "", text_curat)
    text_curat = re.sub(r"[^\w\s.,!?:;ăâîșțĂÂÎȘȚ\-°%/]", " ", text_curat)

    if limba == "ro":
        for regex_abrev, inlocuire in _ABREVIERI_RO:
            text_curat = regex_abrev.sub(inlocuire, text_curat)

        for eng, fonetic_ro in _PERECHI_PRONUNTIE:
            pattern = re.compile(rf"\b{re.escape(eng)}\b", re.IGNORECASE)
            text_curat = pattern.sub(fonetic_ro, text_curat)

    return re.sub(r"\s+", " ", text_curat).strip()


async def _descarca_bytes_audio(text, voce):
    """Descarcă fluxul MP3 direct în memorie (RAM) pentru pre-fetching fără fișiere pe disc."""
    communicate = edge_tts.Communicate(text, voice=voce, rate=VITEZA_VOCE)
    buffer_ram = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buffer_ram.extend(chunk["data"])
    return bytes(buffer_ram)


async def _stream_direct_in_boxe_linux(text, voce, t_referinta=None):
    """Trimite pachetele audio direct în mpg123 în timp real."""
    communicate = edge_tts.Communicate(text, voice=voce, rate=VITEZA_VOCE)
    proces_player = subprocess.Popen(
        ["mpg123", "-q", "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    primul_sunet = False
    try:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio" and proces_player.stdin:
                if not primul_sunet and t_referinta is not None and DEBUG:
                    print(f"[TIMPI DEBUG]: Primul sunet TTS={time.perf_counter() - t_referinta:.2f}s")
                    primul_sunet = True
                proces_player.stdin.write(chunk["data"])
                proces_player.stdin.flush()
    finally:
        if proces_player.stdin:
            proces_player.stdin.close()
        proces_player.wait()


def _reda_bytes_audio(audio_bytes):
    """Redă bytes MP3 direct din memorie prin mpg123 (Linux) sau pygame.mixer (Windows)."""
    global _MIXER_INITIALIZAT
    if not audio_bytes:
        return

    if os.name != "nt" and shutil.which("mpg123"):
        subprocess.run(
            ["mpg123", "-q", "-"],
            input=audio_bytes,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return

    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    import pygame
    if not _MIXER_INITIALIZAT:
        pygame.mixer.init(frequency=24000, buffer=1024)
        _MIXER_INITIALIZAT = True

    flux_memorie = io.BytesIO(audio_bytes)
    pygame.mixer.music.load(flux_memorie, "mp3")
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(0.02)
    pygame.mixer.music.unload()


class StreamVorbeste:
    """
    Pipeline paralel Propoziții LLM -> Pre-fetch TTS în RAM -> Redare fără pauze între propoziții.
    """
    def __init__(self, limba="ro", t_referinta=None):
        self.limba = limba
        self.voce = VOCE_RO if limba == "ro" else VOCE_EN
        self.t_referinta = t_referinta
        self.coada_texte = queue.Queue()
        self.coada_audio = queue.Queue()
        self.primul_trimis = False
        self._t_fetch = threading.Thread(target=self._worker_prefetch, daemon=True)
        self._t_play = threading.Thread(target=self._worker_redare, daemon=True)
        self._t_fetch.start()
        self._t_play.start()

    def adauga_propozitie(self, propozitie):
        text_adaptat = _curata_si_adapteaza_text(propozitie, self.limba)
        if text_adaptat:
            self.coada_texte.put(text_adaptat)

    def _worker_prefetch(self):
        while True:
            text = self.coada_texte.get()
            if text is None:
                self.coada_audio.put(None)
                break
            try:
                # Pe Linux prima propoziție face pipe direct în mpg123 pentru latență minimă (~0.3s)
                if not self.primul_trimis and os.name != "nt" and shutil.which("mpg123"):
                    self.primul_trimis = True
                    self.coada_audio.put(("DIRECT_STREAM", text))
                else:
                    self.primul_trimis = True
                    audio_bytes = asyncio.run(_descarca_bytes_audio(text, self.voce))
                    self.coada_audio.put(("BYTES", audio_bytes))
            except Exception as e:
                print(f"[EROARE PREFETCH TTS]: {e}")

    def _worker_redare(self):
        primul_redat = False
        while True:
            element = self.coada_audio.get()
            if element is None:
                break
            tip, payload = element
            try:
                if tip == "DIRECT_STREAM":
                    asyncio.run(_stream_direct_in_boxe_linux(payload, self.voce, self.t_referinta))
                    primul_redat = True
                elif tip == "BYTES" and payload:
                    if not primul_redat and self.t_referinta is not None and DEBUG:
                        print(f"[TIMPI DEBUG]: Primul sunet TTS={time.perf_counter() - self.t_referinta:.2f}s")
                        primul_redat = True
                    _reda_bytes_audio(payload)
            except Exception as e:
                print(f"[EROARE REDARE TTS]: {e}")

    def asteapta_finalizarea(self):
        self.coada_texte.put(None)
        self._t_fetch.join()
        self._t_play.join()


def vorbeste(text, limba="ro"):
    """Funcție directă pentru rostirea unui text complet (compatibilă 100% cu apelurile existente)."""
    stream_tts = StreamVorbeste(limba=limba, t_referinta=time.perf_counter())
    stream_tts.adauga_propozitie(text)
    stream_tts.asteapta_finalizarea()


if __name__ == "__main__":
    vorbeste("Salut! Totul merge impecabil la 22°C în Timișoara, iar folderul voice este optimizat!", limba="ro")