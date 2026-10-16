import os
import re
import time
import asyncio
import tempfile
import shutil
import subprocess

import edge_tts

VOCE_RO = "ro-RO-EmilNeural"
VOCE_EN = "en-US-ChristopherNeural"
VITEZA_VOCE = "+8%"

_MIXER_INITIALIZAT = False

DICTIONAR_PRONUNTIE_EN_RO = {
    "voice": "vois",
    "ears": "iărs",
    "brain": "brein",
    "weather": "uedăr",
    "folder": "foldăr",
    "folderul": "foldărul",
    "folderele": "foldărele",
    "file": "fail",
    "update": "apdeit",
    "upgrade": "apgreid",
    "online": "onlain",
    "offline": "oflain",
    "server": "sărvăr",
    "serverele": "sărvărele",
    "cloud": "claud",
    "hardware": "harduer",
    "software": "softuer",
    "bug": "bag",
    "bug-uri": "baguri",
    "setup": "setap",
    "display": "displei",
    "kiosk": "chiosc",
    "raspberry": "rezbări",
    "pi": "pai",
    "python": "paiton",
    "google": "gugăl",
    "gemini": "geminai",
    "github": "ghithab",
    "youtube": "iutub",
    "play": "plei",
    "music": "miuzic",
    "video": "vidio",
    "branch": "brenci",
    "commit": "comit",
    "merge": "mărg",
    "push": "puș",
    "pull": "pul",
    "chat": "ceat",
    "cool": "cul",
    "okay": "ochei",
    "ok": "ochei",
    "weekend": "uichend",
    "weekendul": "uichendul",
    "gaming": "gheming",
    "streaming": "striming",
    "wireless": "uairles",
    "wi-fi": "uai-fai",
    "wifi": "uai-fai",
    "bluetooth": "blutut",
    "mouse": "maus",
    "keyboard": "chibord",
    "smart": "smart",
    "fake": "feic",
    "scrolling": "scroling"
}

def _obtine_cale_audio_temp():
    if os.path.isdir("/dev/shm"):
        return "/dev/shm/robot_tts.mp3"
    return os.path.join(tempfile.gettempdir(), "robot_tts.mp3")

def _curata_si_adapteaza_text(text, limba="ro"):
    """Curăță simbolurile Markdown și adaptează fonetic termenii englezești rămași."""
    if not text:
        return ""
    text_curat = text.replace("°C", " grade").replace("°", " grade ").replace("%", " la sută")
    text_curat = re.sub(r"[\*\#\_\`\~]", "", text_curat)
    text_curat = re.sub(r"\s+", " ", text_curat).strip()

    if limba == "ro":
        for eng, fonetic_ro in DICTIONAR_PRONUNTIE_EN_RO.items():
            pattern = re.compile(rf"\b{re.escape(eng)}\b", re.IGNORECASE)
            text_curat = pattern.sub(fonetic_ro, text_curat)

    return text_curat

async def _stream_direct_in_boxe_linux(text, voce):
    """Trimite bucățile audio direct în mpg123 pe măsură ce sosesc de la server."""
    communicate = edge_tts.Communicate(text, voice=voce, rate=VITEZA_VOCE)
    proces_player = subprocess.Popen(
        ["mpg123", "-q", "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    try:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio" and proces_player.stdin:
                proces_player.stdin.write(chunk["data"])
                proces_player.stdin.flush()
    finally:
        if proces_player.stdin:
            proces_player.stdin.close()
        proces_player.wait()

async def _genereaza_fisier_async(text, voce, cale_fisier):
    communicate = edge_tts.Communicate(text, voice=voce, rate=VITEZA_VOCE)
    await communicate.save(cale_fisier)

def _reda_cu_pygame(cale_fisier):
    global _MIXER_INITIALIZAT
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
    """Redă textul prin boxe cu latență minimă."""
    text_adaptat = _curata_si_adapteaza_text(text, limba=limba)
    if not text_adaptat:
        return

    voce = VOCE_RO if limba == "ro" else VOCE_EN

    if os.name != "nt" and shutil.which("mpg123"):
        try:
            asyncio.run(_stream_direct_in_boxe_linux(text_adaptat, voce))
            return
        except Exception as e:
            print(f"[AVERTISMENT STREAM AUDIO]: {e}, trec pe modul clasic...")

    cale_temp = _obtine_cale_audio_temp()
    try:
        asyncio.run(_genereaza_fisier_async(text_adaptat, voce, cale_temp))
        _reda_cu_pygame(cale_temp)
    except Exception as e:
        print(f"[EROARE VOCE]: Nu am putut reda sunetul ({e})")
    finally:
        try:
            if os.path.exists(cale_temp):
                os.remove(cale_temp)
        except Exception:
            pass

if __name__ == "__main__":
    vorbeste("Salut! Sistemul vocal este optimizat și gata de acțiune!", limba="ro")