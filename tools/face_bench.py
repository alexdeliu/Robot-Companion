"""
Benchmark de randare pentru fata robotului (faza F2).

Standalone: nu importa nimic din proiect, nu scrie fisiere, nu foloseste microfonul sau reteaua.
Compara trei variante de randare cu aceeasi fata animata (2 ochi cu pleoape, pupile, glow, gura):
  z = baza (fereastra statica, fara fata)
  a = Tk Canvas vectorial + sprite-uri opace
  b = Pillow -> ImageTk.PhotoImage pe regiunile modificate
  c = pygame/SDL in proces separat (fara GIL comun cu wake word-ul)
In paralel ruleaza un fir care simuleaza bucla wake word (citire 1024 esantioane la 128 ms + DSP Python).

Exemplu pe Pi:  DISPLAY=:0 venv/bin/python face_bench.py --durata 60 --eticheta "serviciu oprit"
Exemplu pe PC:  python tools/face_bench.py --durata 5
"""
import os
import sys
import json
import math
import time
import shutil
import random
import argparse
import threading
import subprocess
from array import array

BG = "#1E222A"
ACCENT = "#61AFEF"
# Masurat pe Pi 3 B+ cu ILI9486/fbtft la 20 MHz (2026-11-11, fbtft debug=32): 2.3-2.4 MB/s reali,
# iar la 30 fps randate panoul a afisat ~15 actualizari/s (fbtft asteapta ~30-40 ms inainte de trimitere).
EFICIENTA_SPI = 0.94
ASTEPTARE_FBTFT_S = 0.035
NUME_FAZE = ("idle", "vorbire", "expresii")
FAZA_FIXA = None   # 0/1/2 = ruleaza o singura faza in bucla (pentru masurarea panoului)
COMPACT = False    # fata joasa: ochi si gura pe mai putine randuri, ochii stau pe loc la vorbire


def _rgb(hex_c):
    return tuple(int(hex_c[i:i + 2], 16) for i in (1, 3, 5))


BG_RGB = _rgb(BG)
ACC_RGB = _rgb(ACCENT)


# --------------------------------------------------------------------------- model animatie

def _zg(n):
    x = math.sin(n * 12.9898) * 43758.5453
    return x - math.floor(x)


def _neted(a):
    a = max(0.0, min(1.0, a))
    return a * a * (3.0 - 2.0 * a)


# (deschidere ochi, inclinare pleoapa, zambet)
EXPRESII = [(1.0, 0.0, 0.6), (0.72, 0.5, 1.0), (1.0, -0.6, -0.5), (0.55, 0.0, 0.1)]


def stare_fata(t):
    """Stare determinista: 0-4 s idle, 4-8 s vorbire, 8-12 s tranzitii de expresie, apoi se repeta."""
    tc = t % 12.0 if FAZA_FIXA is None else FAZA_FIXA * 4.0 + (t % 4.0)
    clip = 0.0
    for t0 in (1.0, 3.2, 3.5, 6.0, 9.4):
        d = tc - t0
        if 0.0 <= d < 0.16:
            clip = max(clip, math.sin(math.pi * d / 0.16))

    k = int(t / 0.9)
    f = _neted((t - k * 0.9) / 0.08)
    gx = (_zg(k - 1) * 2 - 1) + ((_zg(k) * 2 - 1) - (_zg(k - 1) * 2 - 1)) * f
    gy = (_zg(k - 0.5) * 2 - 1) + ((_zg(k + 0.5) * 2 - 1) - (_zg(k - 0.5) * 2 - 1)) * f

    gura = 0.0
    if 4.0 <= tc < 8.0:
        gx *= 0.0 if COMPACT else 0.3
        gy *= 0.0 if COMPACT else 0.3
        gura = abs(math.sin(2 * math.pi * 3.1 * t)) * (0.55 + 0.45 * math.sin(2 * math.pi * 0.7 * t))

    expr = EXPRESII[0]
    if tc >= 8.0:
        i = int(tc - 8.0)
        fe = _neted((tc - 8.0 - i) / 0.3)
        e0, e1 = EXPRESII[i % 4], EXPRESII[(i + 1) % 4]
        expr = tuple(a + (b - a) * fe for a, b in zip(e0, e1))

    return {"clip": clip, "gx": gx, "gy": gy, "gura": max(0.0, gura),
            "desch": expr[0], "incl": expr[1], "zambet": expr[2]}


class Geometrie:
    def __init__(self, w, h):
        self.W, self.H = w, h
        s = min(w / 480.0, h / 320.0)
        self.s = s
        self.kg = 0.67 if COMPACT else 1.0
        self.ew, self.eh, self.er = int(110 * s), int((60 if COMPACT else 80) * s), int((22 if COMPACT else 28) * s)
        self.ey = int(h * 0.44)
        self.ochi_x = (int(w * 0.29), int(w * 0.71))
        self.pr = int((15 if COMPACT else 19) * s)
        self.dp = 2 * self.pr + 2
        self.cursa_x = self.ew // 2 - self.pr - int(8 * s)
        self.cursa_y = self.eh // 2 - self.pr - int(8 * s)
        self.gx, self.gy = w // 2, int(h * 0.665)
        self.ga = int(46 * s)
        self.randuri_ochi = (self.ey - self.eh // 2 - 3, self.ey + self.eh // 2 + 3)
        self.randuri_gura = (self.gy - int(14 * s * self.kg), self.gy + int(38 * s * self.kg))

    def dreptunghi_ochi(self, i):
        x0 = self.ochi_x[i] - self.ew // 2 - 3
        return (x0, self.randuri_ochi[0], x0 + self.ew + 6, self.randuri_ochi[1])

    def dreptunghi_gura(self):
        return (self.gx - self.ga - 6, self.randuri_gura[0], self.gx + self.ga + 6, self.randuri_gura[1])

    def pozitie_pupila(self, i, st):
        return (self.ochi_x[i] + int(round(st["gx"] * self.cursa_x)),
                self.ey + int(round(st["gy"] * self.cursa_y)))

    def poligon_pleoapa(self, i, st):
        x0, top, x1, jos = self.dreptunghi_ochi(i)
        inch = max(st["clip"], 1.0 - st["desch"])
        d = st["incl"] * (-1 if i == 0 else 1) * 10 * self.s
        yl = int(max(top, min(jos, top + inch * (jos - top) + d)))
        yr = int(max(top, min(jos, top + inch * (jos - top) - d)))
        return (x0, top, x1, top, x1, yr, x0, yl)

    def poligon_gura(self, st):
        s, z, g = self.s * self.kg, st["zambet"], st["gura"]
        yc = self.gy - z * 6 * s
        yu = self.gy + z * 6 * s - g * 4 * s
        yl = self.gy + z * 6 * s + 5 * s + g * 26 * s
        n = 8
        sus, jos = [], []
        for k in range(n + 1):
            u = -1.0 + 2.0 * k / n
            f = 1.0 - u * u
            x = int(round(self.gx + u * self.ga))
            sus += [x, int(round(yc + (yu - yc) * f))]
            jos = [x, int(round(yc + (yl - yc) * f))] + jos
        return tuple(sus + jos)


def construieste_sprite(geo):
    """Fundal cu glow, fundal cu ochii desenati antialiasat si pupila opaca (pe culoarea ochiului)."""
    from PIL import Image, ImageDraw, ImageFilter
    s4 = 4
    masca = Image.new("L", (geo.W, geo.H), 0)
    d = ImageDraw.Draw(masca)
    for ex in geo.ochi_x:
        d.rounded_rectangle([ex - geo.ew // 2, geo.ey - geo.eh // 2, ex + geo.ew // 2, geo.ey + geo.eh // 2],
                            radius=geo.er, fill=255)
    glow = masca.filter(ImageFilter.GaussianBlur(geo.eh * 0.22)).point(lambda v: int(v * 0.5))
    fundal = Image.new("RGB", (geo.W, geo.H), BG_RGB)
    fundal.paste(ACC_RGB, (0, 0, geo.W, geo.H), glow)

    mare = Image.new("L", (geo.ew * s4, geo.eh * s4), 0)
    ImageDraw.Draw(mare).rounded_rectangle([0, 0, geo.ew * s4 - 1, geo.eh * s4 - 1], radius=geo.er * s4, fill=255)
    masca_ochi = mare.resize((geo.ew, geo.eh), Image.Resampling.LANCZOS)
    fundal_ochi = fundal.copy()
    for ex in geo.ochi_x:
        x0, y0 = ex - geo.ew // 2, geo.ey - geo.eh // 2
        fundal_ochi.paste(ACC_RGB, (x0, y0, x0 + geo.ew, y0 + geo.eh), masca_ochi)

    dp = geo.dp
    pm = Image.new("RGB", (dp * s4, dp * s4), ACC_RGB)
    dd = ImageDraw.Draw(pm)
    dd.ellipse([s4, s4, (dp - 1) * s4, (dp - 1) * s4], fill=BG_RGB)
    rh = dp * s4 * 0.16
    cx, cy = dp * s4 * 0.66, dp * s4 * 0.30
    dd.ellipse([cx - rh, cy - rh, cx + rh, cy + rh], fill=(255, 255, 255))
    pupila = pm.resize((dp, dp), Image.Resampling.LANCZOS)
    return {"fundal": fundal, "fundal_ochi": fundal_ochi, "pupila": pupila}


# --------------------------------------------------------------------------- simulare wake word

class SimWake(threading.Thread):
    """Aceeasi sarcina Python ca _StreamDSP16k din ears/wake_word.py, pe audio sintetic."""
    PERIOADA = 0.128

    def __init__(self):
        super().__init__(name="SimWake", daemon=True)
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()
        rnd = random.Random(1)
        self._chunk = array("h", [rnd.randint(-40, 40) for _ in range(1024)]).tobytes()
        rc = 1.0 / (2.0 * math.pi * 100.0)
        self._alpha = rc / (rc + 1.0 / 8000.0)
        self._gain = 3.2
        self._dc = self._px = self._py = 0.0
        self._prev_s = 0
        self._cpu_fir = 0.0
        self.reseteaza()

    def reseteaza(self):
        with self._lock:
            self._intarzieri, self._dsp, self._restanta_max = [], [], 0.0
            self._cpu0 = self._cpu_fir

    def statistici(self):
        with self._lock:
            return {"intarzieri": list(self._intarzieri), "dsp": list(self._dsp),
                    "restanta_max": self._restanta_max, "cpu_s": self._cpu_fir - self._cpu0}

    def opreste(self):
        self._stop_evt.set()

    def _proceseaza(self):
        samples = array("h", self._chunk)
        n = len(samples)
        self._dc = 0.90 * self._dc + 0.10 * (sum(samples) / float(n))
        alpha, gain, px, py, dc = self._alpha, self._gain, self._px, self._py, self._dc
        procesate = array("h", [0] * n)
        for i in range(n):
            x = float(samples[i]) - dc
            y = alpha * (py + x - px)
            px = x
            py = y
            val = y * gain
            if val > 29000.0:
                val = 29000.0 + (val - 29000.0) * 0.25
            elif val < -29000.0:
                val = -29000.0 + (val + 29000.0) * 0.25
            procesate[i] = max(-32768, min(32767, int(val)))
        self._px, self._py = px, py
        out = array("h", [0] * (n * 2))
        prev_s = self._prev_s
        for i in range(n):
            curr = procesate[i]
            out[2 * i] = (prev_s + curr) >> 1
            out[2 * i + 1] = curr
            prev_s = curr
        self._prev_s = prev_s
        return out.tobytes()

    def run(self):
        urm = time.perf_counter() + self.PERIOADA
        while not self._stop_evt.is_set():
            rest = urm - time.perf_counter()
            if rest > 0:
                time.sleep(rest)
            t_a = time.perf_counter()
            self._proceseaza()
            t_b = time.perf_counter()
            with self._lock:
                self._intarzieri.append(max(0.0, t_a - urm))
                self._dsp.append(t_b - t_a)
                self._restanta_max = max(self._restanta_max, t_b - (urm + self.PERIOADA))
                self._cpu_fir = time.thread_time()
            urm += self.PERIOADA


# --------------------------------------------------------------------------- masuratori sistem

def _pct(valori, p):
    if not valori:
        return 0.0
    v = sorted(valori)
    return v[min(len(v) - 1, int(round(p / 100.0 * (len(v) - 1))))]


def _proc_stat():
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            v = [int(x) for x in f.readline().split()[1:]]
        return sum(v) - v[3] - v[4], sum(v)
    except (OSError, ValueError, IndexError):
        return None


def _pid_dupa_nume(nume):
    try:
        for p in os.listdir("/proc"):
            if p.isdigit():
                try:
                    with open(f"/proc/{p}/comm", "r", encoding="utf-8") as f:
                        if f.read().strip() == nume:
                            return int(p)
                except OSError:
                    continue
    except OSError:
        return None
    return None


def _cpu_pid(pid):
    if not pid:
        return None
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as f:
            campuri = f.read().rsplit(")", 1)[1].split()
        return (int(campuri[11]) + int(campuri[12])) / float(os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError, IndexError, AttributeError):
        return None


def _rss_mb(pid="self"):
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as f:
            for linie in f:
                if linie.startswith("VmRSS:"):
                    return int(linie.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


def _stare_pi():
    if os.name == "nt" or not shutil.which("vcgencmd"):
        return {}
    rez = {}
    for cheie, arg in (("throttled", ["get_throttled"]), ("ceas", ["measure_clock", "arm"]), ("temp", ["measure_temp"])):
        try:
            out = subprocess.check_output(["vcgencmd"] + arg, timeout=2, text=True).strip()
            rez[cheie] = out.split("=", 1)[1] if "=" in out else out
        except (OSError, subprocess.SubprocessError) as e:
            rez[cheie] = f"eroare({e})"
    return rez


class Masurare:
    def __init__(self, sim):
        self.sim = sim

    def start(self):
        self.pi0 = _stare_pi()
        self.rss0 = _rss_mb()
        self.xpid = _pid_dupa_nume("Xorg")
        if self.sim:
            self.sim.reseteaza()
        self.stat0, self.x0 = _proc_stat(), _cpu_pid(self.xpid)
        self.t0, self.tt0, self.pt0 = time.perf_counter(), time.thread_time(), time.process_time()

    def stop(self):
        dt = max(1e-6, time.perf_counter() - self.t0)
        rez = {"durata_s": round(dt, 2),
               "cpu_fir_ui_pct": round(100.0 * (time.thread_time() - self.tt0) / dt, 1),
               "cpu_proces_pct": round(100.0 * (time.process_time() - self.pt0) / dt, 1)}
        stat1, x1 = _proc_stat(), _cpu_pid(self.xpid)
        if self.stat0 and stat1 and stat1[1] > self.stat0[1]:
            nuclee = os.cpu_count() or 1
            rez["cpu_sistem_pct"] = round(100.0 * nuclee * (stat1[0] - self.stat0[0]) / (stat1[1] - self.stat0[1]), 1)
        if self.x0 is not None and x1 is not None:
            rez["cpu_xorg_pct"] = round(100.0 * (x1 - self.x0) / dt, 1)
        rss1 = _rss_mb()
        if rss1 is not None:
            rez["rss_mb"] = round(rss1, 1)
            rez["rss_delta_mb"] = round(rss1 - (self.rss0 or rss1), 1)
        if self.sim:
            st = self.sim.statistici()
            rez["wake"] = {
                "cicluri": len(st["dsp"]),
                "intarziere_ms": [round(1000 * _pct(st["intarzieri"], p), 1) for p in (50, 95, 100)],
                "dsp_ms": [round(1000 * _pct(st["dsp"], p), 1) for p in (50, 95, 100)],
                "restanta_max_ms": round(1000 * max(0.0, st["restanta_max"]), 1),
                "cpu_fir_pct": round(100.0 * st["cpu_s"] / dt, 1)}
        pi1 = _stare_pi()
        if pi1:
            rez["pi"] = {k: f"{self.pi0.get(k, '?')} -> {pi1.get(k, '?')}" for k in pi1}
        return rez


def _faza_la(t):
    return FAZA_FIXA if FAZA_FIXA is not None else int((t % 12.0) / 4.0)


def _durata_faza(durata, idx):
    if FAZA_FIXA is not None:
        return durata if FAZA_FIXA == idx else 0.0
    cicluri = int(durata // 12.0)
    rest = durata - cicluri * 12.0
    return cicluri * 4.0 + min(4.0, max(0.0, rest - 4.0 * idx))


def _fps_panou(fps_schimbari, randuri, latime, capacitate, fps_randat):
    """Estimare grosiera: panoul prinde un cadru din k, unde k acopera asteptarea fbtft plus transferul."""
    if not randuri or fps_randat <= 0:
        return 0.0
    t_transfer = _pct(randuri, 50) * latime * 2 / capacitate
    k = max(1, math.ceil((ASTEPTARE_FBTFT_S + t_transfer) * fps_randat))
    return round(fps_schimbari / k, 1)


def _rezumat_cadre(timpi_py, timpi_x, randuri, momente, cadre, sarite, durata, latime, spi_hz):
    schimbate = [r for r in randuri if r > 0]
    octeti_s = sum(r * latime * 2 for r in schimbate) / max(1e-6, durata)
    capacitate = spi_hz / 8.0 * EFICIENTA_SPI
    fps_randat = cadre / max(1e-6, durata)
    ocupare = octeti_s / capacitate
    fps_schimbari = len(schimbate) / max(1e-6, durata)
    faze = {}
    for idx, nume in enumerate(NUME_FAZE):
        d_faza = _durata_faza(durata, idx)
        r_faza = [r for r, t in zip(randuri, momente) if r > 0 and _faza_la(t) == idx]
        if d_faza <= 0:
            continue
        fps_f = len(r_faza) / d_faza
        ocup_f = sum(r * latime * 2 for r in r_faza) / d_faza / capacitate
        faze[nume] = {"fps_schimbari": round(fps_f, 1), "randuri_p95": int(_pct(r_faza, 95)),
                      "spi_ocupare_pct": round(100.0 * ocup_f, 0),
                      "fps_panou_estimat": _fps_panou(fps_f, r_faza, latime, capacitate, fps_randat)}
    return {
        "faze": faze,
        "fps_randat": round(fps_randat, 1),
        "cadre": cadre, "sarite": sarite,
        "cadru_py_ms": [round(1000 * _pct(timpi_py, p), 1) for p in (50, 95, 100)],
        "cadru_cu_x_ms": [round(1000 * _pct(timpi_x, p), 1) for p in (50, 95, 100)],
        "randuri_cadru": [int(_pct(schimbate, p)) for p in (50, 95, 100)],
        "spi_ocupare_pct": round(100.0 * ocupare, 0),
        "fps_schimbari": round(fps_schimbari, 1),
        "fps_panou_estimat": _fps_panou(fps_schimbari, schimbate, latime, capacitate, fps_randat)}


def _randuri(spans):
    if not spans:
        return 0
    return max(s[1] for s in spans) - min(s[0] for s in spans)


# --------------------------------------------------------------------------- variantele Tk

class RandareCanvas:
    def __init__(self, tk, parinte, geo, sprite):
        from PIL import ImageTk
        self.geo = geo
        self.c = tk.Canvas(parinte, width=geo.W, height=geo.H, bg=BG, highlightthickness=0, bd=0)
        self.c.place(x=0, y=0)
        self._img_fundal = ImageTk.PhotoImage(sprite["fundal_ochi"])
        self._img_pupila = ImageTk.PhotoImage(sprite["pupila"])
        self.c.create_image(0, 0, image=self._img_fundal, anchor="nw")
        self.pupile = [self.c.create_image(ex, geo.ey, image=self._img_pupila) for ex in geo.ochi_x]
        self.pleoape = [self.c.create_polygon(0, 0, 0, 0, 0, 0, 0, 0, fill=BG, outline="") for _ in geo.ochi_x]
        self.gura = self.c.create_polygon(0, 0, 0, 0, 0, 0, fill=ACCENT, outline="")
        self._chei = {}

    def aplica(self, st):
        geo, spans = self.geo, []
        for i in range(2):
            poz = geo.pozitie_pupila(i, st)
            vechi = self._chei.get(("p", i))
            if vechi != poz:
                self.c.coords(self.pupile[i], poz[0], poz[1])
                y_vechi = vechi[1] if vechi else poz[1]
                spans.append((min(poz[1], y_vechi) - geo.pr - 1, max(poz[1], y_vechi) + geo.pr + 1))
                self._chei[("p", i)] = poz
            pts = geo.poligon_pleoapa(i, st)
            if self._chei.get(("l", i)) != pts:
                self.c.coords(self.pleoape[i], *pts)
                spans.append(geo.randuri_ochi)
                self._chei[("l", i)] = pts
        pts = geo.poligon_gura(st)
        if self._chei.get("g") != pts:
            self.c.coords(self.gura, *pts)
            spans.append(geo.randuri_gura)
            self._chei["g"] = pts
        return spans


class RandarePillow:
    def __init__(self, tk, parinte, geo, sprite):
        from PIL import Image, ImageDraw, ImageTk
        self.Image, self.ImageDraw = Image, ImageDraw
        self.geo = geo
        self.pupila = sprite["pupila"]
        self._foto_fundal = ImageTk.PhotoImage(sprite["fundal_ochi"])
        tk.Label(parinte, image=self._foto_fundal, bd=0, highlightthickness=0, padx=0, pady=0).place(x=0, y=0)
        self.cutii, self.baze, self.sub_pleoape, self.foto = [], [], [], []
        for i in range(2):
            cutie = geo.dreptunghi_ochi(i)
            self.cutii.append(cutie)
            self.baze.append(sprite["fundal_ochi"].crop(cutie))
            self.sub_pleoape.append(sprite["fundal"].crop(cutie))
        self.cutie_gura = geo.dreptunghi_gura()
        self.baza_gura = sprite["fundal"].crop(self.cutie_gura)
        for cutie, baza in list(zip(self.cutii, self.baze)) + [(self.cutie_gura, self.baza_gura)]:
            foto = ImageTk.PhotoImage(baza)
            tk.Label(parinte, image=foto, bd=0, highlightthickness=0, padx=0, pady=0).place(x=cutie[0], y=cutie[1])
            self.foto.append(foto)
        self._chei = {}

    def _masca(self, cutie, pts, factor):
        lw, lh = cutie[2] - cutie[0], cutie[3] - cutie[1]
        m = self.Image.new("L", (lw * factor, lh * factor), 0)
        loc = [((pts[k] - cutie[0]) * factor, (pts[k + 1] - cutie[1]) * factor) for k in range(0, len(pts), 2)]
        self.ImageDraw.Draw(m).polygon(loc, fill=255)
        return m.resize((lw, lh), self.Image.Resampling.BILINEAR)

    def aplica(self, st):
        geo, spans = self.geo, []
        for i in range(2):
            poz, pts = geo.pozitie_pupila(i, st), geo.poligon_pleoapa(i, st)
            if self._chei.get(i) == (poz, pts):
                continue
            self._chei[i] = (poz, pts)
            cutie = self.cutii[i]
            im = self.baze[i].copy()
            im.paste(self.pupila, (poz[0] - cutie[0] - geo.dp // 2, poz[1] - cutie[1] - geo.dp // 2))
            if max(pts[5], pts[7]) > cutie[1]:
                im.paste(self.sub_pleoape[i], (0, 0), self._masca(cutie, pts, 2))
            self.foto[i].paste(im)
            spans.append(geo.randuri_ochi)
        pts = geo.poligon_gura(st)
        if self._chei.get("g") != pts:
            self._chei["g"] = pts
            im = self.baza_gura.copy()
            im.paste(ACC_RGB, (0, 0) + im.size, self._masca(self.cutie_gura, pts, 3))
            self.foto[2].paste(im)
            spans.append(geo.randuri_gura)
        return spans


class BuclaTk:
    def __init__(self, root, randare, durata, fps):
        self.root, self.randare, self.durata, self.pas = root, randare, durata, 1.0 / fps
        self.timpi_py, self.timpi_x, self.randuri, self.momente = [], [], [], []
        self.cadre = self.sarite = 0

    def ruleaza(self):
        self.t_start = time.perf_counter()
        self.urm = self.t_start
        self.root.after(1, self._cadru)
        self.root.mainloop()
        return time.perf_counter() - self.t_start

    def _cadru(self):
        t0 = time.perf_counter()
        if t0 - self.t_start >= self.durata:
            self.root.quit()
            return
        spans = self.randare.aplica(stare_fata(t0 - self.t_start))
        self.root.update_idletasks()
        t1 = time.perf_counter()
        self.root.winfo_pointerxy()  # dus-intors la serverul X: asteapta pana cand desenul e procesat
        t2 = time.perf_counter()
        self.timpi_py.append(t1 - t0)
        self.timpi_x.append(t2 - t0)
        self.randuri.append(_randuri(spans))
        self.momente.append(t0 - self.t_start)
        self.cadre += 1
        self.urm += self.pas
        rest = self.urm - time.perf_counter()
        if rest < 0:
            pierdute = int(-rest / self.pas) + 1
            self.sarite += pierdute
            self.urm += pierdute * self.pas
            rest = self.urm - time.perf_counter()
        self.root.after(max(1, int(rest * 1000)), self._cadru)


# --------------------------------------------------------------------------- varianta SDL (proces copil)

def copil_sdl(args):
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    if args.mod_sdl == "fereastra":
        os.environ.pop("SDL_WINDOWID", None)
        os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
    import pygame
    from pygame import gfxdraw
    pygame.display.init()  # doar video: fara mixer, ca sa nu atinga placa de sunet
    geo = Geometrie(args.latime, args.inaltime)
    ecran = pygame.display.set_mode((geo.W, geo.H), pygame.NOFRAME if args.mod_sdl == "fereastra" else 0)
    sprite = construieste_sprite(geo)

    def _suprafata(img):
        return pygame.image.frombuffer(img.tobytes(), img.size, "RGB").convert()

    fundal, fundal_ochi, pupila = (_suprafata(sprite[k]) for k in ("fundal", "fundal_ochi", "pupila"))
    cutii = [pygame.Rect(c[0], c[1], c[2] - c[0], c[3] - c[1]) for c in (geo.dreptunghi_ochi(0), geo.dreptunghi_ochi(1))]
    cg = geo.dreptunghi_gura()
    cutie_gura = pygame.Rect(cg[0], cg[1], cg[2] - cg[0], cg[3] - cg[1])
    ecran.blit(fundal_ochi, (0, 0))
    pygame.display.flip()

    chei, timpi, randuri, momente = {}, [], [], []
    cadre = sarite = 0
    pas = 1.0 / args.fps
    t_start = time.perf_counter()
    cpu0 = time.process_time()
    urm = t_start
    while True:
        t0 = time.perf_counter()
        if t0 - t_start >= args.durata:
            break
        pygame.event.pump()
        st = stare_fata(t0 - t_start)
        dreptunghiuri, spans = [], []
        for i in range(2):
            poz, pts = geo.pozitie_pupila(i, st), geo.poligon_pleoapa(i, st)
            if chei.get(i) == (poz, pts):
                continue
            chei[i] = (poz, pts)
            ecran.set_clip(cutii[i])
            ecran.blit(fundal_ochi, cutii[i].topleft, cutii[i])
            ecran.blit(pupila, (poz[0] - geo.dp // 2, poz[1] - geo.dp // 2))
            if max(pts[5], pts[7]) > cutii[i].top:
                puncte = [(pts[k], pts[k + 1]) for k in range(0, 8, 2)]
                gfxdraw.filled_polygon(ecran, puncte, BG_RGB)
                gfxdraw.aapolygon(ecran, puncte, BG_RGB)
            ecran.set_clip(None)
            dreptunghiuri.append(cutii[i])
            spans.append(geo.randuri_ochi)
        pts = geo.poligon_gura(st)
        if chei.get("g") != pts:
            chei["g"] = pts
            ecran.blit(fundal, cutie_gura.topleft, cutie_gura)
            puncte = [(pts[k], pts[k + 1]) for k in range(0, len(pts), 2)]
            gfxdraw.filled_polygon(ecran, puncte, ACC_RGB)
            gfxdraw.aapolygon(ecran, puncte, ACC_RGB)
            dreptunghiuri.append(cutie_gura)
            spans.append(geo.randuri_gura)
        if dreptunghiuri:
            pygame.display.update(dreptunghiuri)
        timpi.append(time.perf_counter() - t0)
        randuri.append(_randuri(spans))
        momente.append(t0 - t_start)
        cadre += 1
        urm += pas
        rest = urm - time.perf_counter()
        if rest < 0:
            pierdute = int(-rest / pas) + 1
            sarite += pierdute
            urm += pierdute * pas
            rest = urm - time.perf_counter()
        time.sleep(max(0.0, rest))

    durata = time.perf_counter() - t_start
    rez = _rezumat_cadre(timpi, timpi, randuri, momente, cadre, sarite, durata, geo.W, args.spi_hz)
    rez.update({"mod_sdl": args.mod_sdl, "driver_sdl": pygame.display.get_driver(), "pygame": pygame.version.ver,
                "cpu_copil_pct": round(100.0 * (time.process_time() - cpu0) / durata, 1)})
    rss = _rss_mb()
    if rss is not None:
        rez["rss_copil_mb"] = round(rss, 1)
    pygame.display.quit()
    print("JSON_COPIL " + json.dumps(rez))
    return 0


def ruleaza_sdl(tk, root, geo, args, masurare):
    cadru = tk.Frame(root, width=geo.W, height=geo.H, bg=BG)
    cadru.place(x=0, y=0)
    root.update()
    eroare = ""
    try:
        for mod in ("embed", "fereastra"):
            env = dict(os.environ)
            env["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
            if mod == "embed":
                env["SDL_WINDOWID"] = str(cadru.winfo_id())
            else:
                env.pop("SDL_WINDOWID", None)
            cmd = [sys.executable, os.path.abspath(__file__), "--copil-sdl", "--mod-sdl", mod,
                   "--durata", str(args.durata), "--fps", str(args.fps), "--latime", str(geo.W),
                   "--inaltime", str(geo.H), "--spi-hz", str(args.spi_hz), "--faza", args.faza]
            if args.compact:
                cmd.append("--compact")
            masurare.start()
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)

            def _verifica():
                if proc.poll() is None:
                    root.after(100, _verifica)
                else:
                    root.quit()

            root.after(100, _verifica)
            root.mainloop()
            out, err = proc.communicate()
            rez = masurare.stop()
            for linie in out.splitlines():
                if linie.startswith("JSON_COPIL "):
                    rez.update(json.loads(linie[len("JSON_COPIL "):]))
                    return rez
            eroare = f"mod={mod} cod={proc.returncode} {err.strip()[-300:]}"
            print(f"[BENCH]: varianta c nu a pornit ({eroare})", file=sys.stderr)
    finally:
        cadru.destroy()
    return {"eroare": eroare}


# --------------------------------------------------------------------------- orchestrare

DESCRIERI = {"z": "baza: fereastra statica, fara fata",
             "a": "Tk Canvas vectorial + sprite-uri opace",
             "b": "Pillow -> PhotoImage pe regiuni",
             "c": "pygame/SDL in proces separat"}


def _afiseaza(v, rez):
    print(f"\n== VARIANTA {v} ({DESCRIERI[v]})")
    if rez.get("eroare"):
        print(f"EROARE: {rez['eroare']}")
        return
    if "fps_randat" in rez:
        print(f"fps_randat={rez['fps_randat']} cadre={rez['cadre']} sarite={rez['sarite']}"
              + (f" mod_sdl={rez['mod_sdl']} driver={rez['driver_sdl']}" if "mod_sdl" in rez else ""))
        print(f"cadru_py_ms p50/p95/max={rez['cadru_py_ms']} | cadru_cu_X_ms p50/p95/max={rez['cadru_cu_x_ms']}")
        print(f"randuri_cadru p50/p95/max={rez['randuri_cadru']} | spi_ocupare={rez['spi_ocupare_pct']}% | "
              f"fps_schimbari={rez['fps_schimbari']} | fps_panou_estimat={rez['fps_panou_estimat']}")
        for nume, fz in rez.get("faze", {}).items():
            print(f"  faza {nume}: fps_schimbari={fz['fps_schimbari']} randuri_p95={fz['randuri_p95']} "
                  f"spi_ocupare={fz['spi_ocupare_pct']}% fps_panou_estimat={fz['fps_panou_estimat']}")
    cpu = [f"{k}={rez[k]}%" for k in ("cpu_fir_ui_pct", "cpu_proces_pct", "cpu_copil_pct", "cpu_sistem_pct", "cpu_xorg_pct")
           if k in rez]
    print(" ".join(cpu) + f" durata={rez.get('durata_s')}s")
    if "rss_mb" in rez:
        print(f"rss_mb={rez['rss_mb']} (delta {rez['rss_delta_mb']})"
              + (f" rss_copil_mb={rez['rss_copil_mb']}" if "rss_copil_mb" in rez else ""))
    w = rez.get("wake")
    if w:
        print(f"wake_sim: cicluri={w['cicluri']} intarziere_ms p50/p95/max={w['intarziere_ms']} "
              f"dsp_ms p50/p95/max={w['dsp_ms']} restanta_max_ms={w['restanta_max_ms']} cpu_fir={w['cpu_fir_pct']}%")
    if rez.get("pi"):
        print("pi: " + " | ".join(f"{k}={val}" for k, val in rez["pi"].items()))


def main():
    ap = argparse.ArgumentParser(description="Benchmark de randare pentru fata robotului")
    ap.add_argument("--variante", default="z,a,b,c")
    ap.add_argument("--durata", type=float, default=60.0)
    ap.add_argument("--durata-baza", type=float, default=20.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--latime", type=int, default=480)
    ap.add_argument("--inaltime", type=int, default=320)
    ap.add_argument("--spi-hz", type=int, default=20000000)
    ap.add_argument("--eticheta", default="")
    ap.add_argument("--fara-wake-sim", action="store_true")
    ap.add_argument("--faza", default="toate", choices=("toate",) + NUME_FAZE)
    ap.add_argument("--compact", action="store_true")
    ap.add_argument("--copil-sdl", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--mod-sdl", default="embed", help=argparse.SUPPRESS)
    args = ap.parse_args()
    global FAZA_FIXA, COMPACT
    FAZA_FIXA = NUME_FAZE.index(args.faza) if args.faza in NUME_FAZE else None
    COMPACT = args.compact
    if args.copil_sdl:
        return copil_sdl(args)

    import tkinter as tk
    import PIL
    root = tk.Tk()
    root.title("face_bench")
    root.configure(bg=BG)
    geo = Geometrie(args.latime, args.inaltime)
    if os.name != "nt":
        root.overrideredirect(True)
        root.configure(cursor="none")
    root.geometry(f"{geo.W}x{geo.H}+0+0")
    root.attributes("-topmost", True)
    root.lift()
    root.update()

    print("== FACE BENCH" + (f" [{args.eticheta}]" if args.eticheta else ""))
    print(f"python={sys.version.split()[0]} tk={root.tk.call('info', 'patchlevel')} PIL={PIL.__version__} "
          f"platforma={sys.platform} nuclee={os.cpu_count()}")
    print(f"ecran={root.winfo_screenwidth()}x{root.winfo_screenheight()} adancime={root.winfo_screendepth()} "
          f"fata={geo.W}x{geo.H} fps_tinta={args.fps} durata={args.durata}s spi={args.spi_hz / 1e6:.0f}MHz "
          f"faza={args.faza} compact={args.compact}")
    print(f"banda_fata: ochi randurile {geo.randuri_ochi}, gura randurile {geo.randuri_gura}")

    t_s = time.perf_counter()
    sprite = construieste_sprite(geo)
    print(f"sprite-uri construite in {1000 * (time.perf_counter() - t_s):.0f} ms")

    sim = None
    if not args.fara_wake_sim:
        sim = SimWake()
        sim.start()
    masurare = Masurare(sim)
    toate = {}
    for v in [x.strip() for x in args.variante.split(",") if x.strip() in DESCRIERI]:
        try:
            if v == "c":
                rez = ruleaza_sdl(tk, root, geo, args, masurare)
            else:
                cadru = tk.Frame(root, width=geo.W, height=geo.H, bg=BG)
                cadru.place(x=0, y=0)
                if v == "z":
                    foto = __import__("PIL.ImageTk", fromlist=["PhotoImage"]).PhotoImage(sprite["fundal_ochi"])
                    tk.Label(cadru, image=foto, bd=0, highlightthickness=0, padx=0, pady=0).place(x=0, y=0)
                    root.update()
                    masurare.start()
                    root.after(int(min(args.durata, args.durata_baza) * 1000), root.quit)
                    root.mainloop()
                    rez = masurare.stop()
                else:
                    randare = (RandareCanvas if v == "a" else RandarePillow)(tk, cadru, geo, sprite)
                    root.update()
                    bucla = BuclaTk(root, randare, args.durata, args.fps)
                    masurare.start()
                    durata = bucla.ruleaza()
                    rez = masurare.stop()
                    rez.update(_rezumat_cadre(bucla.timpi_py, bucla.timpi_x, bucla.randuri, bucla.momente,
                                              bucla.cadre, bucla.sarite, durata, geo.W, args.spi_hz))
                cadru.destroy()
                root.update()
        except Exception as e:
            rez = {"eroare": f"{type(e).__name__}: {e}"}
        toate[v] = rez
        _afiseaza(v, rez)
        sys.stdout.flush()

    if sim:
        sim.opreste()
    try:
        root.destroy()
    except tk.TclError as e:
        print(f"[BENCH]: {e}", file=sys.stderr)
    print("\nJSON " + json.dumps({"eticheta": args.eticheta, "rezultate": toate}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
