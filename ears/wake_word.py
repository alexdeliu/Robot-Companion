import os
import json
import time
import zipfile
import urllib.request
import speech_recognition as sr
from ears.listen import ignore_stderr, _obtine_index_microfon

_MODEL_VOSK = None
_EROARE_PERMANENTA_VOSK = False
DIR_EARS = os.path.dirname(__file__)
CALE_MODEL_VOSK = os.path.join(DIR_EARS, "model_ro")
URL_MODEL_VOSK_RO = "https://alphacephei.com/vosk/models/vosk-model-small-ro-0.4.zip"


def _asigura_model_vosk_romana():
    if os.path.isdir(CALE_MODEL_VOSK):
        return True
    try:
        print("[WAKE WORD]: Descarc modelul vocal offline pentru limba română (40 MB, doar la prima rulare)...")
        cale_zip = os.path.join(DIR_EARS, "vosk_ro.zip")
        urllib.request.urlretrieve(URL_MODEL_VOSK_RO, cale_zip)
        with zipfile.ZipFile(cale_zip, "r") as zf:
            zf.extractall(DIR_EARS)
        os.remove(cale_zip)
        folder_extras = os.path.join(DIR_EARS, "vosk-model-small-ro-0.4")
        if os.path.isdir(folder_extras):
            os.rename(folder_extras, CALE_MODEL_VOSK)
        print("[WAKE WORD]: Modelul offline 'Robot' a fost instalat cu succes!")
        return True
    except Exception as e:
        print(f"[AVERTISMENT WAKE WORD]: Nu am putut descărca modelul Vosk ({e}).")
        return False


def _incarca_model_vosk():
    global _MODEL_VOSK, _EROARE_PERMANENTA_VOSK
    if _EROARE_PERMANENTA_VOSK:
        return None
    if _MODEL_VOSK is not None:
        return _MODEL_VOSK
    try:
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        if not _asigura_model_vosk_romana():
            _EROARE_PERMANENTA_VOSK = True
            return None
        _MODEL_VOSK = Model(CALE_MODEL_VOSK)
        return _MODEL_VOSK
    except ImportError:
        print("[INFO WAKE WORD]: Librăria 'vosk' nu este instalată (pip install vosk). Folosesc doar butonul MIC.")
        _EROARE_PERMANENTA_VOSK = True
        return None
    except Exception as e:
        print(f"[AVERTISMENT WAKE WORD]: {e}")
        _EROARE_PERMANENTA_VOSK = True
        return None


def asteapta_wake_word(oprire_event, on_detectat=None):
    model = _incarca_model_vosk()
    if model is None:
        return False

    from vosk import KaldiRecognizer
    mic_index = _obtine_index_microfon()
    gramatica = json.dumps(["robot", "hei robot", "salut robot", "ok robot", "[unk]"])
    rec = KaldiRecognizer(model, 8000, gramatica)

    try:
        with ignore_stderr():
            source = sr.Microphone(device_index=mic_index, sample_rate=8000, chunk_size=1024)
            with source:
                while not oprire_event.is_set():
                    date_brut = source.stream.read(1024, exception_on_overflow=False)
                    if rec.AcceptWaveform(date_brut):
                        rez = json.loads(rec.Result()).get("text", "").strip().lower()
                    else:
                        rez = json.loads(rec.PartialResult()).get("partial", "").strip().lower()

                    cuvinte = rez.split()
                    if any(w in cuvinte for w in ("robot", "robotul", "robo")):
                        break

        if not oprire_event.is_set():
            if on_detectat:
                on_detectat()
            return True
    except Exception:
        time.sleep(0.5)
    return False