"""
Teste offline pentru textul rostit și pentru comenzile recunoscute local (fără Gemini, fără rețea, fără sunet).
Rulează:  python tools/text_selftest.py
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import voice.speak as speak
from brain.ai_brain import CUVINTE_ORA_DATA, _instructiuni_cu_context

REZULTATE = []


def verifica(nume, conditie, detalii=""):
    REZULTATE.append((nume, bool(conditie)))
    print(f"  [{'OK' if conditie else 'ESEC'}] {nume}" + (f" ({detalii})" if detalii and not conditie else ""))


def test_ora_si_data():
    print("Ora și data, recunoscute local")
    da = ["cât e ceasul", "Cât este ceasul?", "cat e ceasul", "robot cât îi ceasul", "cât-i ceasul", "cât e ora",
          "cât este ora acum", "ce oră e", "ce ora este", "ce oră avem", "spune-mi ora", "spune mi cât e ceasul",
          "ora exactă", "ce oră s-a făcut", "în ce dată suntem", "in ce zi suntem", "ce dată e azi",
          "ce data este astazi", "ce zi e azi", "ce zi este astăzi", "în ce an suntem", "ce dată avem"]
    nu = ["ce dată e concertul", "la ce oră începe filmul", "cât e dolarul azi", "pune un ceas pe perete",
          "spune o glumă", "ce zi a fost ieri", "cât costă ceasul ăsta"]
    ratate = [t for t in da if not CUVINTE_ORA_DATA.search(t.lower())]
    false = [t for t in nu if CUVINTE_ORA_DATA.search(t.lower())]
    verifica("întrebările despre oră și dată sunt recunoscute", not ratate, str(ratate))
    verifica("alte întrebări nu sunt confundate cu ora", not false, str(false))
    context = _instructiuni_cu_context()
    verifica("Gemini primește ora și data de la robot", "CONTEXT ACTUAL" in context and "ora " in context)


def test_text_rostit():
    print("Textul trimis la voce")
    original_ro = speak.VOCE_RO
    try:
        speak.VOCE_RO = "ro-RO-EmilNeural"
        curat = speak._curata_si_adapteaza_text
        verifica("C# se rostește «si șarp», nu «C»", "si șarp" in curat("Scriu cod în C# de ani buni."), curat("Scriu cod în C#."))
        verifica("C# între steluțe de markdown", curat("Îmi place **C#** mult.") == "Îmi place si șarp mult.", curat("Îmi place **C#** mult."))
        verifica("C++ și F#", "si plas plas" in curat("C++ sau F#?") and "ef șarp" in curat("C++ sau F#?"), curat("C++ sau F#?"))
        verifica("un # obișnuit dispare ca înainte", curat("# Titlu și #1") == "Titlu și 1", curat("# Titlu și #1"))
        verifica("cuvintele englezești din dicționar sunt rescrise fonetic",
                 "hedbenghing" in curat("Facem headbanging pe YouTube.") and "iutub" in curat("Facem headbanging pe YouTube."))
        verifica("tag-ul de acțiune și emoji dispar", curat("[vorbeste_normal] Salut! 😀") == "Salut!", curat("[vorbeste_normal] Salut! 😀"))
        verifica("gradele și procentele se rostesc", curat("Sunt 21.5°C și 40%.") == "Sunt 21,5 grade Celsius și 40 la sută.",
                 curat("Sunt 21.5°C și 40%."))
        speak.VOCE_RO = "en-US-AvaMultilingualNeural"
        text = curat("Facem headbanging pe YouTube și scriem în C#.")
        verifica("vocea multilingvă primește cuvintele englezești nerescrise",
                 "headbanging" in text and "YouTube" in text and "C sharp" in text, text)
    finally:
        speak.VOCE_RO = original_ro
    verifica("tonul vocii are forma cerută de edge-tts", speak.TON_VOCE[0] in "+-" and speak.TON_VOCE.endswith("Hz"), speak.TON_VOCE)
    original_ton = speak.TON_REDARE
    try:
        speak.TON_REDARE = 0.0
        verifica("fără ton la redare, comanda mpg123 e cea dinainte", speak._comanda_mpg123("a.mp3") == ["mpg123", "-q", "a.mp3"])
        speak.TON_REDARE = 0.2
        verifica("cu ton la redare, mpg123 primește --pitch",
                 speak._comanda_mpg123("a.mp3") == ["mpg123", "-q", "--pitch", "0.200", "a.mp3"])
    finally:
        speak.TON_REDARE = original_ton


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for test in (test_ora_si_data, test_text_rostit):
        try:
            test()
        except Exception as e:
            verifica(f"{test.__name__} a rulat fără excepții", False, f"{type(e).__name__}: {e}")
    esecuri = [n for n, ok in REZULTATE if not ok]
    print("=" * 60)
    print(f"TEXT SELFTEST: {len(REZULTATE) - len(esecuri)} OK, {len(esecuri)} ESEC")
    return 1 if esecuri else 0


if __name__ == "__main__":
    sys.exit(main())
