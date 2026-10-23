import os
import time
import json
import speech_recognition as sr

from config import CFG
from ears.listen import (
    ignore_stderr,
    _obtine_index_microfon,
    deschide_flux_microfon,
    calculeaza_rms_pcm16,
    proceseaza_semnal_microfon_slab
)
from ears.wake_word import (
    _incarca_vosk,
    _converteste_la_16k_dsp,
    GRAMATICA_FONETICA_EXTINSA,
    potrivire_fuzzy_robot
)


def ruleaza_diagnostic():
    print("=" * 65)
    print("      DIAGNOSTIC AUDIO & WAKE WORD - ROBOT COMPANION (PI 3 B+)")
    print("=" * 65)

    # 1. Listare dispozitive
    with ignore_stderr():
        nume_mics = sr.Microphone.list_microphone_names()
    print(f"\n[1] Dispozitive audio găsite ({len(nume_mics)}):")
    for idx, n in enumerate(nume_mics):
        print(f"    [{idx}] {n}")

    mic_ales = _obtine_index_microfon(fortat=True)
    print(f"\n[2] Microfon selectat automat: Index={mic_ales}")

    # 2. Înregistrare 5 secunde (2s liniște + 3s voce)
    print("\n[3] Test de nivel (5 secunde): Păstrează liniștea 2s, apoi spune 'ROBOT' de 2 ori!")
    time.sleep(0.5)
    cadre_brut = []
    valori_rms = []
    rata_hw = 8000

    try:
        with ignore_stderr():
            source = deschide_flux_microfon(mic_ales, chunk_size=1024)
            rata_hw = source.SAMPLE_RATE or 8000
            with source:
                t_start = time.time()
                while time.time() - t_start < 5.0:
                    buf = source.stream.read(1024, exception_on_overflow=False)
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
    snr_db = round(20 * ((rms_max / max(1, rms_min)) if rms_max > 0 else 1), 1)

    raw_5s = b"".join(cadre_brut)
    dsp_5s = proceseaza_semnal_microfon_slab(raw_5s, sample_rate=rata_hw)
    rms_dupa_dsp = int(calculeaza_rms_pcm16(dsp_5s))

    print(f"[4] Statistici Semnal ({rata_hw} Hz):")
    print(f"    - RMS Zgomot (Minim): {rms_min}")
    print(f"    - RMS Vârf Voce (Maxim): {rms_max}")
    print(f"    - RMS Mediu Brut: {rms_med} -> RMS Mediu după DSP/AGC: {rms_dupa_dsp}")

    # 3. Test Strategie Vosk pe înregistrarea de 5 secunde
    print("\n[5] Testare Strategie 1 (Vosk Offline Phonetic + Fuzzy):")
    model_v = _incarca_vosk()
    detectat_vosk = False
    texte_vosk = []
    if model_v:
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(model_v, 16000, GRAMATICA_FONETICA_EXTINSA)
        for c in cadre_brut:
            c16 = _converteste_la_16k_dsp(c, sample_rate_intrare=rata_hw)
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
    else:
        print("    - Modelul Vosk nu a putut fi încărcat.")

    # 4. Test Strategie Google STT pe înregistrarea de 5 secunde
    print("\n[6] Testare Strategie 2 (VAD + Google STT ro-RO):")
    r_stt = sr.Recognizer()
    audio_obj = sr.AudioData(dsp_5s, rata_hw, 2)
    try:
        txt_g = r_stt.recognize_google(audio_obj, language="ro-RO")
        potrivit_g = potrivire_fuzzy_robot(txt_g)
        print(f"    - Google STT a înțeles: '{txt_g}'")
        print(f"    - Wake Word 'Robot' detectat de STT: {'DA [OK]' if potrivit_g else 'NU'}")
    except Exception as e:
        print(f"    - Google STT nu a returnat text ({e}).")

    print("\n" + "=" * 65)
    print("RAPORT SCURT DE COPIAT:")
    print(json.dumps({
        "mic_index": mic_ales,
        "sample_rate": rata_hw,
        "rms_min": rms_min,
        "rms_max": rms_max,
        "rms_dsp": rms_dupa_dsp,
        "vosk_heard": texte_vosk,
        "vosk_triggered": detectat_vosk,
        "snr_est": snr_db
    }))
    print("=" * 65)


if __name__ == "__main__":
    ruleaza_diagnostic()