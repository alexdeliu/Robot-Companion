"""
Teste offline pentru fata robotului: expresii, motor de animatie, privire, randare si afisaj.
Nu foloseste microfonul, reteaua sau Gemini. Ruleaza:  python tools/face_selftest.py
"""
import os
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from face.motor import MotorFata, CLIPIT_INCHIDE
from face.parametri import EXPRESII, expresie
from face.privire import ManagerPrivire
from face.randare import Geometrie, componente, compune_cadru

REZULTATE = []


def verifica(nume, conditie, detalii=""):
    REZULTATE.append((nume, bool(conditie)))
    print(f"  [{'OK' if conditie else 'ESEC'}] {nume}" + (f" ({detalii})" if detalii and not conditie else ""))


class CeasFals:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _motor(ceas, **kw):
    kw.setdefault("respiratie", 0.0)
    kw.setdefault("adormire_dupa_sec", 0)
    motor = MotorFata(ceas=ceas, **kw)
    motor._urm_clipit = motor._urm_sacada = 1e12
    return motor


def _avanseaza(motor, ceas, secunde, pas=1.0 / 30):
    st = motor.tick()
    for _ in range(int(round(secunde / pas))):
        ceas.t += pas
        st = motor.tick()
    return st


def test_expresii():
    print("Expresii")
    chei = set(EXPRESII["neutru"])
    verifica("toate expresiile au aceiasi parametri", all(set(e) == chei for e in EXPRESII.values()))
    verifica("toate valorile sunt numere", all(isinstance(v, float) for e in EXPRESII.values() for v in e.values()))
    verifica("exista cele 16 expresii cerute", all(n in EXPRESII for n in (
        "neutru", "fericit", "ras", "trist", "surprins", "confuz", "ganditor", "curios", "atent", "somnoros",
        "adormit", "plictisit", "jenat", "mandru", "eroare", "entuziasmat", "obosit")))
    try:
        expresie(parametru_inexistent=1.0)
        verifica("parametrul necunoscut e respins", False)
    except KeyError:
        verifica("parametrul necunoscut e respins", True)
    e = expresie(sus=0.3, sus_d=0.7)
    verifica("valoarea pe o latura o suprascrie pe cea comuna", e["sus_s"] == 0.3 and e["sus_d"] == 0.7)


def test_randare():
    print("Randare")
    for latime, inaltime in ((480, 320), (320, 240)):
        geo = Geometrie(latime, inaltime)
        cutii = geo.cutii()
        in_ecran = all(c[0] >= 0 and c[1] >= 0 and c[2] <= latime and c[3] <= inaltime for c in cutii.values())
        verifica(f"{latime}x{inaltime}: toate componentele incap pe ecran", in_ecran, str(cutii))
        ochi_s, ochi_d, gura = cutii["ochi_s"], cutii["ochi_d"], cutii["gura"]
        verifica(f"{latime}x{inaltime}: ochii nu se suprapun", ochi_s[2] <= ochi_d[0])
        verifica(f"{latime}x{inaltime}: gura e sub ochi", gura[1] >= ochi_s[3])
        ok, detaliu = True, ""
        for nume, expr in EXPRESII.items():
            try:
                for element, cheie, fn in componente(geo, expr):
                    plata = [x for parte in cheie[1:] for x in (parte if isinstance(parte, tuple) else (parte,))]
                    if fn is None:
                        continue
                    img = fn()
                    c = cutii[element]
                    if img.size != (c[2] - c[0], c[3] - c[1]) or img.mode != "RGB":
                        ok, detaliu = False, f"{nume}/{element}: marime {img.size}"
                    if not all(isinstance(x, (int, str)) or isinstance(x, tuple) for x in plata):
                        ok, detaliu = False, f"{nume}/{element}: cheie neintreaga"
                if compune_cadru(geo, expr).size != (latime, inaltime):
                    ok, detaliu = False, f"{nume}: cadru gresit"
            except Exception as e:
                ok, detaliu = False, f"{nume}: {type(e).__name__}: {e}"
        verifica(f"{latime}x{inaltime}: toate expresiile se randeaza", ok, detaliu)
    geo = Geometrie()
    k1 = [c[1] for c in componente(geo, EXPRESII["fericit"])]
    k2 = [c[1] for c in componente(geo, dict(EXPRESII["fericit"]))]
    verifica("aceeasi stare da aceleasi chei de cache", k1 == k2)
    t0 = time.perf_counter()
    for expr in EXPRESII.values():
        compune_cadru(geo, expr)
    ms = 1000 * (time.perf_counter() - t0) / len(EXPRESII)
    print(f"  [INFO] randare completa: {ms:.1f} ms pe expresie (pe acest calculator)")


def test_motor():
    print("Motor")
    ceas = CeasFals()
    motor = _motor(ceas)
    motor.seteaza_expresie("fericit")
    st = _avanseaza(motor, ceas, 1.5)
    tinta = EXPRESII["fericit"]
    abatere = max(abs(st[k] - tinta[k]) for k in tinta if k not in ("px", "py", "r", "g", "b"))
    verifica("tranzitia ajunge la expresia tinta", abatere < 0.01, f"abatere {abatere:.3f}")
    verifica("dupa tranzitie motorul e in repaus", not motor.in_miscare)
    verifica("in repaus intervalul creste (FPS adaptiv)", motor.interval_urmator() > 1.5 / motor.fps_activ)

    motor.seteaza_expresie("neutru")
    st1 = _avanseaza(motor, ceas, 1.0 / 30)
    verifica("in tranzitie motorul cere FPS activ", motor.in_miscare and abs(motor.interval_urmator() - 1 / 30) < 1e-6)
    verifica("tranzitia e treptata, nu un salt", 0.0 < abs(st1["g_curb"] - tinta["g_curb"]) < abs(EXPRESII["neutru"]["g_curb"] - tinta["g_curb"]))
    _avanseaza(motor, ceas, 1.5)

    motor.seteaza_expresie("expresie_care_nu_exista")
    verifica("expresia necunoscuta cade pe neutru", motor.expresie_curenta == "neutru")

    motor._urm_clipit = ceas.t
    st = _avanseaza(motor, ceas, CLIPIT_INCHIDE + 0.02)
    verifica("clipitul inchide ambii ochi", all(st[f"sus_{l}"] + st[f"jos_{l}"] > 0.98 for l in "sd"))
    motor._urm_clipit = 1e12
    st = _avanseaza(motor, ceas, 0.5)
    verifica("dupa clipit ochii se redeschid", all(st[f"sus_{l}"] < 0.02 for l in "sd"))

    motor.seteaza_vorbire(True)
    motor.seteaza_nivel_gura(1.0)
    st = _avanseaza(motor, ceas, 0.1)
    verifica("vorbirea deschide gura", st["g_desch"] > 0.98)
    motor.seteaza_vorbire(False)
    ceas.t += 1.0 / 30
    st = motor.tick()
    verifica("la oprirea vorbirii gura se inchide in primul cadru", st["g_desch"] < 0.01)

    motor.reactie("surprins", durata=0.5)
    _avanseaza(motor, ceas, 0.2)
    verifica("reactia inlocuieste temporar expresia", motor.expresie_curenta == "surprins")
    _avanseaza(motor, ceas, 0.6)
    verifica("dupa reactie revine la baza", motor.expresie_curenta == "neutru")
    motor.reactie("nu_exista")
    verifica("reactia necunoscuta e ignorata", motor.expresie_curenta == "neutru")

    motor.opreste()
    verifica("oprit: tick nu produce nimic", motor.tick() is None)
    motor.porneste()
    verifica("repornit: tick produce o stare", isinstance(motor.tick(), dict))


def test_somn():
    print("Somn")
    ceas = CeasFals()
    motor = _motor(ceas, adormire_dupa_sec=10)
    _avanseaza(motor, ceas, 6.5, pas=0.5)
    verifica("dupa 60% din timp: plictisit", motor.stadiu_somn == 1 and motor.expresie_curenta == "plictisit")
    _avanseaza(motor, ceas, 4.0, pas=0.5)
    verifica("la expirare: somnoros", motor.stadiu_somn == 2)
    _avanseaza(motor, ceas, 8.5, pas=0.5)
    verifica("apoi: adormit", motor.stadiu_somn == 3 and motor.expresie_curenta == "adormit")
    verifica("adormit: cel mult un tick pe secunda", motor.interval_urmator() >= 0.99 or motor.in_miscare)
    motor.activitate()
    verifica("activitatea il trezeste cu o reactie", motor.stadiu_somn == 0 and motor.expresie_curenta == "surprins")
    _avanseaza(motor, ceas, 1.0)
    verifica("dupa trezire revine la baza", motor.expresie_curenta == "neutru")
    motor.seteaza_expresie("muzica")
    _avanseaza(motor, ceas, 30.0, pas=0.5)
    verifica("nu adoarme cat timp expresia nu e neutra", motor.stadiu_somn == 0)


def test_privire():
    print("Privire")
    ceas = CeasFals()
    p = ManagerPrivire(ceas)
    verifica("fara surse priveste in fata", p.tinta() == (0.0, 0.0, None))
    p.seteaza(-0.4, 0.2, sursa="idle", timeout_s=None)
    p.seteaza(0.8, 0.5, sursa="camera", timeout_s=1.0)
    verifica("camera are prioritate fata de idle", p.tinta()[2] == "camera")
    ceas.t += 1.1
    verifica("dupa timeout revine la sursa ramasa", p.tinta() == (-0.4, 0.2, "idle"))
    p.seteaza(5.0, -9.0, sursa="atingere")
    x, y, _s = p.tinta()
    verifica("coordonatele sunt limitate la [-1, 1]", (x, y) == (1.0, -1.0))
    p.elibereaza("atingere")
    for _ in range(40):
        ceas.t += 1.0 / 30
        x, y, misca = p.actualizeaza(ceas.t, 1.0 / 30)
    verifica("privirea netezita ajunge la tinta", abs(x + 0.4) < 0.01 and abs(y - 0.2) < 0.01 and not misca)

    erori = []

    def scrie(sursa):
        try:
            for i in range(2000):
                p.seteaza(i % 3 - 1, 0.0, sursa=sursa, timeout_s=0.01)
                p.tinta()
        except Exception as e:
            erori.append(e)

    fire = [threading.Thread(target=scrie, args=(f"s{i}",)) for i in range(4)]
    for f in fire:
        f.start()
    for f in fire:
        f.join()
    verifica("scrieri din mai multe fire nu dau erori", not erori, str(erori[:1]))


def test_afisaj():
    print("Afisaj Tk")
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
    except Exception as e:
        print(f"  [INFO] Tk indisponibil ({e}); sar peste testele de afisaj")
        return
    try:
        from face.afisaj_tk import AfisajFataTk
        afisaj = AfisajFataTk(root, 480, 320, cache_max=6)
        prima = afisaj.aplica(EXPRESII["neutru"])
        verifica("primul desen atinge ochii si gura", len(prima) >= 3)
        verifica("aceeasi stare nu redeseneaza nimic", afisaj.aplica(EXPRESII["neutru"]) == [])
        randari = afisaj.randari
        afisaj.aplica(EXPRESII["fericit"])
        afisaj.aplica(EXPRESII["neutru"])
        verifica("revenirea la o stare vazuta vine din cache", afisaj.randari - randari <= 3)
        for expr in EXPRESII.values():
            afisaj.aplica(expr)
        root.update_idletasks()
        verifica("cache-ul respecta limita", len(afisaj._cache) <= 6)
        verifica("imaginile afisate raman in viata", all(f == "" or f.width() > 0 for f in afisaj._afisat.values()))
    finally:
        root.destroy()


def main():
    for test in (test_expresii, test_randare, test_motor, test_somn, test_privire, test_afisaj):
        try:
            test()
        except Exception as e:
            verifica(f"{test.__name__} a rulat fara exceptii", False, f"{type(e).__name__}: {e}")
    esecuri = [n for n, ok in REZULTATE if not ok]
    print("=" * 60)
    print(f"FACE SELFTEST: {len(REZULTATE) - len(esecuri)} OK, {len(esecuri)} ESEC")
    for n in esecuri:
        print(f"  ESEC: {n}")
    return 1 if esecuri else 0


if __name__ == "__main__":
    sys.exit(main())
