"""
Modul de dezvoltare al fetei, pe PC (fara microfon, fara Gemini, fara robot).

  python -m face.dev                 fereastra interactiva, marita x2
  python -m face.dev --export DIR    planse PNG cu toate expresiile si cu tranzitii

In fereastra: butoanele schimba expresia, mouse-ul deasupra fetei muta privirea, click = atingere,
tragere = mangaiere. Tastele: spatiu = vorbire simulata, f = flux complet, s = somn, t = trezire.
"""
import argparse
import math
import os
import sys
import time

from .motor import MotorFata
from .parametri import EXPRESII, FUNDAL
from .randare import Geometrie, compune_cadru


class CeasFals:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _font(marime, bold=False):
    from PIL import ImageFont
    for nume in (("arialbd.ttf" if bold else "arial.ttf"), "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(nume, marime)
        except OSError:
            continue
    return ImageFont.load_default()


def nivel_vorbire_simulat(t):
    """Anvelopa de amplitudine artificiala, cu silabe si pauze, pentru testarea gurii."""
    silaba = abs(math.sin(2 * math.pi * 3.3 * t))
    fraza = 0.55 + 0.45 * math.sin(2 * math.pi * 0.6 * t)
    pauza = 0.0 if (t % 2.6) > 2.2 else 1.0
    return max(0.0, silaba * fraza * pauza)


def _motor_linistit(ceas):
    """Motor fara clipit si fara sacade, pentru capturi reproductibile."""
    motor = MotorFata(ceas=ceas, respiratie=0.0, adormire_dupa_sec=0)
    motor._urm_clipit = motor._urm_sacada = 1e12
    return motor


def _avanseaza(motor, ceas, secunde, pas=1.0 / 30):
    st = motor.tick()
    for _ in range(int(round(secunde / pas))):
        ceas.t += pas
        st = motor.tick()
    return st


def exporta(director, latime, inaltime):
    from PIL import Image, ImageDraw
    os.makedirs(director, exist_ok=True)
    geo = Geometrie(latime, inaltime)
    y0, y1 = geo.banda()
    y0, y1 = max(0, y0 - 10), min(inaltime, y1 + 10)
    eticheta_h, fundal_plansa = 22, "#111318"
    f_et = _font(15, bold=True)

    # 1. Toate expresiile, la 1x, decupate pe banda fetei
    coloane = 4
    nume = list(EXPRESII)
    randuri = (len(nume) + coloane - 1) // coloane
    cel_h = (y1 - y0) + eticheta_h
    plansa = Image.new("RGB", (coloane * latime, randuri * cel_h), fundal_plansa)
    d = ImageDraw.Draw(plansa)
    for i, n in enumerate(nume):
        x, y = (i % coloane) * latime, (i // coloane) * cel_h
        plansa.paste(compune_cadru(geo, EXPRESII[n]).crop((0, y0, latime, y1)), (x, y + eticheta_h))
        d.text((x + 8, y + 3), n, font=f_et, fill="#ABB2BF")
    plansa.save(os.path.join(director, "plansa_expresii.png"))

    # 2. Aceeasi plansa redusa la culorile ecranului (RGB565, fara dithering): arata treptele din glow
    r, g, b = plansa.split()
    p565 = Image.merge("RGB", (r.point(lambda v: v & 0xF8), g.point(lambda v: v & 0xFC), b.point(lambda v: v & 0xF8)))
    decup = p565.crop((0, 0, 2 * latime, 2 * cel_h))
    decup.resize((decup.width * 2, decup.height * 2), Image.Resampling.NEAREST).save(
        os.path.join(director, "plansa_rgb565_x2.png"))

    # 3. Ecranul intreg pentru cateva expresii, exact cum apare pe panou
    for n in ("neutru", "fericit", "ganditor", "adormit"):
        compune_cadru(geo, EXPRESII[n]).save(os.path.join(director, f"ecran_{n}.png"))

    # 4. Tranzitii, clipit si vorbire, ca benzi de cadre la jumatate de marime
    secvente = []
    for a, b_ in (("neutru", "fericit"), ("neutru", "surprins"), ("fericit", "trist"), ("adormit", "atent")):
        ceas = CeasFals()
        motor = _motor_linistit(ceas)
        motor.seteaza_expresie(a)
        _avanseaza(motor, ceas, 2.0)
        motor.seteaza_expresie(b_)
        cadre = []
        for _ in range(8):
            cadre.append(compune_cadru(geo, _avanseaza(motor, ceas, 1.0 / 15)))
        secvente.append((f"{a} -> {b_} (un cadru la 67 ms)", cadre))

    ceas = CeasFals()
    motor = _motor_linistit(ceas)
    _avanseaza(motor, ceas, 1.0)
    motor._urm_clipit = ceas.t
    secvente.append(("clipit (un cadru la 33 ms)", [compune_cadru(geo, _avanseaza(motor, ceas, 1.0 / 30)) for _ in range(8)]))

    ceas = CeasFals()
    motor = _motor_linistit(ceas)
    _avanseaza(motor, ceas, 1.0)
    motor.seteaza_vorbire(True)
    cadre = []
    for nivel in (0.0, 0.25, 0.6, 1.0, 0.7, 0.35, 0.85, 0.1):
        motor.seteaza_nivel_gura(nivel)
        cadre.append(compune_cadru(geo, _avanseaza(motor, ceas, 1.0 / 30)))
    secvente.append(("vorbire: nivel 0 / .25 / .6 / 1 / .7 / .35 / .85 / .1", cadre))

    mw, mh = latime // 2, (y1 - y0) // 2
    banda = Image.new("RGB", (8 * mw, len(secvente) * (mh + eticheta_h)), fundal_plansa)
    d = ImageDraw.Draw(banda)
    for rand, (titlu, cadre) in enumerate(secvente):
        y = rand * (mh + eticheta_h)
        d.text((8, y + 3), titlu, font=f_et, fill="#ABB2BF")
        for k, cadru in enumerate(cadre):
            mic = cadru.crop((0, y0, latime, y1)).resize((mw, mh), Image.Resampling.LANCZOS)
            banda.paste(mic, (k * mw, y + eticheta_h))
    banda.save(os.path.join(director, "plansa_tranzitii.png"))
    print(f"Export gata in {director}: {len(nume)} expresii, banda fetei = randurile {geo.banda()}")


def ruleaza_interactiv(latime, inaltime, zoom, auto_inchide=0.0):
    import tkinter as tk
    from .afisaj_tk import AfisajFataTk

    root = tk.Tk()
    root.title("Robot Companion - fata (mod dezvoltare)")
    root.configure(bg=FUNDAL)
    motor = MotorFata(adormire_dupa_sec=45)
    afisaj = AfisajFataTk(root, latime, inaltime, zoom=zoom)
    afisaj.canvas.pack()

    info = tk.Label(root, text="", font=("Consolas", 9), bg=FUNDAL, fg="#5C6370", anchor="w")
    info.pack(fill="x", padx=6)
    panou = tk.Frame(root, bg=FUNDAL)
    panou.pack(fill="x", padx=4, pady=4)
    stare = {"vorbire": False, "t_vorbire": 0.0, "tick": 0, "desen": 0, "t_stat": time.monotonic(),
             "cpu": time.process_time(), "trage": 0}

    for i, nume in enumerate(EXPRESII):
        tk.Button(panou, text=nume, font=("Arial", 8), bg="#282C34", fg="#ABB2BF", relief="flat", width=11,
                  command=lambda n=nume: motor.seteaza_expresie(n)).grid(row=i // 8, column=i % 8, padx=1, pady=1)

    def comuta_vorbire(_e=None):
        stare["vorbire"] = not stare["vorbire"]
        stare["t_vorbire"] = time.monotonic()
        motor.seteaza_vorbire(stare["vorbire"])

    def flux(_e=None):
        pasi = [(0, lambda: motor.reactie("surprins", 0.5, 2.2)), (500, lambda: motor.seteaza_expresie("atent")),
                (2500, lambda: motor.seteaza_expresie("ganditor")), (4500, lambda: motor.seteaza_expresie("fericit")),
                (4600, lambda: None if stare["vorbire"] else comuta_vorbire()),
                (8600, lambda: comuta_vorbire() if stare["vorbire"] else None),
                (8700, lambda: motor.seteaza_expresie("neutru"))]
        for ms, fn in pasi:
            root.after(ms, fn)

    comenzi = tk.Frame(root, bg=FUNDAL)
    comenzi.pack(fill="x", padx=4, pady=(0, 6))
    for text, fn in (("vorbire (spatiu)", comuta_vorbire), ("flux complet (f)", flux),
                     ("somn (s)", lambda _e=None: motor.adoarme()), ("trezire (t)", lambda _e=None: motor.activitate())):
        tk.Button(comenzi, text=text, font=("Arial", 9, "bold"), bg="#3B4252", fg="white", relief="flat",
                  command=fn).pack(side="left", padx=2)
    root.bind("<space>", comuta_vorbire)
    root.bind("f", flux)
    root.bind("s", lambda _e: motor.adoarme())
    root.bind("t", lambda _e: motor.activitate())

    def misca(e):
        x = (e.x / (latime * zoom)) * 2 - 1
        y = (e.y / (inaltime * zoom)) * 2 - 1
        motor.privire.seteaza(x, y, sursa="camera", timeout_s=1.2)

    def trage(e):
        misca(e)
        stare["trage"] += 1
        if stare["trage"] == 12:
            motor.atinge("mangaiere")

    def elibereaza(_e):
        if stare["trage"] < 12:
            motor.atinge("tap")
        stare["trage"] = 0

    afisaj.canvas.bind("<Motion>", misca)
    afisaj.canvas.bind("<B1-Motion>", trage)
    afisaj.canvas.bind("<ButtonRelease-1>", elibereaza)

    def tick():
        if stare["vorbire"]:
            motor.seteaza_nivel_gura(nivel_vorbire_simulat(time.monotonic() - stare["t_vorbire"]))
        st = motor.tick()
        stare["tick"] += 1
        if st is not None and afisaj.aplica(st):
            stare["desen"] += 1
        acum = time.monotonic()
        if acum - stare["t_stat"] >= 1.0:
            dt = acum - stare["t_stat"]
            cpu = 100.0 * (time.process_time() - stare["cpu"]) / dt
            info.config(text=f"{motor.expresie_curenta:<12} tick/s={stare['tick'] / dt:4.1f}  desene/s={stare['desen'] / dt:4.1f}  "
                             f"CPU={cpu:4.1f}%  cache={len(afisaj._cache)}  randari={afisaj.randari}  somn={motor.stadiu_somn}")
            stare.update(tick=0, desen=0, t_stat=acum, cpu=time.process_time())
        root.after(max(1, int(motor.interval_urmator() * 1000)), tick)

    tick()
    if auto_inchide > 0:
        root.after(int(auto_inchide * 1000), root.destroy)
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(description="Mod de dezvoltare pentru fata robotului")
    ap.add_argument("--export", metavar="DIR", help="scrie plansele PNG in DIR si iese")
    ap.add_argument("--latime", type=int, default=480)
    ap.add_argument("--inaltime", type=int, default=320)
    ap.add_argument("--zoom", type=int, default=2)
    ap.add_argument("--auto-inchide", type=float, default=0.0, help="inchide fereastra dupa atatea secunde (test)")
    args = ap.parse_args()
    if args.export:
        exporta(args.export, args.latime, args.inaltime)
    else:
        ruleaza_interactiv(args.latime, args.inaltime, args.zoom, args.auto_inchide)
    return 0


if __name__ == "__main__":
    sys.exit(main())
