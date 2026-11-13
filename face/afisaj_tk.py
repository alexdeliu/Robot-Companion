"""
Afisajul fetei pe un Canvas Tk. Fiecare componenta e un element-imagine; cand cheia ei se schimba,
imaginea vine din cache sau se randeaza o singura data cu Pillow. Se apeleaza doar din firul Tk.
"""
from collections import OrderedDict

from .parametri import FUNDAL
from .randare import Geometrie, componente


class AfisajFataTk:
    def __init__(self, parinte, latime=480, inaltime=320, zoom=1, cache_max=None):
        import tkinter as tk
        from PIL import Image, ImageTk
        self._Image, self._ImageTk = Image, ImageTk
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
        self._elemente = {}
        self.randari = 0
        for nume, cutie in self.geo.cutii().items():
            item = self.canvas.create_image(cutie[0] * self.zoom, cutie[1] * self.zoom, anchor="nw")
            self._elemente[nume] = (item, cutie)

    def _foto(self, cheie, fn):
        foto = self._cache.get(cheie)
        if foto is not None:
            self._cache.move_to_end(cheie)
            return foto
        img = fn()
        if self.zoom > 1:
            img = img.resize((img.width * self.zoom, img.height * self.zoom), self._Image.Resampling.NEAREST)
        foto = self._ImageTk.PhotoImage(img)
        self.randari += 1
        self._cache[cheie] = foto
        while len(self._cache) > self.cache_max:
            self._cache.popitem(last=False)
        return foto

    def aplica(self, st):
        """Deseneaza starea. Intoarce intervalele de randuri modificate, pentru statistici."""
        modificate = []
        for nume, cheie, fn in componente(self.geo, st):
            if self._chei.get(nume) == cheie:
                continue
            item, cutie = self._elemente[nume]
            foto = self._foto(cheie, fn) if fn is not None else ""
            self.canvas.itemconfig(item, image=foto)
            # Referinta tine imaginea in viata chiar daca iese din cache cat timp e pe ecran
            self._afisat[nume] = foto
            self._chei[nume] = cheie
            modificate.append((cutie[1], cutie[3]))
        return modificate

    def goleste_cache(self):
        self._cache.clear()
