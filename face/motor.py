"""
Motorul fetei: compune expresia de baza, reactiile, clipitul, privirea, vorbirea si somnul intr-o stare
pe care o deseneaza afisajul. Logica pura: fara Tk, fara Pillow, cu ceas si generator aleator injectabile.

Motorul se foloseste dintr-un singur fir (firul fetei). Doar ManagerPrivire este sigur intre fire.
"""
import logging
import math
import random
import time

from .parametri import EXPRESII, LATURI
from .privire import ManagerPrivire

logger = logging.getLogger("RobotCompanion")

CLIPIT_INCHIDE, CLIPIT_TINE, CLIPIT_DESCHIDE = 0.07, 0.04, 0.13
CLIPIT_TOTAL = CLIPIT_INCHIDE + CLIPIT_TINE + CLIPIT_DESCHIDE
PLEOAPA_JOS_LA_CLIPIT = 0.30
OMEGA_BAZA = 13.0
AMORTIZARE = 0.78
REACTII_ATINGERE = {"tap": ("surprins", 0.7), "mangaiere": ("afectuos", 3.0), "apasare_lunga": ("afectuos", 2.5)}


def _limiteaza(v, jos=0.0, sus=1.0):
    return jos if v < jos else sus if v > sus else v


class MotorFata:
    def __init__(self, ceas=time.monotonic, rng=None, fps_activ=30, fps_idle=2,
                 adormire_dupa_sec=300.0, respiratie=0.10):
        self._ceas = ceas
        self._rng = rng or random.Random()
        self.fps_activ = max(5, int(fps_activ))
        self.fps_idle = max(0.2, float(fps_idle))
        self.adormire_dupa_sec = float(adormire_dupa_sec)
        self.respiratie = float(respiratie)
        self.privire = ManagerPrivire(ceas)

        acum = ceas()
        self._baza = "neutru"
        self._reactie = None          # (nume, moment_expirare)
        self._stadiu_somn = 0         # 0 treaz, 1 plictisit, 2 somnoros, 3 adormit
        self._nume_tinta = "neutru"
        self._tinta = EXPRESII["neutru"]
        self._val = dict(self._tinta)
        self._vit = dict.fromkeys(self._tinta, 0.0)
        self._omega = OMEGA_BAZA

        self._vorbire = False
        self._nivel_gura = 0.0
        self._gura_afisata = 0.0

        self._clipit_t0 = None
        self._urm_clipit = acum + self._rng.uniform(1.5, 4.0)
        self._urm_sacada = acum + self._rng.uniform(0.8, 2.5)
        self._ultima_activitate = acum
        self._t_ultim = None
        self._oprit = False
        self.in_miscare = True

    # ------------------------------------------------------------------ comenzi

    @property
    def expresie_curenta(self):
        return self._nume_tinta

    @property
    def stadiu_somn(self):
        return self._stadiu_somn

    def seteaza_expresie(self, nume, viteza=1.0):
        """Schimba expresia de baza (cea la care fata revine dupa reactii)."""
        if nume not in EXPRESII:
            logger.warning(f"[FACE]: Expresie necunoscuta '{nume}', folosesc 'neutru'.")
            nume = "neutru"
        self._baza = nume
        if nume != "neutru":
            self.activitate()
        self._recalculeaza_tinta(viteza)

    def reactie(self, nume, durata=1.2, viteza=1.5):
        """Expresie temporara peste cea de baza."""
        if nume not in EXPRESII:
            logger.warning(f"[FACE]: Reactie necunoscuta '{nume}', o ignor.")
            return
        self.activitate()
        self._reactie = (nume, self._ceas() + float(durata))
        self._recalculeaza_tinta(viteza)

    def atinge(self, tip="tap"):
        nume, durata = REACTII_ATINGERE.get(tip, REACTII_ATINGERE["tap"])
        self.reactie(nume, durata)

    def seteaza_vorbire(self, activ):
        """Porneste sau opreste stratul de vorbire. La oprire gura se inchide imediat (barge-in)."""
        self._vorbire = bool(activ)
        if self._vorbire:
            self.activitate()
        else:
            self._nivel_gura = 0.0
            self._gura_afisata = 0.0
        self.in_miscare = True

    def seteaza_nivel_gura(self, nivel):
        self._nivel_gura = _limiteaza(float(nivel))

    def activitate(self):
        """Orice eveniment care arata ca robotul e folosit: amana somnul si il trezeste daca dormea."""
        self._ultima_activitate = self._ceas()
        if self._stadiu_somn:
            dormea = self._stadiu_somn >= 2
            self._stadiu_somn = 0
            if dormea:
                self._reactie = ("surprins", self._ceas() + 0.55)
                self._recalculeaza_tinta(2.2)
            else:
                self._recalculeaza_tinta(1.5)

    def adoarme(self):
        self._reactie = None
        self._stadiu_somn = 3
        self._recalculeaza_tinta(0.5)

    def opreste(self):
        """Oprire completa (de exemplu la VIDEO): tick() nu mai produce nimic."""
        self._oprit = True

    def porneste(self):
        self._oprit = False
        self._t_ultim = None
        self._ultima_activitate = self._ceas()
        self.in_miscare = True

    @property
    def oprit(self):
        return self._oprit

    # ------------------------------------------------------------------ logica interna

    def _recalculeaza_tinta(self, viteza=1.0):
        if self._reactie:
            nume = self._reactie[0]
        elif self._stadiu_somn:
            nume = ("plictisit", "somnoros", "adormit")[self._stadiu_somn - 1]
        else:
            nume = self._baza
        self._nume_tinta = nume
        self._tinta = EXPRESII[nume]
        self._omega = OMEGA_BAZA * max(0.2, float(viteza))
        self.in_miscare = True

    def _praguri_somn(self):
        t = self.adormire_dupa_sec
        return (0.6 * t, t, t + 8.0)

    def _actualizeaza_stadii(self, acum):
        if self._reactie and acum >= self._reactie[1]:
            self._reactie = None
            self._recalculeaza_tinta(1.0)
        if self.adormire_dupa_sec <= 0 or self._stadiu_somn >= 3:
            return
        if self._baza != "neutru" or self._reactie or self._vorbire:
            self._ultima_activitate = acum
            return
        inactiv = acum - self._ultima_activitate
        stadiu = sum(1 for prag in self._praguri_somn() if inactiv >= prag)
        if stadiu > self._stadiu_somn:
            self._stadiu_somn = stadiu
            self._recalculeaza_tinta(0.45)

    def _pas_resorturi(self, dt):
        miscare = False
        pasi = max(1, int(dt / 0.008 + 0.999))
        h = dt / pasi
        w, z = self._omega, AMORTIZARE
        val, vit = self._val, self._vit
        for cheie, tinta in self._tinta.items():
            x, v = val[cheie], vit[cheie]
            prag = 0.5 if cheie in ("r", "g", "b") else 0.002
            if abs(x - tinta) < prag and abs(v) < prag * 8:
                if x != tinta:
                    val[cheie], vit[cheie] = tinta, 0.0
                continue
            for _ in range(pasi):
                v += (w * w * (tinta - x) - 2.0 * z * w * v) * h
                x += v * h
            val[cheie], vit[cheie] = x, v
            miscare = True
        return miscare

    def _nivel_clipit(self, acum):
        if self._clipit_t0 is None:
            inchis = sum(self._val[f"sus_{l}"] + self._val[f"jos_{l}"] for l in LATURI) / 2.0
            if acum >= self._urm_clipit:
                if self._stadiu_somn >= 3 or inchis > 0.75:
                    self._urm_clipit = acum + self._rng.uniform(2.0, 5.0)
                    return 0.0
                self._clipit_t0 = acum
            else:
                return 0.0
        e = acum - self._clipit_t0
        if e >= CLIPIT_TOTAL:
            self._clipit_t0 = None
            dublu = self._rng.random() < 0.18
            self._urm_clipit = acum + (0.11 if dublu else self._rng.uniform(2.6, 6.5))
            return 0.0
        if e < CLIPIT_INCHIDE:
            a = e / CLIPIT_INCHIDE
            return a * a * (3.0 - 2.0 * a)
        if e < CLIPIT_INCHIDE + CLIPIT_TINE:
            return 1.0
        a = 1.0 - (e - CLIPIT_INCHIDE - CLIPIT_TINE) / CLIPIT_DESCHIDE
        return a * a * (3.0 - 2.0 * a)

    def _privire_idle(self, acum):
        if acum < self._urm_sacada:
            return
        if self._stadiu_somn >= 2:
            self.privire.seteaza(0.0, 0.0, sursa="idle", timeout_s=None)
            self._urm_sacada = acum + 3.0
            return
        if self._rng.random() < 0.5:
            x, y = self._rng.uniform(-0.15, 0.15), self._rng.uniform(-0.1, 0.1)
        else:
            x, y = self._rng.uniform(-0.75, 0.75), self._rng.uniform(-0.5, 0.5)
        self.privire.seteaza(x, y, sursa="idle", timeout_s=None)
        self._urm_sacada = acum + self._rng.uniform(1.2, 4.0)

    # ------------------------------------------------------------------ cadru

    def tick(self, acum=None):
        """Avanseaza animatia si intoarce starea de desenat, sau None daca fata e oprita."""
        if self._oprit:
            return None
        acum = self._ceas() if acum is None else acum
        dt = 0.0 if self._t_ultim is None else _limiteaza(acum - self._t_ultim, 0.0, 0.1)
        self._t_ultim = acum

        self._actualizeaza_stadii(acum)
        miscare = self._pas_resorturi(dt)
        clipit = self._nivel_clipit(acum)
        self._privire_idle(acum)
        gx, gy, misca_privirea = self.privire.actualizeaza(acum, dt)

        st = dict(self._val)
        if clipit > 0.0:
            for latura in LATURI:
                jos = st[f"jos_{latura}"]
                jos_e = jos + max(0.0, PLEOAPA_JOS_LA_CLIPIT - jos) * clipit
                sus = st[f"sus_{latura}"]
                st[f"jos_{latura}"] = jos_e
                st[f"sus_{latura}"] = sus + max(0.0, 1.0 - jos_e - sus) * clipit

        amplitudine = 0.35 if self._vorbire else 1.0
        st["px"] = _limiteaza(st["px"] + gx * amplitudine, -1.0, 1.0)
        st["py"] = _limiteaza(st["py"] + gy * amplitudine, -1.0, 1.0)

        gura_in_miscare = False
        if self._vorbire or self._gura_afisata > 0.0:
            anterior = self._gura_afisata
            self._gura_afisata = max(self._nivel_gura, anterior - dt * 9.0) if self._vorbire else 0.0
            gura_in_miscare = self._vorbire or self._gura_afisata != anterior
            n = self._gura_afisata
            st["g_desch"] = max(st["g_desch"], n)
            st["g_rot"] = _limiteaza(st["g_rot"] + 0.35 * n)
            st["g_curb"] *= 1.0 - 0.55 * n
            st["g_lat"] *= 1.0 - 0.15 * n

        if self.respiratie > 0.0:
            adanc = 2.2 if self._stadiu_somn >= 3 else 1.0
            st["glow"] *= 1.0 + self.respiratie * adanc * math.sin(2.0 * math.pi * acum / 4.6)

        self.in_miscare = miscare or clipit > 0.0 or misca_privirea or gura_in_miscare
        return st

    def interval_urmator(self, acum=None):
        """Cate secunde poate astepta gazda pana la urmatorul tick (FPS adaptiv)."""
        if self.in_miscare:
            return 1.0 / self.fps_activ
        acum = self._ceas() if acum is None else acum
        asteptari = [1.0 / self.fps_idle if self.respiratie > 0.0 else 2.0,
                     self._urm_clipit - acum, self._urm_sacada - acum]
        if self._reactie:
            asteptari.append(self._reactie[1] - acum)
        if self._stadiu_somn >= 3:
            asteptari = [1.0]
        return _limiteaza(min(asteptari), 1.0 / self.fps_activ, 2.0)
