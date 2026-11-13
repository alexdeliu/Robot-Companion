"""
API de privire: unde se uita robotul. Sigur intre fire (camera, atingerea si motorul scriu din fire diferite).

Coordonate normalizate: x in [-1, 1] (stanga .. dreapta ecranului), y in [-1, 1] (sus .. jos).
Mai multe surse pot cere o privire; castiga cea cu prioritatea cea mai mare care nu a expirat.
"""
import threading
import time

PRIORITATI = {"idle": 0, "eveniment": 10, "atingere": 20, "camera": 30}


def _limiteaza(v, jos=-1.0, sus=1.0):
    return jos if v < jos else sus if v > sus else v


class ManagerPrivire:
    def __init__(self, ceas=time.monotonic, omega=38.0):
        self._ceas = ceas
        self._omega = omega
        self._lock = threading.Lock()
        self._surse = {}
        self._x = self._y = 0.0
        self._vx = self._vy = 0.0

    def seteaza(self, x, y, sursa="camera", prioritate=None, timeout_s=1.5):
        """Cere o privire. timeout_s=None inseamna ca ramane pana la urmatoarea cerere a aceleiasi surse."""
        prio = PRIORITATI.get(sursa, 5) if prioritate is None else prioritate
        expira = None if timeout_s is None else self._ceas() + float(timeout_s)
        with self._lock:
            self._surse[sursa] = (_limiteaza(float(x)), _limiteaza(float(y)), prio, expira)

    def elibereaza(self, sursa):
        with self._lock:
            self._surse.pop(sursa, None)

    def tinta(self, acum=None):
        """Intoarce (x, y, sursa) pentru sursa castigatoare; fara surse active, priveste in fata."""
        acum = self._ceas() if acum is None else acum
        with self._lock:
            for nume in [n for n, s in self._surse.items() if s[3] is not None and s[3] <= acum]:
                del self._surse[nume]
            if not self._surse:
                return 0.0, 0.0, None
            nume = max(self._surse, key=lambda n: self._surse[n][2])
            x, y, _prio, _exp = self._surse[nume]
            return x, y, nume

    def actualizeaza(self, acum, dt):
        """Netezeste privirea spre tinta curenta. Intoarce (x, y, in_miscare)."""
        tx, ty, _sursa = self.tinta(acum)
        if abs(tx - self._x) < 0.004 and abs(ty - self._y) < 0.004 and abs(self._vx) < 0.05 and abs(self._vy) < 0.05:
            self._x, self._y, self._vx, self._vy = tx, ty, 0.0, 0.0
            return tx, ty, False
        pasi = max(1, int(dt / 0.008 + 0.999))
        h = dt / pasi
        w = self._omega
        for _ in range(pasi):
            self._vx += (w * w * (tx - self._x) - 2.0 * w * self._vx) * h
            self._x += self._vx * h
            self._vy += (w * w * (ty - self._y) - 2.0 * w * self._vy) * h
            self._y += self._vy * h
        return self._x, self._y, True
