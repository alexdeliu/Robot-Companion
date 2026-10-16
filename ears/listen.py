import os
import sys
from array import array
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
        yield

# Configurare globală a recognizer-ului
recognizer = sr.Recognizer()
recognizer.dynamic_energy_threshold = False
recognizer.energy_threshold = 240
recognizer.non_speaking_duration = 0.4
recognizer.pause_threshold = 1.0

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

def _proceseaza_dsp_audio(audio_data):
    """
    Prelucrează semnalul brut de la microfonul de 8000 Hz:
    1. Elimină DC Offset-ul
    2. Aplică filtru Pre-Emphasis (accentuează consoanele s, ș, t, ț, c)
    3. Aplică Auto-Gain (amplifică vocea dacă vorbești de la distanță)
    4. Face Upsampling 8000 Hz -> 16000 Hz pentru Google STT
    """
    try:
        raw_bytes = audio_data.get_raw_data(convert_rate=8000, convert_width=2)
        samples = array('h', raw_bytes)
        num_samples = len(samples)
        if num_samples == 0:
            return audio_data

        # 1. Eliminare DC Offset
        dc_offset = int(sum(samples) / num_samples)
        if dc_offset != 0:
            for i in range(num_samples):
                val = samples[i] - dc_offset
                samples[i] = max(-32768, min(32767, val))

        # 2. Filtru de claritate pentru consoane
        clarified = array('h', [0] * num_samples)
        prev = samples[0]
        clarified[0] = prev
        for i in range(1, num_samples):
            curr = samples[i]
            boosted = int(curr + 0.45 * (curr - prev))
            clarified[i] = max(-32768, min(32767, boosted))
            prev = curr

        # 3. Auto-Gain (Normalizare volum până la 85% din maxim, max 6x amplificare)
        max_peak = max(abs(x) for x in clarified)
        if max_peak > 450:
            target_peak = 28000
            gain = min(6.0, target_peak / float(max_peak))
            if gain > 1.05:
                for i in range(num_samples):
                    val = int(clarified[i] * gain)
                    clarified[i] = max(-32768, min(32767, val))

        # 4. Upsampling 8000 Hz -> 16000 Hz
        upsampled = array('h', [0] * (num_samples * 2))
        for i in range(num_samples - 1):
            s1 = clarified[i]
            s2 = clarified[i + 1]
            upsampled[2 * i] = s1
            upsampled[2 * i + 1] = (s1 + s2) >> 1
        upsampled[-2] = clarified[-1]
        upsampled[-1] = clarified[-1]

        return sr.AudioData(upsampled.tobytes(), 16000, 2)

    except Exception as e:
        print(f"[AVERTISMENT DSP]: {e}")
        return audio_data

def asculta_voce(on_status=None):
    """
    Ascultă microfonul și trimite în timp real starea către interfață prin callback-ul on_status:
    - "pregatire": cât timp deschide și calibrează portul USB
    - "asculta": în secunda exactă în care utilizatorul poate vorbi
    - "procesare": imediat ce utilizatorul a terminat de vorbit și se face transcrierea
    """
    if on_status:
        on_status("pregatire")

    mic_index = _obtine_index_microfon()

    try:
        with ignore_stderr():
            source = sr.Microphone(device_index=mic_index, sample_rate=8000, chunk_size=512)

        with source:
            # Micro-calibrare rapidă (0.25s) ca să nu rămână blocat în zgomotul de fond
            recognizer.adjust_for_ambient_noise(source, duration=0.25)
            # Limităm pragul în zona sigură (între 200 și 320)
            recognizer.energy_threshold = max(200, min(320, int(recognizer.energy_threshold * 1.15)))

            # Anunțăm interfața că microfonul este DESCHIS și gata de vorbire!
            if on_status:
                on_status("asculta")
            print(f"\n[ROBOT]: Te ascult! (Prag energie: {recognizer.energy_threshold})")

            audio_brut = recognizer.listen(source, timeout=7, phrase_time_limit=8)

        # Cum s-a ieșit din blocul 'with source', microfonul este eliberat!
        if on_status:
            on_status("procesare")
        print("[SISTEM]: Aplic filtrele audio și trimit la Google STT...")

        audio_curat = _proceseaza_dsp_audio(audio_brut)

        with open("debug.wav", "wb") as f:
            f.write(audio_curat.get_wav_data())

        text = recognizer.recognize_google(audio_curat, language="ro-RO")
        print(f"[TU AI SPUS]: {text}")
        return text

    except sr.WaitTimeoutError:
        print("[EROARE]: Nu s-a detectat voce în timpul alocat.")
        return None
    except sr.UnknownValueError:
        print("[EROARE]: Nu am înțeles cuvintele. (Verifică debug.wav)")
        return None
    except Exception as e:
        print(f"[EROARE MICROFON]: {e}")
        global _MIC_INDEX_CACHE
        _MIC_INDEX_CACHE = None  # Resetăm cache-ul dacă portul USB a dat eroare
        return None

if __name__ == "__main__":
    rezultat = asculta_voce()
    print(f"Rezultat returnat: {rezultat}")