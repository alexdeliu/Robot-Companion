import os
import sys
from array import array
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import speech_recognition as sr

_MIC_INDEX_CACHE = None
_CALIBRAT_INITIAL = False

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
recognizer.energy_threshold = 220
recognizer.non_speaking_duration = 0.35
recognizer.pause_threshold = 0.6

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

def preincalzeste_microfon():
    """
    Rulat automat în fundal la pornirea aplicației.
    Găsește portul USB și calibrează zgomotul ambiental din timp, astfel încât
    atunci când utilizatorul apasă pe MIC, înregistrarea să pornească INSTANTANEU!
    """
    global _CALIBRAT_INITIAL
    if _CALIBRAT_INITIAL:
        return
    try:
        mic_index = _obtine_index_microfon()
        with ignore_stderr():
            source = sr.Microphone(device_index=mic_index, sample_rate=8000, chunk_size=512)
        with source:
            recognizer.adjust_for_ambient_noise(source, duration=0.2)
            recognizer.energy_threshold = max(190, min(290, int(recognizer.energy_threshold * 1.15)))
            _CALIBRAT_INITIAL = True
        print(f"[SISTEM]: Microfon pre-încălzit (Prag: {recognizer.energy_threshold})")
    except Exception as e:
        print(f"[AVERTISMENT PRE-ÎNCĂLZIRE MIC]: {e}")

def _proceseaza_dsp_rapid(audio_data):
    """Filtru DSP rapid într-o singură trecere (DC Offset + Pre-Emphasis consoane + Auto-Gain)."""
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

        for i in range(1, num_samples):
            curr = samples[i] - dc_offset
            boosted = (curr + 0.45 * (curr - prev)) * gain
            out[i] = max(-32768, min(32767, int(boosted)))
            prev = curr

        return sr.AudioData(out.tobytes(), 8000, 2)

    except Exception as e:
        print(f"[AVERTISMENT DSP]: {e}")
        return audio_data

def _interogheaza_stt(audio_curat, cod_limba):
    """Trimite audio la Google STT pentru o limbă și extrage (text, scor_incredere)."""
    try:
        rezultat = recognizer.recognize_google(audio_curat, language=cod_limba, show_all=True)
        if isinstance(rezultat, dict) and "alternative" in rezultat:
            alt = rezultat["alternative"]
            if alt:
                text = alt[0].get("transcript", "").strip()
                scor = float(alt[0].get("confidence", 0.75))
                return text, scor
    except Exception:
        pass
    return None, 0.0

def _recunoaste_bilingv_instant(audio_curat):
    """
    Trimite înregistrarea SIMULTAN la Google STT pe Română și pe Engleză.
    Nu adaugă nicio milisecundă de întârziere și înțelege ambele limbi!
    """
    with ThreadPoolExecutor(max_workers=2) as executor:
        viitor_ro = executor.submit(_interogheaza_stt, audio_curat, "ro-RO")
        viitor_en = executor.submit(_interogheaza_stt, audio_curat, "en-US")
        text_ro, scor_ro = viitor_ro.result()
        text_en, scor_en = viitor_en.result()

    if text_ro and text_en:
        # Oferim un ușor avantaj (+0.05) limbii române când scorurile sunt apropiate
        if scor_en > scor_ro + 0.05:
            print(f"[TU AI SPUS (EN - {scor_en:.2f})]: {text_en}")
            return text_en
        print(f"[TU AI SPUS (RO - {scor_ro:.2f})]: {text_ro}")
        return text_ro

    if text_ro:
        print(f"[TU AI SPUS (RO)]: {text_ro}")
        return text_ro
    if text_en:
        print(f"[TU AI SPUS (EN)]: {text_en}")
        return text_en
    return None

def asculta_voce(on_status=None):
    """Ascultă microfonul cu deschidere instantanee și recunoaștere bilingvă RO + EN."""
    global _CALIBRAT_INITIAL

    if on_status:
        on_status("pregatire")

    mic_index = _obtine_index_microfon()

    try:
        with ignore_stderr():
            source = sr.Microphone(device_index=mic_index, sample_rate=8000, chunk_size=512)

        with source:
            if not _CALIBRAT_INITIAL:
                recognizer.adjust_for_ambient_noise(source, duration=0.15)
                recognizer.energy_threshold = max(190, min(290, int(recognizer.energy_threshold * 1.15)))
                _CALIBRAT_INITIAL = True

            if on_status:
                on_status("asculta")
            print(f"\n[ROBOT]: Te ascult! (Prag energie: {recognizer.energy_threshold})")

            audio_brut = recognizer.listen(source, timeout=6, phrase_time_limit=8)

        if on_status:
            on_status("procesare")
        print("[SISTEM]: Procesez vocea (RO + EN în paralel)...")

        audio_curat = _proceseaza_dsp_rapid(audio_brut)

        cale_debug = "/dev/shm/debug.wav" if os.path.isdir("/dev/shm") else "debug.wav"
        with open(cale_debug, "wb") as f:
            f.write(audio_curat.get_wav_data())

        text = _recunoaste_bilingv_instant(audio_curat)
        if not text:
            print("[EROARE]: Nu am înțeles cuvintele nici în RO, nici în EN.")
            return None
        return text

    except sr.WaitTimeoutError:
        print("[EROARE]: Nu s-a detectat voce în timpul alocat.")
        return None
    except Exception as e:
        print(f"[EROARE MICROFON]: {e}")
        global _MIC_INDEX_CACHE
        _MIC_INDEX_CACHE = None
        return None

if __name__ == "__main__":
    rezultat = asculta_voce()
    print(f"Rezultat returnat: {rezultat}")