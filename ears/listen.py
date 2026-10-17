import os
import sys
import time
from array import array
from contextlib import contextmanager
import speech_recognition as sr

DEBUG = os.getenv("DEBUG", "1") == "1"

_MIC_INDEX_CACHE = None
_CALIBRAT_INITIAL = False


@contextmanager
def ignore_stderr():
    """Suprimă complet erorile C/ALSA/JACK din terminal pe Linux în timpul folosirii PyAudio."""
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
# Prag fixat după calibrarea la rece (nu îl lăsăm să scadă sub zgomotul camerei!)
recognizer.dynamic_energy_threshold = False
recognizer.energy_threshold = 380
recognizer.non_speaking_duration = 0.35
# Se oprește la 0.85s după ce ai terminat propoziția (permite pauze scurte de respirație, dar nu stă blocat!)
recognizer.pause_threshold = 0.85
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


def preincalzeste_microfon():
    """
    Măsoară zgomotul real al camerei web USB la pornire (cu ALSA stderr complet ascuns)
    și setează pragul cu 35% PESTE zgomotul de fond ca să nu rămână blocat pe înregistrare!
    """
    global _CALIBRAT_INITIAL
    if _CALIBRAT_INITIAL:
        return
    try:
        mic_index = _obtine_index_microfon()
        # ATENȚIE: atât crearea Microphone cât și 'with source:' stau în ignore_stderr()!
        with ignore_stderr():
            source = sr.Microphone(device_index=mic_index, sample_rate=8000, chunk_size=512)
            with source:
                recognizer.adjust_for_ambient_noise(source, duration=0.4)
                zgomot_ambiant = recognizer.energy_threshold
                # Punem pragul cu 35% peste zgomotul de fond (între 300 și 900)
                recognizer.energy_threshold = max(300, min(900, int(zgomot_ambiant * 1.35)))
                _CALIBRAT_INITIAL = True
        if DEBUG:
            print(
                f"[SISTEM]: Microfon pre-încălzit (8000 Hz | "
                f"Zgomot fond: {int(zgomot_ambiant)} -> Prag voce: {recognizer.energy_threshold})"
            )
    except Exception as e:
        if DEBUG:
            print(f"[AVERTISMENT PRE-ÎNCĂLZIRE MIC]: {e}")


def _curata_si_amplifica_vocea(audio_data):
    """
    1. Elimină DC-offset-ul camerei USB.
    2. Aplică un pre-emphasis fin (0.25) pentru claritatea consoanelor la 8000 Hz.
    3. Normalizează volumul până la ~75% din maxim (max 3.0x) fără clipping.
    """
    try:
        raw_bytes = audio_data.get_raw_data(convert_rate=8000, convert_width=2)
        samples = array("h", raw_bytes)
        n = len(samples)
        if n == 0:
            return audio_data

        dc_offset = int(sum(samples) / n)
        max_peak = max(abs(x - dc_offset) for x in samples)

        gain = min(3.0, 24000.0 / float(max_peak)) if max_peak > 350 else 1.0

        out = array("h", [0] * n)
        prev = samples[0] - dc_offset
        out[0] = max(-32768, min(32767, int(prev * gain)))

        for i in range(1, n):
            curr = samples[i] - dc_offset
            val = int((curr + 0.25 * (curr - prev)) * gain)
            out[i] = max(-32768, min(32767, val))
            prev = curr

        return sr.AudioData(out.tobytes(), 8000, 2)
    except Exception:
        return audio_data


def _extrage_cel_mai_bun_text(rezultat):
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
    """Ascultă microfonul fără erori ALSA și se oprește rapid după ce termini propoziția."""
    global _CALIBRAT_INITIAL

    if on_status:
        on_status("pregatire")

    mic_index = _obtine_index_microfon()

    try:
        # Tot blocul PyAudio rulează sub ignore_stderr() -> zero mesaje ALSA/JACK în consolă!
        with ignore_stderr():
            source = sr.Microphone(device_index=mic_index, sample_rate=8000, chunk_size=512)
            with source:
                if not _CALIBRAT_INITIAL:
                    recognizer.adjust_for_ambient_noise(source, duration=0.35)
                    zgomot = recognizer.energy_threshold
                    recognizer.energy_threshold = max(300, min(900, int(zgomot * 1.35)))
                    _CALIBRAT_INITIAL = True

                if on_status:
                    on_status("asculta")
                if DEBUG:
                    print(f"\n[ROBOT]: Te ascult! (8000 Hz | Prag voce: {recognizer.energy_threshold})")

                t_rec = time.perf_counter()
                audio_brut = recognizer.listen(source, timeout=6, phrase_time_limit=10)
                durata_rec = time.perf_counter() - t_rec

        if on_status:
            on_status("procesare")

        t_stt = time.perf_counter()
        audio_curat = _curata_si_amplifica_vocea(audio_brut)

        if DEBUG:
            cale_debug = "/dev/shm/debug.wav" if os.path.isdir("/dev/shm") else "debug.wav"
            with open(cale_debug, "wb") as f:
                f.write(audio_curat.get_wav_data())

        text_ro, scor_ro = _apel_stt_cu_retry(audio_curat, "ro-RO")

        if not text_ro or (scor_ro < 0.55 and len(text_ro.split()) <= 2):
            text_en, scor_en = _apel_stt_cu_retry(audio_curat, "en-US")
            if text_en and scor_en > scor_ro:
                text_ro = text_en

        if DEBUG:
            print(
                f"[TIMPI DEBUG]: Captură microfon={durata_rec:.2f}s | "
                f"STT Google={time.perf_counter() - t_stt:.2f}s | Text='{text_ro}'"
            )

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