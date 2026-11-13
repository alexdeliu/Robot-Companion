"""
Randarea fetei cu Pillow: transforma o stare (din MotorFata) in imagini mici, antialiasate, pentru
fiecare componenta (ochi, gura, roseata). Fara Tk: acelasi cod deseneaza pe Pi si exporta plansele PNG.

Fiecare componenta are o "cheie" de numere intregi (pixeli). Doua stari cu aceeasi cheie dau aceeasi
imagine, deci afisajul le poate tine in cache si redeseneaza doar ce s-a schimbat.
"""
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .parametri import FUNDAL_RGB, LATURI, hex_rgb

SS_OCHI = 2
SS_GURA = 3
FANTA_MIN = 7          # ochiul inchis ramane o linie luminoasa de atatia pixeli (la 480x320)
ROZ = hex_rgb("#E06C75")
RAPORT_IRIS = 1.34      # irisul (o nuanta mai inchisa a ochiului) e cu atat mai mare decat pupila
_PUPILE = {}


def _lim(v, jos, sus):
    return jos if v < jos else sus if v > sus else v


def _culoare(st):
    return tuple(min(255, int(round(_lim(st[c], 0.0, 255.0) / 8.0)) * 8) for c in ("r", "g", "b"))


class Geometrie:
    """Asezarea fetei pe ecran. Fata e lata si joasa: costul pe ecranul SPI creste cu randurile atinse."""

    def __init__(self, latime=480, inaltime=320):
        s = min(latime / 480.0, inaltime / 320.0)
        self.W, self.H, self.s = latime, inaltime, s
        self.ochi_w, self.ochi_h = 116.0 * s, 76.0 * s
        self.max_lat, self.max_inalt = 1.1, 1.18
        self.marg_sus, self.marg_jos, self.marg_x = int(round(16 * s)), int(round(11 * s)), int(round(12 * s))
        self.h_max = int(math.ceil(self.ochi_h * self.max_inalt))
        self.cutie_w = int(math.ceil(self.ochi_w * self.max_lat)) + 2 * self.marg_x
        self.cutie_h = self.h_max + self.marg_sus + self.marg_jos
        self.cy_local = self.marg_sus + self.h_max / 2.0
        self.cy_ochi = int(inaltime * 0.41)
        dx = int(latime * 0.235)
        self.cx = {"s": latime // 2 - dx, "d": latime // 2 + dx}
        self.raza_pupila = 0.25 * self.ochi_h

        self.g_a, self.g_curb, self.g_desch = 58.0 * s, 12.0 * s, 27.0 * s
        self.g_gros = max(3, int(round(8 * s)))
        self.g_cutie_w = int(round(2 * self.g_a + 24 * s))
        self.g_sus, self.g_jos = int(round(24 * s)), int(round(39 * s))
        self.gx, self.gy = latime // 2, int(inaltime * 0.695)

        self.ros_w, self.ros_h = int(round(72 * s)), int(round(26 * s))
        self._masca_margine = None

    def cutie_ochi(self, latura):
        x0 = self.cx[latura] - self.cutie_w // 2
        y0 = self.cy_ochi - int(round(self.cy_local))
        return (x0, y0, x0 + self.cutie_w, y0 + self.cutie_h)

    def cutie_gura(self):
        x0 = self.gx - self.g_cutie_w // 2
        return (x0, self.gy - self.g_sus, x0 + self.g_cutie_w, self.gy + self.g_jos)

    def cutie_roseata(self, latura):
        semn = -1 if latura == "s" else 1
        x0 = self.cx[latura] + semn * int(round(14 * self.s)) - self.ros_w // 2
        y0 = self.cutie_ochi(latura)[3] + 1
        return (x0, y0, x0 + self.ros_w, y0 + self.ros_h)

    def cutii(self):
        rez = {"gura": self.cutie_gura()}
        for latura in LATURI:
            rez[f"ochi_{latura}"] = self.cutie_ochi(latura)
            rez[f"ros_{latura}"] = self.cutie_roseata(latura)
        return rez

    def banda(self):
        """Primul si ultimul rand pe care fata le poate modifica."""
        cutii = self.cutii().values()
        return min(c[1] for c in cutii), max(c[3] for c in cutii)

    def masca_margine(self):
        if self._masca_margine is None:
            m = Image.new("L", (self.cutie_w, self.cutie_h), 0)
            ImageDraw.Draw(m).rectangle([5, 5, self.cutie_w - 6, self.cutie_h - 6], fill=255)
            self._masca_margine = m.filter(ImageFilter.GaussianBlur(2.5))
        return self._masca_margine


# ------------------------------------------------------------------------------ ochi

def cheie_ochi(geo, st, latura):
    sufix = "_" + latura
    w = int(round(geo.ochi_w * _lim(st["lat" + sufix], 0.5, geo.max_lat)))
    h = int(round(geo.ochi_h * _lim(st["inalt" + sufix], 0.3, geo.max_inalt)))
    k_sus = int(round(_lim(st["sus" + sufix], 0.0, 1.0) * h))
    k_jos = int(round(_lim(st["jos" + sufix], 0.0, 1.0) * h))
    k_incl = int(round(_lim(st["incl" + sufix], -1.0, 1.0) * 0.26 * h))
    k_as = int(round(_lim(st["arc_sus" + sufix], -1.0, 1.0) * 0.20 * h))
    k_aj = int(round(_lim(st["arc_jos" + sufix], -1.0, 1.0) * 0.32 * h))
    r = int(round(geo.raza_pupila * _lim(st["pm" + sufix], 0.0, 1.4)))
    if r < 3:
        r = px = py = 0
    else:
        r_iris = r * RAPORT_IRIS
        px = int(round(_lim(st["px"], -1.0, 1.0) * max(0.0, w / 2.0 - r_iris - 4 * geo.s)))
        py = int(round(_lim(st["py"], -1.0, 1.0) * max(0.0, h / 2.0 - r_iris - 2 * geo.s)))
    spr = int(round(_lim(st["spr" + sufix], 0.0, 1.0) * 3))
    spr_y = int(round(_lim(st["spr_y" + sufix], -1.0, 1.0) * 4 * geo.s)) if spr else 0
    spr_i = int(round(_lim(st["spr_incl" + sufix], -1.0, 1.0) * 6 * geo.s)) if spr else 0
    glow = int(round(_lim(st["glow"], 0.0, 1.0) * 8))
    return (w, h, k_sus, k_jos, k_incl, k_as, k_aj, px, py, r, spr, spr_y, spr_i, glow, _culoare(st))


def _pupila(r, culoare):
    """Iris (nuanta inchisa a ochiului) + pupila intunecata + punct de lumina; (imagine RGB, masca alfa)."""
    cheie = (r, culoare)
    if cheie not in _PUPILE:
        if len(_PUPILE) > 400:
            _PUPILE.clear()
        ss = 4
        raza = int(math.ceil(r * RAPORT_IRIS))
        d = 2 * raza + 2
        c = d * ss / 2.0
        alfa = Image.new("L", (d * ss, d * ss), 0)
        ImageDraw.Draw(alfa).ellipse([ss, ss, (d - 1) * ss, (d - 1) * ss], fill=255)
        iris = tuple(int(v * 0.58 + f * 0.42 * 0.5) for v, f in zip(culoare, FUNDAL_RGB))
        img = Image.new("RGB", (d * ss, d * ss), iris)
        des = ImageDraw.Draw(img)
        des.ellipse([c - r * ss, c - r * ss, c + r * ss, c + r * ss], fill=FUNDAL_RGB)
        rl = 0.27 * r * ss
        lx, ly = c + 0.42 * r * ss, c - 0.44 * r * ss
        des.ellipse([lx - rl, ly - rl, lx + rl, ly + rl], fill=(255, 255, 255))
        _PUPILE[cheie] = (img.resize((d, d), Image.Resampling.LANCZOS),
                          alfa.resize((d, d), Image.Resampling.LANCZOS), raza)
    return _PUPILE[cheie]


def randeaza_ochi(geo, cheie, latura):
    w, h, k_sus, k_jos, k_incl, k_as, k_aj, px, py, r, spr, spr_y, spr_i, glow, culoare = cheie
    ss, bw, bh = SS_OCHI, geo.cutie_w, geo.cutie_h
    cx, cy = bw / 2.0, geo.cy_local
    x0, y0, x1, y1 = cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0
    semn = 1 if latura == "s" else -1   # capatul dinspre nas e la +x pentru ochiul din stanga

    m = Image.new("L", (bw * ss, bh * ss), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([x0 * ss, y0 * ss, x1 * ss, y1 * ss], radius=min(w, h) * 0.44 * ss, fill=255)

    fanta = max(2.0, FANTA_MIN * geo.s)
    n = 14
    sus, jos = [], []
    for i in range(n + 1):
        u = -1.0 + 2.0 * i / n
        f = 1.0 - u * u
        x = (cx + u * (w / 2.0 + 2.0)) * ss
        yb = max(y1 - k_jos - k_aj * f, y0 + fanta + 1.0)
        yt = min(y0 + k_sus + k_incl * u * semn + k_as * f, yb - fanta)
        sus.append((x, yt * ss))
        jos.append((x, yb * ss))
    xa, xb = sus[0][0], sus[-1][0]
    d.polygon([(xa, 0), (xb, 0)] + sus[::-1], fill=0)
    d.polygon([(xa, bh * ss), (xb, bh * ss)] + jos[::-1], fill=0)

    if spr:
        gros = int(round(max(1.0, (3 + spr) * geo.s) * ss))
        jum = w * 0.40
        by = y0 - 6.0 * geo.s + spr_y
        p1 = ((cx - jum) * ss, (by - spr_i * semn) * ss)
        p2 = ((cx + jum) * ss, (by + spr_i * semn) * ss)
        d.line([p1, p2], fill=255, width=gros)
        for p in (p1, p2):
            d.ellipse([p[0] - gros / 2.0, p[1] - gros / 2.0, p[0] + gros / 2.0, p[1] + gros / 2.0], fill=255)

    masca = m.resize((bw, bh), Image.Resampling.BOX)
    img = Image.new("RGB", (bw, bh), FUNDAL_RGB)
    if glow:
        halou = masca.resize((max(1, bw // 4), max(1, bh // 4)), Image.Resampling.BOX)
        halou = halou.filter(ImageFilter.GaussianBlur(max(1.0, geo.marg_jos / 5.0)))
        halou = ImageChops.multiply(halou.resize((bw, bh), Image.Resampling.BILINEAR), geo.masca_margine())
        tarie = glow / 8.0 * 0.7
        img.paste(culoare, (0, 0, bw, bh), halou.point(lambda v: int(v * tarie)))
    img.paste(culoare, (0, 0, bw, bh), masca)

    if r:
        pupila, alfa, raza = _pupila(r, culoare)
        bx, by = int(round(cx + px - raza - 1)), int(round(cy + py - raza - 1))
        cutie = (bx, by, bx + pupila.width, by + pupila.height)
        img.paste(pupila, cutie, ImageChops.multiply(alfa, masca.crop(cutie)))
    return img


# ------------------------------------------------------------------------------ gura

def cheie_gura(geo, st):
    rot = _lim(st["g_rot"], 0.0, 1.0)
    viz = _lim(st["g_viz"], 0.0, 1.0)
    gros = 0 if viz < 0.05 else max(2, int(round(geo.g_gros * (0.5 + 0.5 * viz))))
    return (int(round(geo.g_a * _lim(st["g_lat"], 0.1, 1.0) * (1.0 - 0.5 * rot))),
            int(round(geo.g_curb * _lim(st["g_curb"], -1.0, 1.0))),
            int(round(geo.g_desch * _lim(st["g_desch"], 0.0, 1.0))),
            int(round(rot * 4)),
            int(round(4 * geo.s * _lim(st["g_unda"], 0.0, 1.0))),
            int(round(7 * geo.s * _lim(st["g_stramb"], -1.0, 1.0))),
            gros, int(round(_lim(st["glow"], 0.0, 1.0) * 8)), _culoare(st))


def randeaza_gura(geo, cheie):
    a, curb, desch, rot, unda, stramb, gros, glow, culoare = cheie
    ss = SS_GURA
    bw, bh = geo.g_cutie_w, geo.g_sus + geo.g_jos
    img = Image.new("RGB", (bw, bh), FUNDAL_RGB)
    if not gros:
        return img
    cx, cy = bw / 2.0, float(geo.g_sus)
    putere = 1.0 - 0.5 * rot / 4.0
    parte_sus = 0.3 + 0.2 * rot / 4.0   # gura rotunda ("o") se deschide aproape simetric
    n = 22
    sus, jos = [], []
    for i in range(n + 1):
        u = -1.0 + 2.0 * i / n
        f = max(0.0, 1.0 - u * u)
        yc = cy + curb * (f - 0.5) - stramb * u * 0.5 + unda * math.sin(2.5 * math.pi * u)
        x = (cx + u * a) * ss
        sus.append((x, (yc - desch * parte_sus * f ** (putere if rot < 3 else 0.5)) * ss))
        jos.append((x, (yc + desch * (1.0 - parte_sus) * f ** (putere * 0.6)) * ss))

    m = Image.new("L", (bw * ss, bh * ss), 0)
    d = ImageDraw.Draw(m)
    if desch > 0:
        d.polygon(sus + jos[::-1], fill=255)
    g = gros * ss
    d.line(sus, fill=255, width=g, joint="curve")
    d.line(jos, fill=255, width=g, joint="curve")
    for p in (sus[0], sus[-1]):
        d.ellipse([p[0] - g / 2.0, p[1] - g / 2.0, p[0] + g / 2.0, p[1] + g / 2.0], fill=255)
    masca = m.resize((bw, bh), Image.Resampling.BOX)
    if glow:
        halou = masca.filter(ImageFilter.GaussianBlur(3.0 * geo.s))
        tarie = glow / 8.0 * 0.45
        img.paste(culoare, (0, 0, bw, bh), halou.point(lambda v: int(v * tarie)))
    img.paste(culoare, (0, 0, bw, bh), masca)
    return img


# ------------------------------------------------------------------------------ roseata

def randeaza_roseata(geo, nivel):
    bw, bh = geo.ros_w, geo.ros_h
    m = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(m).ellipse([bw * 0.18, bh * 0.28, bw * 0.82, bh * 0.72], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(3.4 * geo.s))
    tarie = nivel / 4.0 * 0.95
    img = Image.new("RGB", (bw, bh), FUNDAL_RGB)
    img.paste(ROZ, (0, 0, bw, bh), m.point(lambda v: int(v * tarie)))
    return img


# ------------------------------------------------------------------------------ compunere

def componente(geo, st):
    """Lista (element, cheie_cache, functie_randare) pentru starea data; functia e None daca elementul e gol."""
    rez = []
    for latura in LATURI:
        k = cheie_ochi(geo, st, latura)
        rez.append((f"ochi_{latura}", ("ochi", latura, k), lambda k=k, latura=latura: randeaza_ochi(geo, k, latura)))
    kg = cheie_gura(geo, st)
    rez.append(("gura", ("gura", kg), lambda kg=kg: randeaza_gura(geo, kg)))
    nivel = int(round(_lim(st["roseata"], 0.0, 1.0) * 4))
    for latura in LATURI:
        rez.append((f"ros_{latura}", ("ros", nivel), (lambda nivel=nivel: randeaza_roseata(geo, nivel)) if nivel else None))
    return rez


def compune_cadru(geo, st):
    """Cadru complet (pentru export si teste); pe robot se deseneaza doar componentele schimbate."""
    img = Image.new("RGB", (geo.W, geo.H), FUNDAL_RGB)
    cutii = geo.cutii()
    for element, _cheie, fn in componente(geo, st):
        if fn is not None:
            img.paste(fn(), cutii[element][:2])
    return img
