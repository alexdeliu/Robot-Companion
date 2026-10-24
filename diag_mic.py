import os
import sys
import time
import json
import wave
import speech_recognition as sr

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(BASE_DIR) == "tools":
    BASE_DIR = os.path.dirname(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ears.listen import (
    ignore_stderr,
    _obtine_index_microfon,
    deschide_flux_microfon,
    calculeaza_rms_pcm16,
    proceseaza_semnal_microfon_slab
)
from ears.wake_word import (
    _incarca_vosk,
    _StreamDSP16k,
    GRAMATICA_FONETICA_EXTINSA,
    potrivire_fuzzy_robot
)


def _testeaza_rate_suportate(mic_index):
    rate_ok = []
    with ignore_stderr():
        for r in (8000, 16000, 22050, 44100, 48000):
            try:
                s = sr.Microphone(device_index=mic_index, sample_rate=r, chunk_size=512)
                with s:
                    _ = s.stream.read(256)
                rate_ok.append(r)
            except Exception:
                pass
    return rate_ok


def ruleaza_diagnostic():
    print("=" * 65)
    print("      DIAGNOSTIC AUDIO & WAKE WORD - ROBOT COMPANION (PI 3 B+)")
    print("=" * 65)

    with ignore_stderr():
        nume_mics = sr.Microphone.list_microphone_names()
    print(f"\n[1] Dispozitive audio găsite ({len(nume_mics)}):")
    for idx, n in enumerate(nume_mics):
        print(f"    [{idx}] {n}")

    mic_ales = _obtine_index_microfon(fortat=True)
    rate_reale = _testeaza_rate_suportate(mic_ales)
    print(f"\n[2] Microfon selectat: Index={mic_ales} | Sample rates suportate REAL: {rate_reale}")

    print("\n[3] Înregistrare 5 secunde: Păstrează liniștea 2s, apoi spune 'ROBOT' de 2 ori!")
    time.sleep(0.5)
    cadre_brut = []
    valori_rms = []
    rata_hw = rate_reale[0] if rate_reale else 8000

    try:
        with ignore_stderr():
            source = deschide_flux_microfon(mic_ales, chunk_size=1024)
            rata_hw = source.SAMPLE_RATE or rata_hw
            with source:
                t_start = time.time()
                while time.time() - t_start < 5.0:
                    # FĂRĂ exception_on_overflow=False!
                    buf = source.stream.read(1024)
                    cadre_brut.append(buf)
                    rms = calculeaza_rms_pcm16(buf)
                    valori_rms.append(rms)
                    bare = "#" * min(35, int(rms / 100))
                    print(f"\r    RMS Curent: {int(rms):5d} | {bare:<35}", end="", flush=True)
        print("\n")
    except Exception as e:
        print(f"\n[EROARE CAPTURĂ]: {e}")
        return

    rms_min = int(min(valori_rms)) if valori_rms else 0
    rms_max = int(max(valori_rms)) if valori_rms else 0
    rms_med = int(sum(valori_rms) / len(valori_rms)) if valori_rms else 0

    raw_5s = b"".join(cadre_brut)
    dsp_5s = proceseaza_semnal_microfon_slab(raw_5s, sample_rate=rata_hw)
    rms_dupa_dsp = int(calculeaza_rms_pcm16(dsp_5s))

    cale_wav = "/tmp/diag_mic_test.wav" if os.name != "nt" else os.path.join(BASE_DIR, "diag_mic_test.wav")
    try:
        with wave.open(cale_wav, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rata_hw)
            wf.writeframes(raw_5s)
        print(f"[4] WAV salvat în: {cale_wav} ({rata_hw} Hz)")
    except Exception as e:
        print(f"[AVERTISMENT WAV]: {e}")

    print(f"    - RMS Minim: {rms_min} | RMS Maxim: {rms_max} | RMS Mediu: {rms_med} -> După DSP: {rms_dupa_dsp}")

    print("\n[5] Testare Strategie 1 (Vosk Offline Phonetic + Stateful DSP):")
    model_v = _incarca_vosk()
    detectat_vosk = False
    texte_vosk = []
    if model_v:
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(model_v, 16000, GRAMATICA_FONETICA_EXTINSA)
        dsp_stream = _StreamDSP16k(sample_rate_in=rata_hw)
        for c in cadre_brut:
            c16 = dsp_stream.proceseaza_chunk(c)
            if rec.AcceptWaveform(c16):
                r = json.loads(rec.Result()).get("text", "").strip()
                if r:
                    texte_vosk.append(r)
            else:
                p = json.loads(rec.PartialResult()).get("partial", "").strip()
                if p and potrivire_fuzzy_robot(p):
                    detectat_vosk = True
        r_fin = json.loads(rec.FinalResult()).get("text", "").strip()
        if r_fin:
            texte_vosk.append(r_fin)
        for t in texte_vosk:
            if potrivire_fuzzy_robot(t):
                detectat_vosk = True
        print(f"    - Transcrieri fonetice Vosk: {texte_vosk}")
        print(f"    - Wake Word 'Robot' detectat de Vosk: {'DA [OK]' if detectat_vosk else 'NU'}")

    print("\n[6] Testare Strategie 2 (VAD + Google STT ro-RO):")
    r_stt = sr.Recognizer()
    audio_obj = sr.AudioData(dsp_5s, rata_hw, 2)
    txt_g = ""
    potrivit_g = False
    try:
        txt_g = r_stt.recognize_google(audio_obj, language="ro-RO")
        potrivit_g = potrivire_fuzzy_robot(txt_g)
        print(f"    - Google STT a înțeles: '{txt_g}' -> Detectat: {'DA [OK]' if potrivit_g else 'NU'}")
    except Exception as e:
        print(f"    - Google STT nu a returnat text ({e}).")

    print("\n" + "=" * 65)
    print("RAPORT SCURT DE COPIAT:")
    print(json.dumps({
        "mic_index": mic_ales,
        "supported_rates": rate_reale,
        "used_rate": rata_hw,
        "rms_min": rms_min,
        "rms_max": rms_max,
        "rms_dsp": rms_dupa_dsp,
        "vosk_heard": texte_vosk,
        "vosk_triggered": detectat_vosk,
        "stt_heard": txt_g,
        "stt_triggered": potrivit_g,
        "wav_file": cale_wav
    }))
    print("=" * 65)


if __name__ == "__main__":
    ruleaza_diagnostic()