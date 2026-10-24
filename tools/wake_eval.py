import os
import sys
import glob
import json
import time
import wave
import speech_recognition as sr

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ears.listen import calculeaza_rms_pcm16, proceseaza_semnal_microfon_slab
from ears.wake_word import (
    _incarca_vosk,
    _StreamDSP16k,
    GRAMATICA_FONETICA_EXTINSA,
    potrivire_fuzzy_robot
)


def evalueaza_fisier_wav(cale_wav, model_vosk, rec_stt):
    with wave.open(cale_wav, "rb") as wf:
        rata = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    rms_med = int(calculeaza_rms_pcm16(raw))
    t0 = time.perf_counter()
    vosk_trig = False
    vosk_txt = []

    if model_vosk:
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(model_vosk, 16000, GRAMATICA_FONETICA_EXTINSA)
        dsp = _StreamDSP16k(sample_rate_in=rata)
        pas = 2048
        for i in range(0, len(raw), pas):
            c16 = dsp.proceseaza_chunk(raw[i:i + pas])
            if rec.AcceptWaveform(c16):
                t = json.loads(rec.Result()).get("text", "").strip()
                if t:
                    vosk_txt.append(t)
                    if potrivire_fuzzy_robot(t):
                        vosk_trig = True
            else:
                p = json.loads(rec.PartialResult()).get("partial", "").strip()
                if p and potrivire_fuzzy_robot(p):
                    vosk_trig = True
        fin = json.loads(rec.FinalResult()).get("text", "").strip()
        if fin:
            vosk_txt.append(fin)
            if potrivire_fuzzy_robot(fin):
                vosk_trig = True
    lat_vosk_ms = int((time.perf_counter() - t0) * 1000)

    t1 = time.perf_counter()
    stt_txt = ""
    stt_trig = False
    try:
        proc = proceseaza_semnal_microfon_slab(raw, sample_rate=rata)
        aud = sr.AudioData(proc, rata, 2)
        stt_txt = rec_stt.recognize_google(aud, language="ro-RO").strip().lower()
        stt_trig = potrivire_fuzzy_robot(stt_txt)
    except Exception:
        pass
    lat_stt_ms = int((time.perf_counter() - t1) * 1000)

    return {
        "fisier": os.path.basename(cale_wav),
        "rate": rata,
        "rms": rms_med,
        "vosk_ok": vosk_trig,
        "vosk_heard": " ".join(vosk_txt),
        "vosk_ms": lat_vosk_ms,
        "stt_ok": stt_trig,
        "stt_heard": stt_txt,
        "stt_ms": lat_stt_ms
    }


def main():
    tinta = sys.argv[1] if len(sys.argv) > 1 else "/tmp"
    fisiere = [tinta] if os.path.isfile(tinta) else sorted(glob.glob(os.path.join(tinta, "*.wav")))
    if not fisiere:
        print(f"Niciun fișier .wav găsit în '{tinta}'.")
        print("Înregistrează cu: arecord -D plughw:2,0 -f S16_LE -r 8000 -c 1 -d 3 /tmp/robot_1.wav")
        return

    model_v = _incarca_vosk()
    rec_g = sr.Recognizer()
    print("=" * 82)
    print(f"{'FISIER WAV':<20} | {'RMS':<5} | {'VOSK':<5} | {'VOSK AUZIT':<18} | {'STT':<5} | {'LAT(ms)'}")
    print("-" * 82)
    for f in fisiere:
        r = evalueaza_fisier_wav(f, model_v, rec_g)
        print(
            f"{r['fisier'][:20]:<20} | {r['rms']:<5} | "
            f"{'DA' if r['vosk_ok'] else 'NU':<5} | {r['vosk_heard'][:18]:<18} | "
            f"{'DA' if r['stt_ok'] else 'NU':<5} | V:{r['vosk_ms']} / S:{r['stt_ms']}"
        )
    print("=" * 82)


if __name__ == "__main__":
    main()