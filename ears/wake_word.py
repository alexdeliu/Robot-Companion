import os
import json
import time
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

DIR_EARS = os.path.dirname(os.path.abspath(__file__))
CALE_MODEL_WAKE = os.path.join(DIR_EARS, "model_wake")
CALE_MODEL_RO = os.path.join(DIR_EARS, "model_ro")

URL_MODELE_VOSK = [
    "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
    "https://alphacephei.com/kaldi/models/vosk-model-small-en-us-0.15.zip"
]

# Gramatică fonetică extinsă pentru pronunția românească "/ro-bot/" pe Vosk
GRAMATICA_FONETICA_EXTINSA = json.dumps([
    "robot", "hey robot", "ok robot", "salut robot",
    "robert", "robbie", "rob", "robo",
    "row boat", "row bought", "raw bought", "rah bought",
    "roar boat", "rabat", "rub out", "about", "boat",
    "[unk]"
])


def _obtine_lista_declansare():
    custom = CFG.get("wake_word", {}).get("custom_triggers", [])
    baza = {
        "robot", "robotul", "robotule", "robote", "robo", "robert", "robbie",
        "rob", "ropot", "rombot", "raw bought", "row boat", "row bought",
        "rah bought", "roar boat", "rabat", "rub out", "hey robot", "ok robot"
    }
    for c in custom:
        baza.add(c.lower().strip())
    return baza


def potrivire_fuzzy_robot(text_auzit):
    """
    Verifică atât potrivirea exactă/fonetică, cât și distanța Levenshtein (fuzzy)
    pentru variații de pronunție românească a cuvântului 'robot'.
    """
    if not text_auzit:
        return False
    text_curat = text_auzit.lower().strip()
    if not text_curat or text_curat == "[unk]":
        return False

    declansatori = _obtine_lista_declansare()
    if text_curat in declansatori:
        return True

    cuvinte = [c.strip(".,!?-") for c in text_curat.split() if c.strip(".,!?-")]
    prag_fuzzy = float(CFG.get("wake_word", {}).get("fuzzy_threshold", 0.72))

    # Verificăm expresii din 2 cuvinte (ex: "raw bought", "row boat")
    for i in range(len(cuvinte) - 1):
        bigram = f"{cuvinte[i]} {cuvinte[i + 1]}"
        if bigram in declansatori:
            return True

    tinte_scurte = ("robot", "robo", "robert", "robote", "ropot")
    for cuv in cuvinte:
        if cuv in declansatori or cuv.startswith("robot") or cuv.startswith("robo"):
            return True
        if len(cuv) >= 4:
            for tinta in tinte_scurte:
                scor = difflib.SequenceMatcher(None, cuv, tinta).ratio()
                if scor >= prag_fuzzy:
                    return True
    return False


def _converteste_la_16k_dsp(raw_bytes, sample_rate_intrare=8000):
    """Aplică filtrul High-Pass + AGC și face upsampling rapid la 16000 Hz pentru Vosk/OWW."""
    gain_cfg = float(CFG.get("wake_word", {}).get("vosk_gain", 3.0))
    curat = proceseaza_semnal_microfon_slab(raw_bytes, sample_rate=sample_rate_intrare, max_gain=gain_cfg)
    if sample_rate_intrare == 16000:
        return curat

    samples_8k = array("h", curat)
    n = len(samples_8k)
    if n == 0:
        return curat

    out_16k = array("h", [0] * (n * 2))
    prev = samples_8k[0]
    for i in range(n):
        curr = samples_8k[i]
        out_16k[2 * i] = (prev + curr) >> 1
        out_16k[2 * i + 1] = curr
        prev = curr
    return out_16k.tobytes()


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
        logger.warning(f"[WAKE WORD]: Vosk indisponibil ({e}), voi folosi strategia de fallback.")
        _EROARE_VOSK = True
    return None


def _incarca_openwakeword():
    global _OWW_MODEL, _EROARE_OWW
    if _EROARE_OWW:
        return None
    if _OWW_MODEL is not None:
        return _OWW_MODEL
    try:
        import openwakeword
        from openwakeword.model import Model as OWWModel
        _OWW_MODEL = OWWModel()
        return _OWW_MODEL
    except Exception:
        _EROARE_OWW = True
        return None


def _este_robotul_in_vorbire():
    """Evită auto-declanșarea cât timp robotul vorbește sau imediat după."""
    try:
        from voice.speak import este_vorbire_activa, timp_de_la_ultima_vorbire
        cooldown = float(CFG.get("wake_word", {}).get("ignore_after_speak_sec", 0.9))
        if este_vorbire_activa() or timp_de_la_ultima_vorbire() < cooldown:
            return True
    except Exception:
        pass
    return False


def obtine_strategie_activa():
    return _STRATEGIE_ACTIVA or "auto"


def asteapta_wake_word(oprire_event, on_detectat=None):
    """
    Lanț de detecție Wake Word cu fallback automat:
    1. 'vosk_phonetic': Vosk offline 16kHz + Gramatică fonetică extinsă + Fuzzy matching.
    2. 'openwakeword': Dacă biblioteca openwakeword este instalată.
    3. 'energy_vad_stt': Detecție acustică de energie (VAD) + verificare scurtă STT cu potrivire fuzzy.
    """
    global _STRATEGIE_ACTIVA

    # Așteptăm dacă robotul încă vorbește (prevenire auto-declanșare)
    while not oprire_event.is_set() and _este_robotul_in_vorbire():
        time.sleep(0.15)
    if oprire_event.is_set():
        return False

    pref = CFG.get("wake_word", {}).get("preferred_strategy", "auto")
    ordine = CFG.get("wake_word", {}).get("strategies_order", ["vosk_phonetic", "openwakeword", "energy_vad_stt"])
    if pref != "auto" and pref in ordine:
        strategii = [pref] + [s for s in ordine if s != pref]
    else:
        strategii = ordine

    for strat in strategii:
        if oprire_event.is_set():
            return False

        # --- STRATEGIA 1: VOSK PHONETIC + FUZZY ---
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
                        with source:
                            while not oprire_event.is_set():
                                if _este_robotul_in_vorbire():
                                    rec.Reset()
                                    time.sleep(0.1)
                                    continue

                                date_brut = source.stream.read(1024, exception_on_overflow=False)
                                rms = calculeaza_rms_pcm16(date_brut)
                                date_16k = _converteste_la_16k_dsp(date_brut, sample_rate_intrare=rata_hw)

                                if rec.AcceptWaveform(date_16k):
                                    rez = json.loads(rec.Result()).get("text", "").strip().lower()
                                else:
                                    rez = json.loads(rec.PartialResult()).get("partial", "").strip().lower()

                                if rez and rez != "[unk]":
                                    if DEBUG:
                                        logger.debug(f"[WAKE VOSK]: auzit='{rez}' (RMS={int(rms)})")
                                    if potrivire_fuzzy_robot(rez):
                                        logger.info(f"[WAKE WORD]: Declanșat prin Vosk ('{rez}')!")
                                        break
                if not oprire_event.is_set():
                    if on_detectat:
                        on_detectat()
                    return True
            except Exception as e:
                logger.warning(f"[WAKE WORD]: Eroare în strategia vosk_phonetic ({e}), trec pe următoarea...")
                continue

        # --- STRATEGIA 2: OPENWAKEWORD (DACĂ ESTE INSTALAT) ---
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
                        with source:
                            while not oprire_event.is_set():
                                if _este_robotul_in_vorbire():
                                    time.sleep(0.1)
                                    continue
                                date_brut = source.stream.read(1024, exception_on_overflow=False)
                                date_16k = _converteste_la_16k_dsp(date_brut, sample_rate_intrare=rata_hw)
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

        # --- STRATEGIA 3: ENERGY VAD + SHORT STT FUZZY MATCH (FALLBACK UNIVERSAL) ---
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
                                float(CFG["wake_word"].get("min_trigger_rms", 260)),
                                obtine_zgomot_ambiental() * float(CFG["wake_word"].get("sensitivity_rms_ratio", 1.35))
                            )
                            while not oprire_event.is_set():
                                if _este_robotul_in_vorbire():
                                    time.sleep(0.1)
                                    continue
                                date_brut = source.stream.read(1024, exception_on_overflow=False)
                                rms = calculeaza_rms_pcm16(date_brut)
                                if rms >= prag_rms:
                                    # Am detectat începutul unui cuvânt: capturăm 1.3 secunde
                                    cadre = [date_brut]
                                    nr_pachete = max(6, int((rata_hw / 1024.0) * 1.3))
                                    for _ in range(nr_pachete):
                                        if oprire_event.is_set():
                                            break
                                        cadre.append(source.stream.read(1024, exception_on_overflow=False))
                                    raw_total = b"".join(cadre)
                                    proc = proceseaza_semnal_microfon_slab(raw_total, sample_rate=rata_hw)
                                    audio_scurt = sr.AudioData(proc, rata_hw, 2)
                                    try:
                                        txt = recognizer.recognize_google(audio_scurt, language="ro-RO").strip().lower()
                                        if DEBUG and txt:
                                            logger.debug(f"[WAKE VAD-STT]: '{txt}'")
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