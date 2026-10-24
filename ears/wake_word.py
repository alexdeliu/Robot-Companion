import os
import json
import time
import math
import zipfile
import difflib
import urllib.request
from array import array
import speech_recognition as sr

from config import CFG, DEBUG
from system_health import logger
from ears.listen import (
    AUDIO_MIC_LOCK,
    ignore_stderr,
    _obtine_index_microfon,
    deschide_flux_microfon,
    calculeaza_rms_pcm16,
    proceseaza_semnal_microfon_slab,
    obtine_zgomot_ambiental,
    recognizer
)

_MODEL_VOSK = None
_OWW_MODEL = None
_STRATEGIE_ACTIVA = None
_EROARE_VOSK = False
_EROARE_OWW = False
_CALLBACK_DEBUG_UI = None

DIR_EARS = os.path.dirname(os.path.abspath(__file__))
CALE_MODEL_WAKE = os.path.join(DIR_EARS, "model_wake")
CALE_MODEL_RO = os.path.join(DIR_EARS, "model_ro")

URL_MODELE_VOSK = [
    "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
    "https://alphacephei.com/kaldi/models/vosk-model-small-en-us-0.15.zip"
]

# Toate cuvintele de mai jos există garantat în words.txt al vosk-model-small-en-us-0.15
# (fără 'salut' care provoca avertisment în UpdateGrammarFst!)
GRAMATICA_FONETICA_EXTINSA = json.dumps([
    "robot", "robots", "hey", "ok", "okay", "oh", "hi", "hello",
    "robert", "robbie", "rob", "robin",
    "row", "raw", "roar", "boat", "bought", "about", "but", "out", "rub",
    "[unk]"
])


def seteaza_callback_debug_wake(cb):
    global _CALLBACK_DEBUG_UI
    _CALLBACK_DEBUG_UI = cb


def _notifica_ui_wake(text_status):
    if _CALLBACK_DEBUG_UI and CFG.get("wake_word", {}).get("debug_wake_in_ui", True):
        try:
            _CALLBACK_DEBUG_UI(text_status)
        except Exception as e:
            logger.debug(f"[WAKE UI CALLBACK]: {e}")


def _obtine_lista_declansare():
    custom = CFG.get("wake_word", {}).get("custom_triggers", [])
    baza = {
        "robot", "robots", "robotul", "robotule", "robote", "robo", "robert",
        "robbie", "rob", "robin", "ropot", "rombot", "raw bought", "row boat",
        "row bought", "rah bought", "roar boat", "rabat", "rub out", "oh bought",
        "row but", "raw but", "hey robot", "ok robot", "okay robot", "hi robot"
    }
    for c in custom:
        baza.add(c.lower().strip())
    return baza


def potrivire_fuzzy_robot(text_auzit):
    if not text_auzit:
        return False
    text_curat = text_auzit.lower().strip()
    if not text_curat or text_curat == "[unk]":
        return False

    declansatori = _obtine_lista_declansare()
    if text_curat in declansatori:
        return True

    cuvinte = [c.strip(".,!?-") for c in text_curat.split() if c.strip(".,!?-")]
    prag_fuzzy = float(CFG.get("wake_word", {}).get("fuzzy_threshold", 0.70))

    for i in range(len(cuvinte) - 1):
        bigram = f"{cuvinte[i]} {cuvinte[i + 1]}"
        if bigram in declansatori:
            return True

    tinte_scurte = ("robot", "robo", "robert", "robote", "ropot", "robin")
    for cuv in cuvinte:
        if cuv in declansatori or cuv.startswith("robot") or cuv.startswith("robo"):
            return True
        if len(cuv) >= 4:
            for tinta in tinte_scurte:
                if difflib.SequenceMatcher(None, cuv, tinta).ratio() >= prag_fuzzy:
                    return True
    return False


class _StreamDSP16k:
    """
    Filtru High-Pass 100 Hz + Gain constant + Upsampler 8kHz -> 16kHz CU STARE CONTINUĂ
    între pachete (elimină clicurile la fiecare 64ms care stricau recunoașterea Vosk).
    """
    def __init__(self, sample_rate_in=8000):
        self.rate_in = max(8000, int(sample_rate_in))
        cutoff = float(CFG.get("microphone", {}).get("highpass_cutoff_hz", 100))
        rc = 1.0 / (2.0 * math.pi * cutoff)
        dt = 1.0 / float(self.rate_in)
        self.alpha = rc / (rc + dt)
        self.gain = float(CFG.get("wake_word", {}).get("vosk_gain", 3.2))
        self.dc_est = 0.0
        self.prev_x = 0.0
        self.prev_y = 0.0
        self.prev_s16 = 0

    def proceseaza_chunk(self, raw_bytes):
        if not raw_bytes or len(raw_bytes) < 2:
            return raw_bytes
        samples = array("h", raw_bytes)
        n = len(samples)
        if n == 0:
            return raw_bytes

        medie_chunk = sum(samples) / float(n)
        self.dc_est = 0.90 * self.dc_est + 0.10 * medie_chunk
        alpha = self.alpha
        gain = self.gain
        px = self.prev_x
        py = self.prev_y

        procesate = array("h", [0] * n)
        for i in range(n):
            x = float(samples[i]) - self.dc_est
            y = alpha * (py + x - px)
            px = x
            py = y
            val = y * gain
            if val > 29000.0:
                val = 29000.0 + (val - 29000.0) * 0.25
            elif val < -29000.0:
                val = -29000.0 + (val + 29000.0) * 0.25
            procesate[i] = max(-32768, min(32767, int(val)))

        self.prev_x = px
        self.prev_y = py

        if self.rate_in == 16000:
            return procesate.tobytes()

        out_16k = array("h", [0] * (n * 2))
        prev_s = self.prev_s16
        for i in range(n):
            curr_s = procesate[i]
            out_16k[2 * i] = (prev_s + curr_s) >> 1
            out_16k[2 * i + 1] = curr_s
            prev_s = curr_s
        self.prev_s16 = prev_s
        return out_16k.tobytes()


def _converteste_la_16k_dsp(raw_bytes, sample_rate_intrare=8000):
    dsp = _StreamDSP16k(sample_rate_in=sample_rate_intrare)
    return dsp.proceseaza_chunk(raw_bytes)


def _incarca_vosk():
    global _MODEL_VOSK, _EROARE_VOSK
    if _EROARE_VOSK:
        return None
    if _MODEL_VOSK is not None:
        return _MODEL_VOSK

    try:
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)

        for folder in (CALE_MODEL_RO, CALE_MODEL_WAKE):
            if os.path.isdir(folder):
                _MODEL_VOSK = Model(folder)
                return _MODEL_VOSK

        cale_zip = os.path.join(DIR_EARS, "vosk_wake.zip")
        for url in URL_MODELE_VOSK:
            try:
                logger.info(f"[WAKE WORD]: Descarc modelul Vosk (40 MB) de la {url}...")
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=25) as r, open(cale_zip, "wb") as f_out:
                    f_out.write(r.read())
                with zipfile.ZipFile(cale_zip, "r") as zf:
                    zf.extractall(DIR_EARS)
                os.remove(cale_zip)
                extras = os.path.join(DIR_EARS, "vosk-model-small-en-us-0.15")
                if os.path.isdir(extras):
                    os.rename(extras, CALE_MODEL_WAKE)
                _MODEL_VOSK = Model(CALE_MODEL_WAKE)
                logger.info("[WAKE WORD]: Model Vosk pregătit!")
                return _MODEL_VOSK
            except Exception as e:
                logger.warning(f"[WAKE WORD]: Eșec descărcare {url}: {e}")
    except Exception as e:
        logger.warning(f"[WAKE WORD]: Vosk indisponibil ({e}), trec pe fallback.")
        _EROARE_VOSK = True
    return None


def _incarca_openwakeword():
    global _OWW_MODEL, _EROARE_OWW
    if _EROARE_OWW:
        return None
    if _OWW_MODEL is not None:
        return _OWW_MODEL
    try:
        from openwakeword.model import Model as OWWModel
        _OWW_MODEL = OWWModel()
        return _OWW_MODEL
    except Exception:
        _EROARE_OWW = True
        return None


def _este_robotul_in_vorbire():
    try:
        from voice.speak import este_vorbire_activa, timp_de_la_ultima_vorbire
        cooldown = float(CFG.get("wake_word", {}).get("ignore_after_speak_sec", 0.9))
        if este_vorbire_activa() or timp_de_la_ultima_vorbire() < cooldown:
            return True
    except Exception as e:
        logger.debug(f"[WAKE SPEAK CHECK]: {e}")
    return False


def obtine_strategie_activa():
    return _STRATEGIE_ACTIVA or "auto"


def asteapta_wake_word(oprire_event, on_detectat=None):
    global _STRATEGIE_ACTIVA

    while not oprire_event.is_set() and _este_robotul_in_vorbire():
        time.sleep(0.15)
    if oprire_event.is_set():
        return False

    pref = CFG.get("wake_word", {}).get("preferred_strategy", "auto")
    ordine = CFG.get("wake_word", {}).get("strategies_order", ["vosk_phonetic", "openwakeword", "energy_vad_stt"])
    strategii = ([pref] + [s for s in ordine if s != pref]) if (pref != "auto" and pref in ordine) else ordine
    interval_telem = float(CFG.get("wake_word", {}).get("telemetry_interval_sec", 5.0))

    for strat in strategii:
        if oprire_event.is_set():
            return False

        # --- STRATEGIA 1: VOSK PHONETIC + FUZZY (CU TELEMETRIE LA 5 SECUNDE) ---
        if strat == "vosk_phonetic":
            model = _incarca_vosk()
            if model is None:
                continue
            _STRATEGIE_ACTIVA = "vosk_phonetic"
            from vosk import KaldiRecognizer
            rec = KaldiRecognizer(model, 16000, GRAMATICA_FONETICA_EXTINSA)
            try:
                with AUDIO_MIC_LOCK:
                    if oprire_event.is_set():
                        return False
                    mic_index = _obtine_index_microfon()
                    with ignore_stderr():
                        source = deschide_flux_microfon(mic_index, chunk_size=1024)
                        rata_hw = source.SAMPLE_RATE or 8000
                        dsp_stream = _StreamDSP16k(sample_rate_in=rata_hw)
                        with source:
                            t_raport = time.monotonic()
                            nr_cadre = 0
                            rms_list = []
                            ultimul_text = ""

                            while not oprire_event.is_set():
                                if _este_robotul_in_vorbire():
                                    rec.Reset()
                                    time.sleep(0.1)
                                    continue

                                # FĂRĂ exception_on_overflow=False (cauza dovedită a crash-ului TypeError!)
                                date_brut = source.stream.read(1024)
                                nr_cadre += 1
                                rms = calculeaza_rms_pcm16(date_brut)
                                rms_list.append(rms)
                                date_16k = dsp_stream.proceseaza_chunk(date_brut)

                                if rec.AcceptWaveform(date_16k):
                                    rez = json.loads(rec.Result()).get("text", "").strip().lower()
                                else:
                                    rez = json.loads(rec.PartialResult()).get("partial", "").strip().lower()

                                if rez and rez != "[unk]":
                                    ultimul_text = rez
                                    if DEBUG:
                                        logger.debug(f"[WAKE VOSK]: auzit='{rez}' (RMS={int(rms)})")
                                    _notifica_ui_wake(f"Mic RMS:{int(rms)} | Auzit: '{rez}'")
                                    if potrivire_fuzzy_robot(rez):
                                        logger.info(f"[WAKE WORD]: Declanșat prin Vosk ('{rez}', RMS={int(rms)})!")
                                        break

                                acum_m = time.monotonic()
                                if acum_m - t_raport >= interval_telem and rms_list:
                                    r_min = int(min(rms_list))
                                    r_med = int(sum(rms_list) / len(rms_list))
                                    r_max = int(max(rms_list))
                                    logger.info(
                                        f"[WAKE TELEMETRY]: strat=vosk_phonetic | frames={nr_cadre} | "
                                        f"RMS(min/avg/max)={r_min}/{r_med}/{r_max} | last='{ultimul_text}'"
                                    )
                                    _notifica_ui_wake(f"Wake: ON (RMS max:{r_max} | '{ultimul_text or '...'}')")
                                    t_raport = acum_m
                                    nr_cadre = 0
                                    rms_list.clear()

                if not oprire_event.is_set():
                    if on_detectat:
                        on_detectat()
                    return True
            except Exception as e:
                logger.warning(f"[WAKE WORD]: Eroare în vosk_phonetic ({e}), trec pe următoarea strategie...")
                continue

        # --- STRATEGIA 2: OPENWAKEWORD ---
        elif strat == "openwakeword":
            oww = _incarca_openwakeword()
            if oww is None:
                continue
            _STRATEGIE_ACTIVA = "openwakeword"
            try:
                import numpy as np
                with AUDIO_MIC_LOCK:
                    mic_index = _obtine_index_microfon()
                    with ignore_stderr():
                        source = deschide_flux_microfon(mic_index, chunk_size=1024)
                        rata_hw = source.SAMPLE_RATE or 8000
                        dsp_stream = _StreamDSP16k(sample_rate_in=rata_hw)
                        with source:
                            while not oprire_event.is_set():
                                if _este_robotul_in_vorbire():
                                    time.sleep(0.1)
                                    continue
                                date_brut = source.stream.read(1024)
                                date_16k = dsp_stream.proceseaza_chunk(date_brut)
                                arr = np.frombuffer(date_16k, dtype=np.int16)
                                pred = oww.predict(arr)
                                if any(v >= 0.5 for v in pred.values()):
                                    logger.info("[WAKE WORD]: Declanșat prin openWakeWord!")
                                    break
                if not oprire_event.is_set():
                    if on_detectat:
                        on_detectat()
                    return True
            except Exception as e:
                logger.warning(f"[WAKE WORD]: Eroare openWakeWord ({e}), trec pe următoarea...")
                continue

        # --- STRATEGIA 3: ENERGY VAD + SHORT STT FUZZY MATCH ---
        elif strat == "energy_vad_stt":
            _STRATEGIE_ACTIVA = "energy_vad_stt"
            try:
                with AUDIO_MIC_LOCK:
                    if oprire_event.is_set():
                        return False
                    mic_index = _obtine_index_microfon()
                    with ignore_stderr():
                        source = deschide_flux_microfon(mic_index, chunk_size=1024)
                        rata_hw = source.SAMPLE_RATE or 8000
                        with source:
                            prag_rms = max(
                                float(CFG["wake_word"].get("min_trigger_rms", 240)),
                                obtine_zgomot_ambiental() * float(CFG["wake_word"].get("sensitivity_rms_ratio", 1.35))
                            )
                            t_raport = time.monotonic()
                            rms_list = []
                            while not oprire_event.is_set():
                                if _este_robotul_in_vorbire():
                                    time.sleep(0.1)
                                    continue
                                date_brut = source.stream.read(1024)
                                rms = calculeaza_rms_pcm16(date_brut)
                                rms_list.append(rms)

                                if time.monotonic() - t_raport >= interval_telem and rms_list:
                                    logger.info(
                                        f"[WAKE TELEMETRY]: strat=energy_vad_stt | "
                                        f"RMS(max)={int(max(rms_list))}/prag={int(prag_rms)}"
                                    )
                                    t_raport = time.monotonic()
                                    rms_list.clear()

                                if rms >= prag_rms:
                                    cadre = [date_brut]
                                    nr_pachete = max(6, int((rata_hw / 1024.0) * 1.2))
                                    for _ in range(nr_pachete):
                                        if oprire_event.is_set():
                                            break
                                        cadre.append(source.stream.read(1024))
                                    raw_total = b"".join(cadre)
                                    proc = proceseaza_semnal_microfon_slab(raw_total, sample_rate=rata_hw)
                                    audio_scurt = sr.AudioData(proc, rata_hw, 2)
                                    try:
                                        txt = recognizer.recognize_google(audio_scurt, language="ro-RO").strip().lower()
                                        if DEBUG and txt:
                                            logger.info(f"[WAKE VAD-STT]: auzit='{txt}'")
                                        _notifica_ui_wake(f"VAD-STT: '{txt}'")
                                        if potrivire_fuzzy_robot(txt):
                                            logger.info(f"[WAKE WORD]: Declanșat prin VAD-STT ('{txt}')!")
                                            break
                                    except Exception:
                                        continue
                if not oprire_event.is_set():
                    if on_detectat:
                        on_detectat()
                    return True
            except Exception as e:
                logger.warning(f"[WAKE WORD]: Eroare VAD-STT ({e}).")
                time.sleep(0.4)

    return False