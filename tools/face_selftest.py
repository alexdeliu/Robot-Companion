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

import math
from array import array

import face.lipsync as modul_lipsync
from face.lipsync import LipSync, analizeaza_fereastra
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


class RngFix:
    """Generator previzibil: fara clipit dublu la intamplare, ca testele sa dea mereu acelasi rezultat."""

    def random(self):
        return 0.5

    def uniform(self, a, b):
        return (a + b) / 2.0


def _motor(ceas, **kw):
    kw.setdefault("rng", RngFix())
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
    try:
        for dim in ((96, 64), (72, 48)):
            for expr in EXPRESII.values():
                compune_cadru(Geometrie(*dim), expr)
        verifica("mini-fata se randeaza la dimensiuni foarte mici", True)
    except Exception as e:
        verifica("mini-fata se randeaza la dimensiuni foarte mici", False, f"{type(e).__name__}: {e}")
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
    motor.seteaza_nivel_gura(1.0, forma=0.0)
    st_rotund = _avanseaza(motor, ceas, 0.4)
    verifica("vorbirea deschide gura", st_rotund["g_desch"] > 0.98)
    motor.seteaza_nivel_gura(1.0, forma=1.0)
    st_lat = _avanseaza(motor, ceas, 0.4)
    verifica("sunetele inchise rotunjesc gura, cele ascutite o latesc",
             st_rotund["g_rot"] > st_lat["g_rot"] + 0.3 and st_lat["g_lat"] > st_rotund["g_lat"] + 0.1
             and st_lat["g_desch"] < st_rotund["g_desch"])
    verifica("cat vorbeste priveste in fata", motor.privire.tinta()[:2] == (0.0, 0.0))
    st = st_lat
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


def _pcm_test():
    """2 s la 16 kHz: liniste 1 s, apoi 0,5 s sunet grav (200 Hz), apoi 0,5 s sunet ascutit."""
    es = array("h", [0] * 16000)
    es.extend(int(8000 * math.sin(2 * math.pi * 200 * i / 16000.0)) for i in range(8000))
    es.extend(6000 if i % 2 else -6000 for i in range(8000))
    if sys.byteorder == "big":
        es.byteswap()
    return es.tobytes()


def test_lipsync():
    print("Lip-sync")
    raw = _pcm_test()
    ls = LipSync(offset_ms=0)
    verifica("fara voce gura e inactiva", ls.citeste(50.0) == (False, 0.0, 0.5))
    ls.incarca_pcm(raw)
    ls.porneste(t=100.0)
    verifica("durata anvelopei = durata sunetului", abs(ls.durata_s - 2.0) < 0.03, f"{ls.durata_s:.3f}")
    activ, nivel, _forma = ls.citeste(100.5)
    verifica("in liniste gura sta inchisa", activ and nivel == 0.0)
    _a, nivel_grav, forma_grav = ls.citeste(101.25)
    verifica("sunet grav: gura deschisa, forma rotunda", nivel_grav > 0.8 and forma_grav < 0.3,
             f"nivel {nivel_grav:.2f} forma {forma_grav:.2f}")
    _a, nivel_ascutit, forma_ascutit = ls.citeste(101.75)
    verifica("sunet ascutit: forma lata", nivel_ascutit > 0.5 and forma_ascutit > 0.8,
             f"nivel {nivel_ascutit:.2f} forma {forma_ascutit:.2f}")
    inceput = next((k for k in range(0, 2000) if ls.citeste(100.0 + k / 1000.0)[1] > 0.3), None)
    verifica("gura se deschide la cel mult 40 ms de inceputul sunetului",
             inceput is not None and 960 <= inceput <= 1040, f"la {inceput} ms")
    verifica("dupa sfarsitul sunetului gura e inchisa", ls.citeste(102.5)[1] == 0.0)
    ls.opreste()
    verifica("oprirea inchide gura imediat", ls.citeste(101.25) == (False, 0.0, 0.5))

    cu_offset = LipSync(offset_ms=100)
    cu_offset.incarca_pcm(raw)
    cu_offset.porneste(t=100.0)
    verifica("decalajul configurat muta gura in timp",
             cu_offset.citeste(101.05)[1] == 0.0 and cu_offset.citeste(101.2)[1] > 0.5)

    fara_date = LipSync(offset_ms=0)
    fara_date.pregateste(None)
    fara_date.porneste(t=100.0)
    niveluri = [fara_date.citeste(100.7 + k * 0.05)[1] for k in range(20)]
    verifica("fara date audio gura tot se misca (rezerva)", fara_date.fara_date and max(niveluri) > 0.3)

    fragment = raw[32000 + 640:32000 + 1280]
    cu_audioop = analizeaza_fereastra(fragment)
    original = modul_lipsync.audioop
    modul_lipsync.audioop = None
    try:
        fara_audioop = analizeaza_fereastra(fragment)
    finally:
        modul_lipsync.audioop = original
    verifica("varianta fara audioop da acelasi rezultat",
             abs(cu_audioop[0] - fara_audioop[0]) < 0.02 * cu_audioop[0] + 1
             and abs(cu_audioop[1] - fara_audioop[1]) < 0.03, f"{cu_audioop} vs {fara_audioop}")

    erori = []

    def citeste_mereu():
        try:
            for k in range(3000):
                ls.citeste(100.0 + k / 1000.0)
        except Exception as e:
            erori.append(e)

    fir = threading.Thread(target=citeste_mereu)
    fir.start()
    for _ in range(200):
        ls.incarca_pcm(raw[:6400])
        ls.porneste(t=100.0)
        ls.opreste()
    fir.join()
    verifica("citirea in timp ce vocea porneste si se opreste nu da erori", not erori, str(erori[:1]))


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
        afisaj2 = AfisajFataTk(root, 480, 320)
        afisaj2.aplica(EXPRESII["neutru"])
        cutie_gura = afisaj2.geo.cutie_gura()
        sus, jos = afisaj2._randuri["gura"]
        verifica("gura inchisa ocupa mult mai putine randuri decat cutia ei",
                 0 < jos - sus <= 0.5 * (cutie_gura[3] - cutie_gura[1]), f"{jos - sus} randuri")
        deschisa = dict(EXPRESII["neutru"], g_desch=1.0)
        modificat = [m for m in afisaj2.aplica(deschisa)]
        verifica("schimbarea gurii atinge doar randurile gurii",
                 len(modificat) == 1 and modificat[0][0] >= cutie_gura[1] and modificat[0][1] <= cutie_gura[3])
        verifica("imaginile afisate raman in viata", all(f == "" or f.width() > 0 for f in afisaj._afisat.values()))
    finally:
        root.destroy()


def main():
    for test in (test_expresii, test_randare, test_motor, test_somn, test_privire, test_lipsync, test_afisaj):
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
