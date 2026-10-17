import os
import json
import time
import speech_recognition as sr
from ears.listen import ignore_stderr, _obtine_index_microfon

_MODEL_VOSK = None
CALE_MODEL_VOSK = os.path.join(os.path.dirname(__file__), "model_ro")

CUVINTE_ACTIVARE = {"robot", "robotul", "robo", "hei robot", "salut robot"}


def _incarca_model_vosk():
    global _MODEL_VOSK
    if _MODEL_VOSK is not None:
        return _MODEL_VOSK
    if not os.path.isdir(CALE_MODEL_VOSK):
        return None
    from vosk import Model, SetLogLevel
    SetLogLevel(-1)
    _MODEL_VOSK = Model(CALE_MODEL_VOSK)
    return _MODEL_VOSK


def asteapta_wake_word(oprire_event, on_detectat=None):
    """
    Ascultă local/offline cu consum minim de CPU până aude cuvântul 'Robot'.
    Închide fluxul microfonului IMEDIAT ce detectează cuvântul, pentru ca
    asculta_voce() (Google STT) să preia microfonul fără niciun conflict hardware!
    """
    model = _incarca_model_vosk()
    if model is None:
        return False

    from vosk import KaldiRecognizer
    mic_index = _obtine_index_microfon()
    rec = KaldiRecognizer(model, 8000, json.dumps(["robot", "hei robot", "salut robot", "[unk]"]))

    try:
        with ignore_stderr():
            source = sr.Microphone(device_index=mic_index, sample_rate=8000, chunk_size=1024)
            with source:
                while not oprire_event.is_set():
                    date_brut = source.stream.read(1024)
                    if rec.AcceptWaveform(date_brut):
                        rez = json.loads(rec.Result()).get("text", "").strip().lower()
                    else:
                        rez = json.loads(rec.PartialResult()).get("partial", "").strip().lower()

                    if any(w in rez.split() for w in ("robot", "robotul", "robo")):
                        if on_detectat:
                            on_detectat()
                        return True
    except Exception as e:
        print(f"[AVERTISMENT WAKE WORD]: {e}")
        time.sleep(1.0)
    return False