"""
Parametrii fetei si tabelul de expresii. Fara Tk si fara Pillow, ca sa poata fi testat offline.

O expresie este un dictionar plat {parametru: numar}. Parametrii de ochi exista pentru fiecare
latura ("_s" = ochiul din stanga ecranului, "_d" = cel din dreapta), deci fata poate fi asimetrica.

Ochi:
  sus, jos        cat acopera pleoapa de sus / de jos din inaltimea ochiului (0..1)
  incl            inclinarea pleoapei de sus: +1 capatul dinspre nas coboara (incruntat), -1 urca (trist)
  arc_sus         curbura pleoapei de sus (+ coboara la mijloc)
  arc_jos         curbura pleoapei de jos (+ urca la mijloc: ochi "zambitor")
  lat, inalt      scara ochiului pe latime / inaltime
  pm              marimea pupilei (0 = fara pupila)
  spr, spr_y, spr_incl   spranceana: vizibilitate (0..1), pozitie (-1 sus .. 1 jos), inclinare
Gura:
  g_lat, g_curb (+ zambet), g_desch, g_rot (rotunjire "o"), g_unda (ondulata), g_stramb (colt ridicat), g_viz
Comun:
  glow, roseata, px, py (deplasarea privirii ceruta de expresie), r, g, b (culoarea)
"""

FUNDAL = "#1E222A"


def hex_rgb(culoare):
    return tuple(int(culoare[i:i + 2], 16) for i in (1, 3, 5))


FUNDAL_RGB = hex_rgb(FUNDAL)

CULORI = {
    "albastru": "#61AFEF",
    "verde": "#98C379",
    "galben": "#E5C07B",
    "rosu": "#E06C75",
    "mov": "#C678DD",
    "cyan": "#56B6C2",
    "gri": "#7C8696",
}

LATURI = ("s", "d")

IMPLICIT_OCHI = {
    "sus": 0.0, "jos": 0.0, "incl": 0.0, "arc_sus": 0.0, "arc_jos": 0.0,
    "lat": 1.0, "inalt": 1.0, "pm": 1.0, "spr": 0.0, "spr_y": 0.0, "spr_incl": 0.0,
}

IMPLICIT_COMUN = {
    "g_lat": 0.55, "g_curb": 0.25, "g_desch": 0.0, "g_rot": 0.0, "g_unda": 0.0, "g_stramb": 0.0, "g_viz": 1.0,
    "glow": 0.5, "roseata": 0.0, "px": 0.0, "py": 0.0,
}


def expresie(culoare="albastru", **valori):
    """Construieste o expresie completa; "sus=0.3" seteaza ambii ochi, "sus_s=0.3" doar pe cel stang."""
    rez = {}
    for cheie, val in IMPLICIT_OCHI.items():
        for latura in LATURI:
            rez[f"{cheie}_{latura}"] = val
    rez.update(IMPLICIT_COMUN)
    r, g, b = hex_rgb(CULORI[culoare])
    rez.update(r=float(r), g=float(g), b=float(b))
    for cheie, val in valori.items():
        if cheie in IMPLICIT_OCHI:
            for latura in LATURI:
                rez[f"{cheie}_{latura}"] = float(val)
    for cheie, val in valori.items():
        if cheie in IMPLICIT_OCHI:
            continue
        if cheie not in rez:
            raise KeyError(f"Parametru de fata necunoscut: {cheie}")
        rez[cheie] = float(val)
    return rez


EXPRESII = {
    "neutru": expresie("albastru", g_curb=0.3),
    "fericit": expresie("verde", jos=0.2, arc_jos=0.9, py=-0.45, g_curb=0.95, g_lat=0.7, glow=0.6),
    "ras": expresie("verde", sus=0.5, jos=0.5, arc_jos=0.9, pm=0.0, g_curb=1.0, g_desch=0.7, g_lat=0.66, glow=0.7),
    "trist": expresie("albastru", sus=0.22, incl=-0.9, py=0.5, g_curb=-0.8, g_lat=0.45, glow=0.3),
    "surprins": expresie("cyan", inalt=1.2, lat=0.94, pm=0.72, spr=1.0, spr_y=-1.0,
                         g_rot=1.0, g_desch=0.8, g_lat=0.62, g_curb=0.0, glow=0.7),
    "confuz": expresie("galben", sus_s=0.42, incl_s=0.35, inalt_d=1.1, spr_d=1.0, spr_y_d=-0.8, spr_incl_d=-0.3,
                       g_unda=1.0, g_curb=0.0, g_lat=0.5, px=-0.2),
    "ganditor": expresie("galben", sus=0.22, px=0.6, py=-0.7, g_curb=0.0, g_lat=0.32, g_stramb=0.5),
    "curios": expresie("cyan", inalt_d=1.16, pm=1.15, sus_s=0.12, spr_d=1.0, spr_y_d=-0.7,
                       g_curb=0.4, g_lat=0.38, px=0.25, glow=0.6),
    "atent": expresie("albastru", inalt=1.12, pm=1.22, g_curb=0.25, g_lat=0.36, glow=0.85),
    "somnoros": expresie("gri", sus=0.56, arc_sus=0.35, jos=0.08, py=0.4, g_curb=0.0, g_lat=0.34, glow=0.28),
    "adormit": expresie("gri", sus=0.55, jos=0.45, arc_jos=-0.7, pm=0.0, g_curb=0.15, g_lat=0.24, g_viz=0.7,
                        glow=0.18),
    "plictisit": expresie("albastru", sus=0.46, px=0.55, py=-0.1, g_curb=-0.2, g_lat=0.4, glow=0.35),
    "jenat": expresie("albastru", sus=0.26, jos=0.08, px=-0.5, py=0.8, roseata=1.0,
                      g_unda=0.6, g_curb=0.25, g_lat=0.36),
    "mandru": expresie("verde", sus=0.3, jos=0.26, arc_jos=0.7, py=-0.2, g_curb=0.75, g_stramb=0.4, g_lat=0.5),
    "eroare": expresie("rosu", sus=0.16, incl=-0.6, pm=0.6, spr=1.0, spr_incl=-0.8, spr_y=-0.2,
                       g_unda=1.0, g_curb=-0.3, g_lat=0.5, glow=0.4),
    "entuziasmat": expresie("verde", inalt=1.16, pm=1.25, jos=0.12, arc_jos=0.9, py=-0.2,
                            g_desch=0.5, g_curb=1.0, g_lat=0.68, glow=0.9),
    "obosit": expresie("gri", sus=0.5, incl=-0.45, jos=0.14, py=0.5, g_curb=-0.3, g_lat=0.4, glow=0.24),
    "ironic": expresie("mov", sus_s=0.46, incl_s=0.3, sus_d=0.14, px=0.4,
                       g_stramb=1.0, g_curb=0.5, g_lat=0.5),
    "wink": expresie("verde", sus_d=0.5, jos_d=0.5, arc_jos_d=0.9, pm_d=0.0, jos_s=0.12, arc_jos_s=0.7,
                     g_curb=0.85, g_stramb=0.45, g_lat=0.52),
    "sceptic": expresie("galben", sus_s=0.5, incl_s=0.5, inalt_d=1.08, spr_d=1.0, spr_y_d=-1.0, px=-0.35,
                        g_curb=-0.2, g_stramb=-0.7, g_lat=0.4),
    "speriat": expresie("cyan", inalt=1.22, lat=0.9, pm=0.5, spr=1.0, spr_y=-0.6, spr_incl=-0.7,
                        g_rot=0.8, g_desch=0.4, g_lat=0.5, g_curb=-0.3, glow=0.8),
    "afectuos": expresie("mov", jos=0.2, arc_jos=0.9, pm=1.3, py=-0.2, roseata=1.0,
                         g_curb=0.85, g_lat=0.44, glow=0.65),
    "muzica": expresie("mov", sus=0.5, jos=0.5, arc_jos=0.9, pm=0.0, g_curb=0.7, g_lat=0.46, glow=0.55),
    "offline": expresie("gri", sus=0.34, incl=-0.3, pm=0.8, py=0.2, g_curb=-0.35, g_lat=0.36, glow=0.14),
}
