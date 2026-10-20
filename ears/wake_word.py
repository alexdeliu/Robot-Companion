import os
import json
import time
import zipfile
import urllib.request
from array import array
import speech_recognition as sr
from ears.listen import ignore_stderr, _obtine_index_microfon

DEBUG = os.getenv("DEBUG", "1") == "1"

_MODEL_VOSK = None
_EROARE_PERMANENTA_VOSK = False
DIR_EARS = os.path.dirname(__file__)
CALE_MODEL_VOSK = os.path.join(DIR_EARS, "model_ro")
URL_MODEL_VOSK_RO = "https://alphacephei.com/vosk/models/vosk-model-small-ro-0.4.zip"

# Toate formele fonetice pe care Vosk le poate transcrie când strigi "Robot" în cameră
CUVINTE_TINTA_ROBOT = {
    "robot", "robotul", "robotule", "robote", "robo",
    "robert", "ropot", "rombot", "rob", "robbie"
}


def _asigura_model_vosk_romana():
    if os.path.isdir(CALE_MODEL_VOSK):
        return True
    try:
        print("[WAKE WORD]: Descarc modelul vocal offline pentru limba română (~40 MB)...")
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
        print("[INFO WAKE WORD]: Librăria 'vosk' nu este instalată (pip install vosk).")
        _EROARE_PERMANENTA_VOSK = True
        return None
    except Exception as e:
        print(f"[AVERTISMENT WAKE WORD]: Eroare la încărcarea modelului ({e}).")
        _EROARE_PERMANENTA_VOSK = True
        return None


def _converteste_8k_la_16k_amplificat(date_brut_8k):
    """
    Camera web USB înregistrează la 8000 Hz cu DC-offset, dar modelul Vosk RO
    este antrenat la 16000 Hz!
    Această funcție elimină DC-offset-ul, amplifică vocea cu 2.8x și dublează
    eșantioanele (interpolare liniară 8kHz -> 16kHz) în <0.1ms!
    """
    samples_8k = array("h", date_brut_8k)
    n = len(samples_8k)
    if n == 0:
        return date_brut_8k

    dc = int(sum(samples_8k) / n)
    out_16k = array("h", [0] * (n * 2))
    gain = 2.8

    prev_val = max(-32768, min(32767, int((samples_8k[0] - dc) * gain)))
    for i in range(n):
        curr_val = max(-32768, min(32767, int((samples_8k[i] - dc) * gain)))
        mid_val = (prev_val + curr_val) >> 1
        out_16k[2 * i] = mid_val
        out_16k[2 * i + 1] = curr_val
        prev_val = curr_val

    return out_16k.tobytes()


def _contine_cuvant_robot(text_auzit):
    if not text_auzit:
        return False
    for cuv in text_auzit.lower().split():
        cuv_curat = cuv.strip(".,!?-")
        if cuv_curat in CUVINTE_TINTA_ROBOT or cuv_curat.startswith("robot"):
            return True
    return False


def asteapta_wake_word(oprire_event, on_detectat=None):
    """
    Ascultă în buclă continuă cuvântul 'Robot' (convertit la 16000 Hz pentru modelul Vosk).
    Eliberează imediat microfonul când aude 'Robot' sau când utilizatorul apasă pe MIC.
    """
    model = _incarca_model_vosk()
    if model is None:
        return False

    from vosk import KaldiRecognizer
    mic_index = _obtine_index_microfon()
    # Folosim 16000 Hz (frecvența nativă a modelului vosk-model-small-ro-0.4)
    rec = KaldiRecognizer(model, 16000)

    try:
        with ignore_stderr():
            source = sr.Microphone(device_index=mic_index, sample_rate=8000, chunk_size=1024)
            with source:
                if DEBUG:
                    print("[WAKE WORD]: Ascult activ în fundal cuvântul 'Robot'...")
                while not oprire_event.is_set():
                    date_brut = source.stream.read(1024, exception_on_overflow=False)
                    date_16k = _converteste_8k_la_16k_amplificat(date_brut)

                    if rec.AcceptWaveform(date_16k):
                        rez = json.loads(rec.Result()).get("text", "").strip().lower()
                    else:
                        rez = json.loads(rec.PartialResult()).get("partial", "").strip().lower()

                    if rez and DEBUG and len(rez) > 2:
                        print(f"[WAKE WORD AUZIT]: '{rez}'")

                    if _contine_cuvant_robot(rez):
                        if DEBUG:
                            print("[WAKE WORD]: Cuvântul 'ROBOT' a fost detectat! Activez ascultarea...")
                        break

        if not oprire_event.is_set():
            if on_detectat:
                on_detectat()
            return True
    except Exception as e:
        if DEBUG:
            print(f"[AVERTISMENT STREAM WAKE WORD]: {e}")
        time.sleep(0.4)
    return False