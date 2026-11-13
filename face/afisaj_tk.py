"""
Afisajul fetei pe un Canvas Tk. Fiecare componenta e un element-imagine; cand cheia ei se schimba,
imaginea vine din cache sau se randeaza o singura data cu Pillow. Se apeleaza doar din firul Tk.
"""
from collections import OrderedDict

from .parametri import FUNDAL, FUNDAL_RGB
from .randare import Geometrie, componente


class AfisajFataTk:
    def __init__(self, parinte, latime=480, inaltime=320, zoom=1, cache_max=None):
        import tkinter as tk
        from PIL import Image, ImageChops, ImageTk
        self._Image, self._ImageChops, self._ImageTk = Image, ImageChops, ImageTk
        self.geo = Geometrie(latime, inaltime)
        self.zoom = max(1, int(zoom))
        # Imaginile cresc cu patratul scarii, deci pe ecrane mari tinem mai putine in cache
        scara = self.geo.s * self.zoom
        self.cache_max = cache_max if cache_max else max(24, int(240 / max(1.0, scara * scara)))
        self.canvas = tk.Canvas(parinte, width=latime * self.zoom, height=inaltime * self.zoom,
                                bg=FUNDAL, highlightthickness=0, bd=0)
        self._cache = OrderedDict()
        self._afisat = {}
        self._chei = {}
        self._randuri = {}
        self._elemente = {}
        self.randari = 0
        for nume, cutie in self.geo.cutii().items():
            item = self.canvas.create_image(cutie[0] * self.zoom, cutie[1] * self.zoom, anchor="nw")
            self._elemente[nume] = (item, cutie)

    def _foto(self, cheie, fn):
        """(imagine Tk, deplasare x, deplasare y, inaltime) pentru cheia data, decupata la continut."""
        intrare = self._cache.get(cheie)
        if intrare is not None:
            self._cache.move_to_end(cheie)
            return intrare
        img = fn()
        # Pastram doar zona care difera de fundal: pe ecranul SPI costul creste cu randurile atinse
        cutie = self._ImageChops.difference(img, self._Image.new("RGB", img.size, FUNDAL_RGB)).getbbox()
        if cutie is None:
            intrare = ("", 0, 0, 0)
        else:
            img = img.crop(cutie)
            if self.zoom > 1:
                img = img.resize((img.width * self.zoom, img.height * self.zoom), self._Image.Resampling.NEAREST)
            intrare = (self._ImageTk.PhotoImage(img), cutie[0], cutie[1], cutie[3] - cutie[1])
        self.randari += 1
        self._cache[cheie] = intrare
        while len(self._cache) > self.cache_max:
            self._cache.popitem(last=False)
        return intrare

    def aplica(self, st):
        """Deseneaza starea. Intoarce intervalele de randuri modificate, pentru statistici."""
        modificate = []
        for nume, cheie, fn in componente(self.geo, st):
            if self._chei.get(nume) == cheie:
                continue
            item, cutie = self._elemente[nume]
            foto, dx, dy, inalt = self._foto(cheie, fn) if fn is not None else ("", 0, 0, 0)
            self.canvas.coords(item, (cutie[0] + dx) * self.zoom, (cutie[1] + dy) * self.zoom)
            self.canvas.itemconfig(item, image=foto)
            # Referinta tine imaginea in viata chiar daca iese din cache cat timp e pe ecran
            self._afisat[nume] = foto
            self._chei[nume] = cheie
            nou = (cutie[1] + dy, cutie[1] + dy + inalt)
            vechi = self._randuri.get(nume, nou)
            self._randuri[nume] = nou
            modificate.append((min(vechi[0], nou[0]), max(vechi[1], nou[1])))
        return modificate

    def goleste_cache(self):
        self._cache.clear()
