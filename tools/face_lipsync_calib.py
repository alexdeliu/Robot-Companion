"""
Calibrarea gurii: măsoară, cu microfonul robotului, cât trece de la pornirea redării până când vocea
se aude efectiv, și propune valoarea pentru face.lipsync_offset_ms.

Rulează pe robot, cu serviciul oprit (microfonul trebuie să fie liber), într-o cameră liniștită:

    sudo systemctl stop robot-companion
    venv/bin/python tools/face_lipsync_calib.py              # doar măsoară
    venv/bin/python tools/face_lipsync_calib.py --salveaza   # scrie valoarea în config.local.json
    sudo systemctl start robot-companion

Robotul spune o frază scurtă de câteva ori. Folosește exact aceeași cale de redare ca în funcționarea normală
(voice.speak.vorbeste), deci măsoară întârzierea reală. Nu folosește Gemini.
"""
import argparse
import os
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

FRAZA = "Pa, pa, pa. Unu, doi, trei. Test de sincronizare."
PAS_S = 0.01
# Cât întârzie, estimativ, microfonul (de la sunet până la citirea eșantioanelor) și ecranul SPI
# (de la desen până când imaginea se vede). Se scad din întârzierea măsurată.
LATENTA_MICROFON_MS = 30
LATENTA_ECRAN_MS = 60


def _pe_grila(momente, valori, durata_s):
    """Pune valorile măsurate la momente neregulate pe o grilă de PAS_S (ultima valoare cunoscută)."""
    rez, j, ultima = [], 0, 0.0
    for k in range(int(durata_s / PAS_S)):
        t = k * PAS_S
        while j < len(momente) and momente[j] <= t:
            ultima = valori[j]
            j += 1
        rez.append(ultima)
    return rez


def masoara_o_data(speak, LipSync, analizeaza_fereastra, estimeaza_decalaj, sursa):
    ls = LipSync(offset_ms=0)
    t_pornit = []

    def la_redare(eveniment, **date):
        if eveniment == "pregatit":
            ls.pregateste(date.get("cale"))
        elif eveniment == "pornit":
            t_pornit.append(date.get("t") or time.monotonic())
            ls.porneste(date.get("t"))   # pe PC decodarea porneste abia aici

    speak.seteaza_callback_redare(la_redare)
    stop = threading.Event()
    momente, tarii, erori = [], [], [0]
    rata = int(sursa.SAMPLE_RATE)
    bucata = max(80, rata // 50)   # 20 ms

    def asculta():
        while not stop.is_set():
            try:
                date = sursa.stream.read(bucata)
            except Exception:
                erori[0] += 1
                continue
            momente.append(time.monotonic() - bucata / (2.0 * rata))
            tarii.append(analizeaza_fereastra(date)[0])

    fir = threading.Thread(target=asculta, name="CalibMic", daemon=True)
    fir.start()
    time.sleep(0.4)
    speak.vorbeste(FRAZA, "ro")
    time.sleep(0.8)
    stop.set()
    fir.join(timeout=2)
    speak.seteaza_callback_redare(None)

    if not t_pornit or ls.durata_s <= 0 or not momente:
        return None, 0.0, f"lipsesc date (pornit={len(t_pornit)}, durata={ls.durata_s:.2f}s, microfon={len(momente)} bucăți)"
    t0 = t_pornit[0]
    referinta = [v for v in ls._rms for _ in (0, 1)]   # ferestre de 20 ms -> grilă de 10 ms
    relativ = [(t - t0, v) for t, v in zip(momente, tarii) if t >= t0]
    masurat = _pe_grila([t for t, _v in relativ], [v for _t, v in relativ], ls.durata_s + 1.3)
    decalaj, scor = estimeaza_decalaj(referinta, masurat, pas_s=PAS_S, max_s=1.2)
    return decalaj, scor, f"{len(momente)} bucăți de microfon, {erori[0]} erori de citire"


def main():
    ap = argparse.ArgumentParser(description="Calibrarea sincronizării gurii cu vocea")
    ap.add_argument("--repetari", type=int, default=3)
    ap.add_argument("--salveaza", action="store_true", help="scrie face.lipsync_offset_ms în config.local.json")
    ap.add_argument("--latenta-ecran-ms", type=int, default=LATENTA_ECRAN_MS)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from config import salveaza_config_local
    from ears.listen import deschide_flux_microfon
    from face.lipsync import LipSync, analizeaza_fereastra, estimeaza_decalaj
    from voice import speak

    print("== CALIBRARE GURĂ: robotul va vorbi de câteva ori; păstrează liniște în cameră.")
    rezultate = []
    sursa = deschide_flux_microfon(chunk_size=256)
    with sursa:
        for i in range(max(1, args.repetari)):
            decalaj, scor, detalii = masoara_o_data(speak, LipSync, analizeaza_fereastra, estimeaza_decalaj, sursa)
            if decalaj is None:
                print(f"  măsurătoarea {i + 1}: EȘEC, {detalii}")
                continue
            print(f"  măsurătoarea {i + 1}: sunetul apare la {decalaj * 1000:.0f} ms după pornirea redării "
                  f"(potrivire {scor:.2f}; {detalii})")
            if scor >= 0.45:
                rezultate.append(decalaj * 1000.0)
            time.sleep(0.6)

    if not rezultate:
        print("REZULTAT: nu am o măsurătoare de încredere (potrivire sub 0.45). Verifică volumul și microfonul.")
        return 1
    rezultate.sort()
    median = rezultate[len(rezultate) // 2]
    recomandat = int(round(max(0.0, median - LATENTA_MICROFON_MS - args.latenta_ecran_ms)))
    print(f"REZULTAT: întârzierea sunetului = {median:.0f} ms (din {len(rezultate)} măsurători: "
          f"{', '.join(f'{r:.0f}' for r in rezultate)})")
    print(f"RECOMANDAT: face.lipsync_offset_ms = {recomandat} "
          f"(= {median:.0f} - {LATENTA_MICROFON_MS} microfon - {args.latenta_ecran_ms} ecran)")
    if args.salveaza:
        salveaza_config_local("face", "lipsync_offset_ms", recomandat)
        print("Am salvat valoarea în config.local.json. Repornește serviciul ca să o folosească.")
    else:
        print("Nu am salvat nimic. Rulează din nou cu --salveaza ca să o păstrezi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
