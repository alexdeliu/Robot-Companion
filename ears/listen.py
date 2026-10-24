import os
import sys
import math
import time
import shutil
import subprocess
import threading
from array import array
from contextlib import contextmanager
import speech_recognition as sr

from config import CFG, DEBUG
from system_health import logger

# Lock global re-entrant împărțit între listen.py și wake_word.py:
# Garantează că placa audio USB nu este NICIODATĂ deschisă de două thread-uri simultan!
AUDIO_MIC_LOCK = threading.RLock()
_STDERR_LOCK = threading.Lock()

_MIC_INDEX_CACHE = None
_SAMPLE_RATE_CACHE = None
_CALIBRAT_INITIAL = False
_ZGOMOT_RMS_AMBIENTAL = 350.0


@contextmanager
def ignore_stderr():
    """
    Suprimă mesajele C/ALSA/JACK din terminal fără bug-ul de dublu-yield
    care provoca 'RuntimeError: generator didn't stop after throw()'.
    """
    devnull = None
    old_stderr = None
    with _STDERR_LOCK:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            old_stderr = os.dup(2)
            sys.stderr.flush()
            os.dup2(devnull, 2)
        except Exception:
            if devnull is not None:
                try:
                    os.close(devnull)
                except Exception:
                    pass
            devnull = None
            old_stderr = None

    try:
        yield
    finally:
        with _STDERR_LOCK:
            if old_stderr is not None:
                try:
                    sys.stderr.flush()
                    os.dup2(old_stderr, 2)
                except Exception:
                    pass
                try:
                    os.close(old_stderr)
                except Exception:
                    pass
            if devnull is not None:
                try:
                    os.close(devnull)
                except Exception:
                    pass


recognizer = sr.Recognizer()
recognizer.dynamic_energy_threshold = False
recognizer.energy_threshold = 380
recognizer.non_speaking_duration = 0.35
recognizer.pause_threshold = float(CFG["microphone"].get("pause_threshold", 0.85))
recognizer.phrase_threshold = 0.25


def _regleaza_gain_hardware_alsa(card_index=None):
    """Reglează automat volumul de captură al microfonului USB în ALSA în limite sigure (75%)."""
    if os.name == "nt" or not shutil.which("amixer"):
        return
    procent = int(CFG["microphone"].get("auto_gain_alsa_percent", 75))
    procent = max(50, min(90, procent))
    carduri = [str(card_index)] if card_index is not None else ["2", "1", "0"]
    for c in carduri:
        for ctrl in ("Mic", "Capture", "Auto Gain Control"):
            try:
                subprocess.run(
                    ["amixer", "-c", c, "set", ctrl, f"{procent}%", "cap", "unmute"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.5
                )
            except Exception as e:
                logger.debug(f"[ALSA MIC GAIN card {c} {ctrl}]: {e}")


def calculeaza_rms_pcm16(raw_bytes):
    if not raw_bytes or len(raw_bytes) < 4:
        return 0.0
    samples = array("h", raw_bytes)
    n = len(samples)
    if n == 0:
        return 0.0
    dc = sum(samples) / float(n)
    suma_patrate = sum((s - dc) * (s - dc) for s in samples)
    return math.sqrt(suma_patrate / float(n))


def _obtine_index_microfon(fortat=False):
    """
    Enumerează, filtrează și selectează automat microfonul corect (preferând USB/Camera),
    cu posibilitate de override în config.json ('preferred_device_index').
    """
    global _MIC_INDEX_CACHE
    if _MIC_INDEX_CACHE is not None and not fortat:
        return _MIC_INDEX_CACHE

    pref_idx = CFG["microphone"].get("preferred_device_index")
    if pref_idx is not None:
        _MIC_INDEX_CACHE = int(pref_idx)
        return _MIC_INDEX_CACHE

    with ignore_stderr():
        lista_microfoane = sr.Microphone.list_microphone_names()

    cuvinte_cheie = CFG["microphone"].get("preferred_keywords", ["USB", "Camera", "Webcam", "Audio", "Mic"])
    candidati = []
    for index, name in enumerate(lista_microfoane):
        nume_mic = name.lower()
        if any(excl in nume_mic for excl in ("hdmi", "bcm2835", "vc4")):
            continue
        scor = 0
        if "usb" in nume_mic or "camera" in nume_mic or "webcam" in nume_mic:
            scor += 10
        elif any(k.lower() in nume_mic for k in cuvinte_cheie):
            scor += 5
        if "hw:" in nume_mic:
            scor += 2
        if scor > 0:
            candidati.append((scor, index, name))

    if candidati:
        candidati.sort(key=lambda x: x[0], reverse=True)
        _MIC_INDEX_CACHE = candidati[0][1]
        nume_ales = candidati[0][2]
        logger.info(f"[MICROFON]: Selectat automat portul {_MIC_INDEX_CACHE}: {nume_ales}")
        _regleaza_gain_hardware_alsa()
        return _MIC_INDEX_CACHE

    logger.warning("[MICROFON]: Nu am găsit microfon USB explicit, folosesc device-ul implicit (None).")
    return None


def deschide_flux_microfon(mic_index=None, chunk_size=512):
    """Deschide microfonul la rata suportată de hardware (8000 Hz sau 16000 Hz) și salvează rata în cache."""
    global _SAMPLE_RATE_CACHE
    if mic_index is None:
        mic_index = _obtine_index_microfon()

    rata_cfg = int(CFG["microphone"].get("sample_rate", 8000))
    rate_incercate = [_SAMPLE_RATE_CACHE] if _SAMPLE_RATE_CACHE else [rata_cfg, 8000, 16000, 44100]

    for r in rate_incercate:
        if not r:
            continue
        try:
            src = sr.Microphone(device_index=mic_index, sample_rate=int(r), chunk_size=chunk_size)
            _SAMPLE_RATE_CACHE = int(r)
            return src
        except Exception:
            continue

    return sr.Microphone(device_index=mic_index, chunk_size=chunk_size)


def obtine_zgomot_ambiental():
    return _ZGOMOT_RMS_AMBIENTAL


def preincalzeste_microfon():
    """Calibrează zgomotul ambiental la pornire sub protecția AUDIO_MIC_LOCK."""
    global _CALIBRAT_INITIAL, _ZGOMOT_RMS_AMBIENTAL
    if _CALIBRAT_INITIAL:
        return
    with AUDIO_MIC_LOCK:
        try:
            mic_index = _obtine_index_microfon()
            with ignore_stderr():
                source = deschide_flux_microfon(mic_index, chunk_size=512)
                with source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.45)
                    zgomot_ambiant = max(120.0, float(recognizer.energy_threshold))
                    _ZGOMOT_RMS_AMBIENTAL = zgomot_ambiant
                    mult = float(CFG["microphone"].get("ambient_multiplier", 1.25))
                    p_min = int(CFG["microphone"].get("min_energy_threshold", 280))
                    p_max = int(CFG["microphone"].get("max_energy_threshold", 3200))
                    recognizer.energy_threshold = max(p_min, min(p_max, int(zgomot_ambiant * mult)))
                    _CALIBRAT_INITIAL = True
            logger.info(
                f"[MICROFON]: Pre-încălzit ({_SAMPLE_RATE_CACHE} Hz | "
                f"Zgomot fond: {int(zgomot_ambiant)} -> Prag voce: {recognizer.energy_threshold})"
            )
        except Exception as e:
            logger.warning(f"[AVERTISMENT PRE-ÎNCĂLZIRE MIC]: {e}")


def proceseaza_semnal_microfon_slab(raw_bytes, sample_rate=8000, target_rms=None, max_gain=None):
    """
    Pipeline DSP pentru microfon USB slab:
    1. Eliminare DC-offset.
    2. Filtru High-Pass IIR de ordinul 1 (~100 Hz) care taie bâzâitul de rețea (50Hz) și zgomotul joase.
    3. Pre-emphasis ușor (0.22) pentru claritatea consoanelor.
    4. Normalizare AGC cu Soft-Limiter fără clipping.
    """
    if not raw_bytes or len(raw_bytes) < 4:
        return raw_bytes
    samples = array("h", raw_bytes)
    n = len(samples)
    if n == 0:
        return raw_bytes

    dc = int(sum(samples) / n)

    # Coeficient High-Pass ~100 Hz: alpha = RC / (RC + dt)
    rc = 1.0 / (2.0 * math.pi * float(CFG["microphone"].get("highpass_cutoff_hz", 100)))
    dt = 1.0 / float(max(8000, sample_rate))
    alpha = rc / (rc + dt)

    hp = [0.0] * n
    prev_x = float(samples[0] - dc)
    prev_y = 0.0
    suma_p = 0.0
    for i in range(n):
        x = float(samples[i] - dc)
        y = alpha * (prev_y + x - prev_x)
        hp[i] = y
        prev_x = x
        prev_y = y
        suma_p += y * y

    rms = math.sqrt(suma_p / float(n)) if n > 0 else 1.0
    t_rms = float(target_rms or CFG["microphone"].get("target_rms", 3200))
    m_gain = float(max_gain or CFG["microphone"].get("max_dsp_gain", 3.5))

    # Noise gate blând: nu amplificăm liniștea pură
    if rms < max(80.0, _ZGOMOT_RMS_AMBIENTAL * 0.45):
        gain = 1.0
    else:
        gain = min(m_gain, max(1.0, t_rms / max(1.0, rms)))

    out = array("h", [0] * n)
    prev_h = hp[0]
    out[0] = max(-32768, min(32767, int(prev_h * gain)))
    for i in range(1, n):
        curr = hp[i]
        boosted = (curr + 0.22 * (curr - prev_h)) * gain
        # Soft-clipping la capete
        if boosted > 29000.0:
            boosted = 29000.0 + (boosted - 29000.0) * 0.25
        elif boosted < -29000.0:
            boosted = -29000.0 + (boosted + 29000.0) * 0.25
        out[i] = max(-32768, min(32767, int(boosted)))
        prev_h = curr

    return out.tobytes()


def _curata_si_amplifica_vocea(audio_data):
    try:
        rata = audio_data.sample_rate or 8000
        raw_bytes = audio_data.get_raw_data(convert_rate=rata, convert_width=2)
        procesat = proceseaza_semnal_microfon_slab(raw_bytes, sample_rate=rata)
        return sr.AudioData(procesat, rata, 2)
    except Exception as e:
        logger.warning(f"Eroare DSP: {e}")
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
    """Ascultă microfonul protejat de AUDIO_MIC_LOCK (fără conflict cu Wake Word-ul)."""
    global _CALIBRAT_INITIAL, _ZGOMOT_RMS_AMBIENTAL

    if on_status:
        on_status("pregatire")

    with AUDIO_MIC_LOCK:
        mic_index = _obtine_index_microfon()
        try:
            with ignore_stderr():
                source = deschide_flux_microfon(mic_index, chunk_size=512)
                with source:
                    if not _CALIBRAT_INITIAL:
                        recognizer.adjust_for_ambient_noise(source, duration=0.35)
                        zgomot = max(120.0, float(recognizer.energy_threshold))
                        _ZGOMOT_RMS_AMBIENTAL = zgomot
                        mult = float(CFG["microphone"].get("ambient_multiplier", 1.25))
                        p_min = int(CFG["microphone"].get("min_energy_threshold", 280))
                        p_max = int(CFG["microphone"].get("max_energy_threshold", 3200))
                        recognizer.energy_threshold = max(p_min, min(p_max, int(zgomot * mult)))
                        _CALIBRAT_INITIAL = True

                    if on_status:
                        on_status("asculta")
                    if DEBUG:
                        logger.info(f"[ROBOT]: Te ascult! ({_SAMPLE_RATE_CACHE} Hz | Prag voce: {recognizer.energy_threshold})")

                    t_rec = time.perf_counter()
                    timeout_s = float(CFG["microphone"].get("listen_timeout", 6.0))
                    limit_s = float(CFG["microphone"].get("phrase_time_limit", 10.0))
                    audio_brut = recognizer.listen(source, timeout=timeout_s, phrase_time_limit=limit_s)
                    durata_rec = time.perf_counter() - t_rec

            if on_status:
                on_status("procesare")

            t_stt = time.perf_counter()
            audio_curat = _curata_si_amplifica_vocea(audio_brut)

            if CFG["microphone"].get("save_debug_wav", False):
                cale_debug = "/dev/shm/debug.wav" if os.path.isdir("/dev/shm") else "debug.wav"
                with open(cale_debug, "wb") as f:
                    f.write(audio_curat.get_wav_data())

            text_ro, scor_ro = _apel_stt_cu_retry(audio_curat, "ro-RO")
            if not text_ro or (scor_ro < 0.55 and len(text_ro.split()) <= 2):
                text_en, scor_en = _apel_stt_cu_retry(audio_curat, "en-US")
                if text_en and scor_en > scor_ro:
                    text_ro = text_en

            if DEBUG:
                logger.info(
                    f"[TIMPI DEBUG]: Captură={durata_rec:.2f}s | "
                    f"STT={time.perf_counter() - t_stt:.2f}s | Text='{text_ro}'"
                )
            return text_ro

        except sr.WaitTimeoutError:
            if DEBUG:
                logger.info("[STT]: Timeout (nu s-a detectat voce).")
            return None
        except Exception as e:
            logger.error(f"[EROARE MICROFON]: {e}")
            global _MIC_INDEX_CACHE
            _MIC_INDEX_CACHE = None
            return None