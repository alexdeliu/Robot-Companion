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
CALE_MODEL_VOSK = os.path.join(DIR_EARS, "model_wake")

# URL-urile oficiale verificate de pe serverul AlphaCephei pentru Raspberry Pi (40 MB)
URL_MODELE_BACKUP = [
    "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
    "https://alphacephei.com/kaldi/models/vosk-model-small-en-us-0.15.zip"
]

# Gramatică fonetică restricționată: mapează pronunția românească "/ro-bot/" direct pe țintă
GRAMATICA_WAKE_ROBOT = json.dumps([
    "robot",
    "hey robot",
    "ok robot",
    "row boat",
    "robert",
    "rob",
    "robbie",
    "[unk]"
])

CUVINTE_DECLANSARE = {"robot", "robert", "rob", "robbie", "row", "boat"}


def _descarca_model_backup():
    if os.path.isdir(CALE_MODEL_VOSK):
        return CALE_MODEL_VOSK

    cale_zip = os.path.join(DIR_EARS, "vosk_wake.zip")
    for url in URL_MODELE_BACKUP:
        try:
            print(f"[WAKE WORD]: Descarc modelul vocal offline (40 MB) de la {url}...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as rasp, open(cale_zip, "wb") as f_out:
                f_out.write(rasp.read())

            with zipfile.ZipFile(cale_zip, "r") as zf:
                zf.extractall(DIR_EARS)
            os.remove(cale_zip)

            folder_extras = os.path.join(DIR_EARS, "vosk-model-small-en-us-0.15")
            if os.path.isdir(folder_extras):
                os.rename(folder_extras, CALE_MODEL_VOSK)
            print("[WAKE WORD]: Modelul offline 'Robot' a fost instalat cu succes!")
            return CALE_MODEL_VOSK
        except Exception as e:
            print(f"[AVERTISMENT DOWNLOAD WAKE]: {e}")
            continue
    return None


def _incarca_model_vosk():
    global _MODEL_VOSK, _EROARE_PERMANENTA_VOSK
    if _EROARE_PERMANENTA_VOSK:
        return None
    if _MODEL_VOSK is not None:
        return _MODEL_VOSK

    try:
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)

        # 1. Dacă este deja descărcat în ears/model_wake, îl încărcăm direct
        if os.path.isdir(CALE_MODEL_VOSK):
            _MODEL_VOSK = Model(CALE_MODEL_VOSK)
            return _MODEL_VOSK

        # 2. Folosim descărcătorul oficial Vosk sau arhiva de backup
        cale_locala = _descarca_model_backup()
        if cale_locala and os.path.isdir(cale_locala):
            _MODEL_VOSK = Model(cale_locala)
            return _MODEL_VOSK

        _MODEL_VOSK = Model(lang="en-us")
        return _MODEL_VOSK

    except Exception as e:
        print(f"[AVERTISMENT WAKE WORD]: Nu am putut inițializa Vosk ({e}).")
        _EROARE_PERMANENTA_VOSK = True
        return None


def _converteste_8k_la_16k_amplificat(date_brut_8k):
    """
    Elimină DC-offset-ul camerei web USB, amplifică vocea cu 2.8x
    și convertește fluxul de la 8000 Hz la 16000 Hz pentru Vosk.
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
        out_16k[2 * i] = (prev_val + curr_val) >> 1
        out_16k[2 * i + 1] = curr_val
        prev_val = curr_val

    return out_16k.tobytes()


def _este_detectat_robot(text_auzit):
    if not text_auzit:
        return False
    cuvinte = [c.strip(".,!?-") for c in text_auzit.lower().split()]
    return any(c in CUVINTE_DECLANSARE for c in cuvinte)


def asteapta_wake_word(oprire_event, on_detectat=None):
    """
    Ascultă offline cu gramatică fonetică dedicată cuvântul 'Robot'.
    Închide imediat microfonul când detectează cuvântul pentru a-l preda către Google STT.
    """
    model = _incarca_model_vosk()
    if model is None:
        return False

    from vosk import KaldiRecognizer
    mic_index = _obtine_index_microfon()
    rec = KaldiRecognizer(model, 16000, GRAMATICA_WAKE_ROBOT)

    try:
        with ignore_stderr():
            source = sr.Microphone(device_index=mic_index, sample_rate=8000, chunk_size=1024)
            with source:
                if DEBUG:
                    print("[WAKE WORD]: Ascult activ cuvântul 'Robot'...")
                while not oprire_event.is_set():
                    date_brut = source.stream.read(1024, exception_on_overflow=False)
                    date_16k = _converteste_8k_la_16k_amplificat(date_brut)

                    if rec.AcceptWaveform(date_16k):
                        rez = json.loads(rec.Result()).get("text", "").strip().lower()
                    else:
                        rez = json.loads(rec.PartialResult()).get("partial", "").strip().lower()

                    if rez and rez != "[unk]" and DEBUG:
                        print(f"[WAKE WORD AUZIT]: '{rez}'")

                    if _este_detectat_robot(rez):
                        if DEBUG:
                            print("[WAKE WORD]: 'ROBOT' detectat! Pornesc ascultarea...")
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