import os
import sys
import time
from array import array
from contextlib import contextmanager
import speech_recognition as sr

DEBUG = os.getenv("DEBUG", "1") == "1"

_MIC_INDEX_CACHE = None
_SAMPLE_RATE_CACHE = None
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
recognizer.dynamic_energy_threshold = True
recognizer.dynamic_energy_adjustment_damping = 0.15
recognizer.dynamic_energy_ratio = 1.5
recognizer.energy_threshold = 180
recognizer.non_speaking_duration = 0.4
recognizer.pause_threshold = 1.05
recognizer.phrase_threshold = 0.25


def _obtine_index_microfon():
    """Caută portul USB al camerei web o singură dată și îl salvează în cache."""
    global _MIC_INDEX_CACHE
    if _MIC_INDEX_CACHE is not None:
        return _MIC_INDEX_CACHE

    with ignore_stderr():
        lista_microfoane = sr.Microphone.list_microphone_names()

    for index, name in enumerate(lista_microfoane):
        if any(k in name for k in ("USB", "Camera", "Webcam", "Audio", "Mic")):
            _MIC_INDEX_CACHE = index
            if DEBUG:
                print(f"[SISTEM]: Microfon salvat în cache pe portul {_MIC_INDEX_CACHE}: {name}")
            break

    return _MIC_INDEX_CACHE


def _deschide_microfon(mic_index):
    """Deschide microfonul la 16000 Hz (optim pentru STT), cu fallback automat la 8000 Hz."""
    global _SAMPLE_RATE_CACHE
    rate_de_incercat = [_SAMPLE_RATE_CACHE] if _SAMPLE_RATE_CACHE else [16000, 8000]

    for rata in rate_de_incercat:
        try:
            chunk = 1024 if rata == 16000 else 512
            with ignore_stderr():
                src = sr.Microphone(device_index=mic_index, sample_rate=rata, chunk_size=chunk)
            _SAMPLE_RATE_CACHE = rata
            return src
        except Exception:
            continue

    with ignore_stderr():
        return sr.Microphone(device_index=mic_index)


def preincalzeste_microfon():
    """Calibrează microfonul în fundal la pornirea aplicației."""
    global _CALIBRAT_INITIAL
    if _CALIBRAT_INITIAL:
        return
    try:
        mic_index = _obtine_index_microfon()
        source = _deschide_microfon(mic_index)
        with source:
            recognizer.adjust_for_ambient_noise(source, duration=0.3)
            recognizer.energy_threshold = max(150, min(300, int(recognizer.energy_threshold)))
            _CALIBRAT_INITIAL = True
        if DEBUG:
            print(f"[SISTEM]: Microfon pre-încălzit ({_SAMPLE_RATE_CACHE} Hz | Prag: {recognizer.energy_threshold})")
    except Exception as e:
        if DEBUG:
            print(f"[AVERTISMENT PRE-ÎNCĂLZIRE MIC]: {e}")


def _curata_dc_si_normalizeaza_bland(audio_data):
    """
    Elimină doar DC-offset-ul și aplică un gain blând (max 2.0x) doar dacă vocea este foarte slabă,
    fără a distorsiona armonicile și fără a ridica agresiv zgomotul de fond.
    """
    try:
        rata = audio_data.sample_rate
        raw_bytes = audio_data.get_raw_data(convert_rate=rata, convert_width=2)
        samples = array("h", raw_bytes)
        n = len(samples)
        if n == 0:
            return audio_data

        dc_offset = int(sum(samples) / n)
        max_peak = max(abs(x - dc_offset) for x in samples)

        gain = 1.0
        if 300 < max_peak < 12000:
            gain = min(2.0, 20000.0 / float(max_peak))

        if dc_offset == 0 and gain <= 1.05:
            return audio_data

        out = array("h", [0] * n)
        for i in range(n):
            val = int((samples[i] - dc_offset) * gain)
            out[i] = max(-32768, min(32767, val))

        return sr.AudioData(out.tobytes(), rata, 2)
    except Exception:
        return audio_data


def _extrage_cel_mai_bun_text(rezultat):
    """Alege cea mai completă alternativă din răspunsul Google STT."""
    if not isinstance(rezultat, dict) or "alternative" not in rezultat:
        return None, 0.0
    alt_list = rezultat["alternative"]
    if not alt_list:
        return None, 0.0

    baza_text = alt_list[0].get("transcript", "").strip()
    baza_scor = float(alt_list[0].get("confidence", 0.80))

    for alt in alt_list[1:3]:
        t = alt.get("transcript", "").strip()
        s = float(alt.get("confidence", 0.0))
        if len(t) > len(baza_text) + 4 and s >= baza_scor - 0.08:
            baza_text = t
            baza_scor = s
            break

    return (baza_text if baza_text else None), baza_scor


def _apel_stt_cu_retry(audio_curat, limba):
    """Apel Google STT cu 1 retry rapid în caz de eroare temporară de rețea."""
    for incercare in range(2):
        try:
            rez = recognizer.recognize_google(audio_curat, language=limba, show_all=True)
            return _extrage_cel_mai_bun_text(rez)
        except sr.RequestError:
            if incercare == 0:
                time.sleep(0.2)
                continue
        except Exception:
            break
    return None, 0.0


def asculta_voce(on_status=None):
    """Ascultă microfonul la 16 kHz, suportă fraze complexe și RO/EN."""
    global _CALIBRAT_INITIAL

    if on_status:
        on_status("pregatire")

    mic_index = _obtine_index_microfon()

    try:
        source = _deschide_microfon(mic_index)
        with source:
            if not _CALIBRAT_INITIAL:
                recognizer.adjust_for_ambient_noise(source, duration=0.25)
                _CALIBRAT_INITIAL = True

            # Plafonăm pragul adaptiv ca să rămână mereu receptiv
            recognizer.energy_threshold = max(150, min(320, int(recognizer.energy_threshold)))

            if on_status:
                on_status("asculta")
            if DEBUG:
                print(f"\n[ROBOT]: Te ascult! ({_SAMPLE_RATE_CACHE} Hz | Prag: {recognizer.energy_threshold})")

            audio_brut = recognizer.listen(source, timeout=6, phrase_time_limit=15)

        if on_status:
            on_status("procesare")

        t_stt = time.perf_counter()
        audio_curat = _curata_dc_si_normalizeaza_bland(audio_brut)

        if DEBUG:
            cale_debug = "/dev/shm/debug.wav" if os.path.isdir("/dev/shm") else "debug.wav"
            with open(cale_debug, "wb") as f:
                f.write(audio_curat.get_wav_data())

        text_ro, scor_ro = _apel_stt_cu_retry(audio_curat, "ro-RO")

        # Apelăm en-US doar dacă ro-RO nu a găsit nimic sau are scor foarte mic pe o frază scurtă
        if not text_ro or (scor_ro < 0.55 and len(text_ro.split()) <= 2):
            text_en, scor_en = _apel_stt_cu_retry(audio_curat, "en-US")
            if text_en and scor_en > scor_ro:
                text_ro = text_en

        if DEBUG:
            print(f"[TIMPI DEBUG]: STT={time.perf_counter() - t_stt:.2f}s | Text='{text_ro}'")

        return text_ro

    except sr.WaitTimeoutError:
        if DEBUG:
            print("[STT]: Timeout (nu s-a detectat voce).")
        return None
    except Exception as e:
        print(f"[EROARE MICROFON]: {e}")
        global _MIC_INDEX_CACHE
        _MIC_INDEX_CACHE = None
        return None


if __name__ == "__main__":
    rezultat = asculta_voce()
    print(f"Rezultat returnat: {rezultat}")