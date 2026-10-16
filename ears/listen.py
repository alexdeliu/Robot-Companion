import os
import sys
from array import array
from contextlib import contextmanager
import speech_recognition as sr

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
        yield

recognizer = sr.Recognizer()
recognizer.dynamic_energy_threshold = False
recognizer.energy_threshold = 230
# Timp de așteptare după ce termini de vorbit redus la 0.65s pentru reacție rapidă!
recognizer. non_speaking_duration = 0.35
recognizer.pause_threshold = 0.65

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

def _proceseaza_dsp_rapid(audio_data):
    """
    Filtru DSP ultra-rapid (o singură trecere, fără upsampling inutil) optimizat pentru Raspberry Pi 3B+:
    Curăță DC offset-ul, accentuează consoanele (Pre-Emphasis) și amplifică vocea (Auto-Gain).
    """
    try:
        raw_bytes = audio_data.get_raw_data(convert_rate=8000, convert_width=2)
        samples = array('h', raw_bytes)
        num_samples = len(samples)
        if num_samples == 0:
            return audio_data

        dc_offset = int(sum(samples) / num_samples)
        max_peak = max(abs(x - dc_offset) for x in samples)
        gain = min(5.5, 27000.0 / float(max_peak)) if max_peak > 450 else 1.0

        out = array('h', [0] * num_samples)
        prev = samples[0] - dc_offset
        out[0] = max(-32768, min(32767, int(prev * gain)))

        # O singură buclă rapidă pentru Pre-Emphasis + Auto-Gain
        for i in range(1, num_samples):
            curr = samples[i] - dc_offset
            boosted = (curr + 0.45 * (curr - prev)) * gain
            out[i] = max(-32768, min(32767, int(boosted)))
            prev = curr

        return sr.AudioData(out.tobytes(), 8000, 2)

    except Exception as e:
        print(f"[AVERTISMENT DSP]: {e}")
        return audio_data

def asculta_voce(on_status=None):
    """
    Ascultă microfonul cu latență minimă și recunoaște atât Română (ro-RO), cât și Engleză (en-US).
    """
    if on_status:
        on_status("pregatire")

    mic_index = _obtine_index_microfon()

    try:
        with ignore_stderr():
            source = sr.Microphone(device_index=mic_index, sample_rate=8000, chunk_size=512)

        with source:
            # Calibrare ultra-scurtă (0.15s) doar pentru stabilizarea canalului USB
            recognizer.adjust_for_ambient_noise(source, duration=0.15)
            recognizer.energy_threshold = max(190, min(300, int(recognizer.energy_threshold * 1.15)))

            if on_status:
                on_status("asculta")
            print(f"\n[ROBOT]: Te ascult! (Prag energie: {recognizer.energy_threshold})")

            audio_brut = recognizer.listen(source, timeout=6, phrase_time_limit=8)

        if on_status:
            on_status("procesare")
        print("[SISTEM]: Procesez și trimit vocea la Google STT...")

        audio_curat = _proceseaza_dsp_rapid(audio_brut)

        # Pe Raspberry Pi salvăm debug.wav în RAM (/dev/shm) ca să nu încetinim cardul SD
        cale_debug = "/dev/shm/debug.wav" if os.path.isdir("/dev/shm") else "debug.wav"
        with open(cale_debug, "wb") as f:
            f.write(audio_curat.get_wav_data())

        # 1. Încercăm recunoașterea în limba Română (care prinde și cuvinte englezești uzuale)
        try:
            text = recognizer.recognize_google(audio_curat, language="ro-RO")
            print(f"[TU AI SPUS (RO)]: {text}")
            return text
        except sr.UnknownValueError:
            # 2. Dacă ai vorbit o propoziție întreagă în Engleză, o decodăm instant pe en-US!
            text_en = recognizer.recognize_google(audio_curat, language="en-US")
            print(f"[TU AI SPUS (EN)]: {text_en}")
            return text_en

    except sr.WaitTimeoutError:
        print("[EROARE]: Nu s-a detectat voce în timpul alocat.")
        return None
    except sr.UnknownValueError:
        print("[EROARE]: Nu am înțeles cuvintele nici în RO, nici în EN.")
        return None
    except Exception as e:
        print(f"[EROARE MICROFON]: {e}")
        global _MIC_INDEX_CACHE
        _MIC_INDEX_CACHE = None
        return None

if __name__ == "__main__":
    rezultat = asculta_voce()
    print(f"Rezultat returnat: {rezultat}")