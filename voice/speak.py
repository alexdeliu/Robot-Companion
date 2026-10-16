import os
import re
import time
import asyncio
import tempfile
import shutil
import subprocess

# Ascundem mesajul de întâmpinare din consolă al librăriei pygame
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import edge_tts
import pygame

# Configurare voci neurale (poți schimba în "ro-RO-AlinaNeural" pentru voce feminină)
VOCE_RO = "ro-RO-EmilNeural"
VOCE_EN = "en-US-ChristopherNeural"
VITEZA_VOCE = "+5%"

_MIXER_INITIALIZAT = False

def _obtine_cale_audio_temp():
    """
    Pe Raspberry Pi (Linux) salvează în /dev/shm (direct în RAM - zero uzură pe cardul SD!).
    Pe Windows salvează în folderul Temp al sistemului.
    """
    if os.path.isdir("/dev/shm"):
        return "/dev/shm/robot_tts.mp3"
    return os.path.join(tempfile.gettempdir(), "robot_tts.mp3")

def _curata_text_pentru_voce(text):
    """Elimină formatarea Markdown (*, #, _) pentru a nu fi citită literal de sinteză."""
    if not text:
        return ""
    text_curat = re.sub(r"[\*\#\_\`\~]", "", text)
    text_curat = re.sub(r"\s+", " ", text_curat).strip()
    return text_curat

async def _genereaza_audio_async(text, voce, cale_fisier):
    """Comunică cu serverul Edge TTS și salvează fișierul MP3."""
    communicate = edge_tts.Communicate(text, voice=voce, rate=VITEZA_VOCE)
    await communicate.save(cale_fisier)

def _reda_fisier_audio(cale_fisier):
    """
    Redă fișierul audio prin boxe folosind mpg123 (pe Linux) sau pygame.mixer (Windows/Linux).
    """
    global _MIXER_INITIALIZAT

    if os.name != "nt" and shutil.which("mpg123"):
        subprocess.run(
            ["mpg123", "-q", cale_fisier],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return

    if not _MIXER_INITIALIZAT:
        pygame.mixer.init(frequency=24000, buffer=2048)
        _MIXER_INITIALIZAT = True

    pygame.mixer.music.load(cale_fisier)
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        time.sleep(0.05)

    pygame.mixer.music.unload()

def vorbeste(text, limba="ro"):
    """Transformă textul în voce și îl redă prin boxe."""
    text_curat = _curata_text_pentru_voce(text)
    if not text_curat:
        return

    voce = VOCE_RO if limba == "ro" else VOCE_EN
    cale_temp = _obtine_cale_audio_temp()

    try:
        print(f"[VOCE]: Generez audio ({voce})...")
        asyncio.run(_genereaza_audio_async(text_curat, voce, cale_temp))

        print("[VOCE]: Redau răspunsul în boxe...")
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
    vorbeste("Salut! Sistemele mele audio sunt acum conectate în folderul voice și funcționează perfect!", limba="ro")