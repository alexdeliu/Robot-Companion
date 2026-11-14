"""
Ascultă variante de voce direct pe robot (sau pe PC), fără Gemini, și păstreaz-o pe cea care îți place.

    venv/bin/python tools/voice_preview.py               # redă toate variantele, pe rând
    venv/bin/python tools/voice_preview.py 3 5            # redă doar variantele 3 și 5
    venv/bin/python tools/voice_preview.py --salveaza 5   # scrie varianta 5 în config.local.json

Pe robot oprește întâi serviciul (sudo systemctl stop robot-companion), ca să nu se audă singur.
Variantele „robot mic” ridică tonul la redare (mpg123 --pitch): vocea sună mai subțire, ca a unui personaj mic.
Pe PC redarea nu poate ridica tonul în felul acesta, deci acolo variantele respective sună ca vocea de bază.
"""
import argparse
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

FRAZA = ("Salut! Eu sunt asistentul tău de birou. Azi ascultăm rock, facem puțin headbanging "
         "și scriem cod în C# și Python. Tu ce mai faci?")

# (nume, voce edge-tts, ton edge-tts, viteză edge-tts, ton la redare)
# Viteza edge-tts e redusă la variantele „robot mic”, pentru că redarea mai sus e și mai rapidă.
VARIANTE = [
    ("Emil, vocea de acum", "ro-RO-EmilNeural", "+0Hz", "+8%", 0.0),
    ("Emil, robot mic (ușor)", "ro-RO-EmilNeural", "+0Hz", "-6%", 0.15),
    ("Emil, robot mic (mediu)", "ro-RO-EmilNeural", "+0Hz", "-13%", 0.25),
    ("Emil, robot mic (pronunțat)", "ro-RO-EmilNeural", "+0Hz", "-20%", 0.35),
    ("Alina", "ro-RO-AlinaNeural", "+0Hz", "+8%", 0.0),
    ("Alina, robot mic (ușor)", "ro-RO-AlinaNeural", "+0Hz", "-2%", 0.10),
    ("Alina, robot mic (mediu)", "ro-RO-AlinaNeural", "+0Hz", "-10%", 0.20),
    ("Andrew multilingv, robot mic", "en-US-AndrewMultilingualNeural", "+0Hz", "-10%", 0.22),
    ("Ava multilingvă, robot mic", "en-US-AvaMultilingualNeural", "+0Hz", "-4%", 0.12),
]


def aplica(speak, varianta):
    _nume, voce, ton, viteza, ton_redare = varianta
    speak.VOCE_RO, speak.TON_VOCE, speak.VITEZA_VOCE, speak.TON_REDARE = voce, ton, viteza, ton_redare


def main():
    ap = argparse.ArgumentParser(description="Ascultă și alege vocea robotului")
    ap.add_argument("numere", nargs="*", type=int, help="ce variante să redea (implicit toate)")
    ap.add_argument("--salveaza", type=int, metavar="N", help="păstrează varianta N în config.local.json")
    ap.add_argument("--fraza", default=FRAZA)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.salveaza is not None:
        if not 1 <= args.salveaza <= len(VARIANTE):
            print(f"Varianta {args.salveaza} nu există (1..{len(VARIANTE)}).")
            return 1
        from config import salveaza_config_local
        nume, voce, ton, viteza, ton_redare = VARIANTE[args.salveaza - 1]
        for cheie, valoare in (("tts_voice_ro", voce), ("tts_pitch", ton), ("tts_rate", viteza),
                               ("tts_playback_pitch", ton_redare)):
            salveaza_config_local("audio_out", cheie, valoare)
        print(f"Am salvat varianta {args.salveaza} ({nume}) în config.local.json. Repornește robotul ca să o folosească.")
        return 0

    from voice import speak
    alese = args.numere or list(range(1, len(VARIANTE) + 1))
    for nr in alese:
        if not 1 <= nr <= len(VARIANTE):
            print(f"Sar peste {nr}: nu există.")
            continue
        varianta = VARIANTE[nr - 1]
        print(f"Varianta {nr}: {varianta[0]}  (voce {varianta[1]}, viteză {varianta[3]}, ton la redare {varianta[4]})")
        sys.stdout.flush()
        aplica(speak, varianta)
        speak.vorbeste(f"Varianta {nr}. {args.fraza}", "ro")
        time.sleep(0.7)
    print("Gata. Păstrezi una cu:  venv/bin/python tools/voice_preview.py --salveaza N")
    return 0


if __name__ == "__main__":
    sys.exit(main())
