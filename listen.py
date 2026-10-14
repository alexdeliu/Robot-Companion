import os
import sys
from contextlib import contextmanager
import speech_recognition as sr

# Variabilă globală pentru Zero-Latency Caching (evită rescanarea USB la fiecare apăsare)
_MIC_INDEX_CACHE = None

@contextmanager
def ignore_stderr():
    """Suprimă erorile C/ALSA/JACK din terminal pe Linux în timpul inițializării PyAudio."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        sys.stderr.flush()
        os.dup2(devnull, 2)
        os.close(devnull)
        try:
            yield
        finally:
            os.dup2(old_stderr, 2)
            os.close(old_stderr)
    except Exception:
        # Fallback sigur pentru rularea pe Windows
        yield

# Configurare globală a recognizer-ului pentru hardware-ul actual
recognizer = sr.Recognizer()
recognizer.dynamic_energy_threshold = False
recognizer.energy_threshold = 300
recognizer.pause_threshold = 1.5

def _obtine_index_microfon():
    """Caută portul USB al camerei web o singură dată și îl salvează în cache."""
    global _MIC_INDEX_CACHE
    if _MIC_INDEX_CACHE is not None:
        return _MIC_INDEX_CACHE

    print("\n[SISTEM]: Scanez porturile audio pentru camera web...")
    with ignore_stderr():
        lista_microfoane = sr.Microphone.list_microphone_names()

    for index, name in enumerate(lista_microfoane):
        if "USB" in name or "Camera" in name or "Audio" in name:
            _MIC_INDEX_CACHE = index
            print(f"[SISTEM]: Microfon salvat în cache pe portul {_MIC_INDEX_CACHE}: {name}")
            break

    return _MIC_INDEX_CACHE

def asculta_voce():
    """Ascultă microfonul, salvează debug.wav și returnează textul recunoscut (sau None)."""
    mic_index = _obtine_index_microfon()

    try:
        with ignore_stderr():
            source = sr.Microphone(device_index=mic_index, sample_rate=8000)

        with source:
            print("\n[ROBOT]: Te ascult! (Vorbește acum...)")
            audio = recognizer.listen(source, timeout=5)

        print("[SISTEM]: Procesez vocea...")

        # Salvăm captura pentru diagnostic acustic
        with open("debug.wav", "wb") as f:
            f.write(audio.get_wav_data())

        text = recognizer.recognize_google(audio, language="ro-RO")
        print(f"[TU AI SPUS]: {text}")
        return text

    except sr.WaitTimeoutError:
        print("[EROARE]: Timpul de așteptare a expirat (nu s-a detectat voce).")
        return None
    except sr.UnknownValueError:
        print("[EROARE]: Nu am înțeles cuvintele. (Verifică debug.wav)")
        return None
    except Exception as e:
        print(f"[EROARE]: {e}")
        return None

if __name__ == "__main__":
    # Pentru testare directă din terminal: python listen.py
    rezultat = asculta_voce()
    print(f"Rezultat returnat: {rezultat}")