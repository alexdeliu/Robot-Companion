"""
Miscarea gurii dupa vocea redata efectiv.

Vocea robotului e un fisier MP3 sintetizat complet inainte de redare (voice/speak.py). Aici il decodam
in paralel cu redarea, in ferestre de 20 ms, si scoatem pentru fiecare fereastra:
  - taria (RMS)      -> cat de deschisa e gura
  - stralucirea      -> forma gurii: sunete inchise (o, u, a) = gura rotunda, sunete ascutite (i, e, s) = lata
Gura citeste apoi fereastra corespunzatoare timpului scurs de la pornirea redarii.

Sigur intre fire: pregateste()/porneste()/opreste() vin din firul vocii, citeste() din firul fetei.
Nu atinge Tk si nu intarzie vocea: decodarea ruleaza in firul ei, cu prioritate mica.
"""
import logging
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import warnings
from array import array

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    try:
        import audioop   # exista pana la Python 3.12; mai jos e si varianta fara el
    except ImportError:
        audioop = None

logger = logging.getLogger("RobotCompanion")

FEREASTRA_S = 0.02
RATA = 16000
OCTETI_FEREASTRA = int(RATA * FEREASTRA_S) * 2
REF_MINIM = 400.0
# Cat trece, estimativ, de la notificarea "redare pornita" pana cand sunetul se aude, minus intarzierea
# ecranului. Se regleaza din face.lipsync_offset_ms dupa testul pe robot.
OFFSET_IMPLICIT_MS = 40 if os.name == "nt" else 120


def analizeaza_fereastra(fragment):
    """(tarie RMS, stralucire) pentru un fragment PCM 16 biti mono; stralucirea e raportul dintre
    energia diferentelor dintre esantioane vecine si energia semnalului."""
    if len(fragment) < 4:
        return 0.0, 0.0
    if audioop is not None:
        rms = audioop.rms(fragment, 2)
        if rms <= 0:
            return 0.0, 0.0
        dif = audioop.add(fragment[2:], audioop.mul(fragment[:-2], 2, -1.0), 2)
        return float(rms), audioop.rms(dif, 2) / float(rms)
    es = array("h")
    es.frombytes(fragment[:len(fragment) // 2 * 2])
    if sys.byteorder == "big":
        es.byteswap()
    n = len(es)
    rms = math.sqrt(sum(x * x for x in es) / n)
    if rms <= 0:
        return 0.0, 0.0
    dif = math.sqrt(sum((es[i] - es[i - 1]) ** 2 for i in range(1, n)) / (n - 1))
    return rms, dif / rms


def nivel_simulat(t):
    """Anvelopa artificiala, cu silabe si pauze: pentru modul de dezvoltare si ca rezerva fara date audio."""
    silaba = abs(math.sin(2 * math.pi * 3.3 * t))
    fraza = 0.55 + 0.45 * math.sin(2 * math.pi * 0.6 * t)
    pauza = 0.0 if (t % 2.6) > 2.2 else 1.0
    return max(0.0, silaba * fraza * pauza)


def estimeaza_decalaj(referinta, masurat, pas_s=0.01, max_s=1.2):
    """Cu cat e intarziat sirul masurat fata de referinta (doua anvelope esantionate la pas_s).

    Intoarce (decalaj in secunde, scor 0..1); scorul e corelatia la decalajul gasit.
    Folosit la calibrare: referinta = anvelopa fisierului audio, masurat = ce a auzit microfonul.
    """
    def normalizeaza(v):
        if not v:
            return []
        medie = sum(v) / len(v)
        abatere = math.sqrt(sum((x - medie) ** 2 for x in v) / len(v)) or 1.0
        return [(x - medie) / abatere for x in v]

    ref, mas = normalizeaza(list(referinta)), normalizeaza(list(masurat))
    if len(ref) < 10 or len(mas) < 10:
        return 0.0, 0.0
    scoruri = []
    for k in range(int(max_s / pas_s) + 1):
        n = min(len(ref), len(mas) - k)
        if n < 10:
            break
        scoruri.append(sum(ref[j] * mas[j + k] for j in range(n)) / n)
    if not scoruri:
        return 0.0, 0.0
    k = max(range(len(scoruri)), key=scoruri.__getitem__)
    fin = float(k)
    if 0 < k < len(scoruri) - 1:
        a, b, c = scoruri[k - 1], scoruri[k], scoruri[k + 1]
        numitor = a - 2 * b + c
        if numitor < 0:
            fin = k + 0.5 * (a - c) / numitor
    return fin * pas_s, max(0.0, min(1.0, scoruri[k]))


def _la_mono_16k(raw, frecventa, canale):
    """Aduce PCM 16 biti la mono 16 kHz (pentru decodarea prin pygame, pe PC)."""
    if audioop is not None:
        if canale == 2:
            raw = audioop.tomono(raw, 2, 0.5, 0.5)
        if frecventa != RATA:
            raw, _stare = audioop.ratecv(raw, 2, 1, frecventa, RATA, None)
        return raw
    es = array("h")
    es.frombytes(raw[:len(raw) // 2 * 2])
    if sys.byteorder == "big":
        es.byteswap()
    mono = es[::max(1, canale)]
    pas = frecventa / float(RATA)
    iesire = array("h", (mono[int(i * pas)] for i in range(int(len(mono) / pas))))
    if sys.byteorder == "big":
        iesire.byteswap()
    return iesire.tobytes()


class LipSync:
    def __init__(self, offset_ms=None):
        self.offset_s = (OFFSET_IMPLICIT_MS if offset_ms is None else float(offset_ms)) / 1000.0
        self._lock = threading.Lock()
        self._gen = 0            # creste la fiecare replica noua sau oprire: firele vechi se opresc singure
        self._rms = []
        self._stral = []
        self._ref = REF_MINIM
        self._gata = False
        self._t0 = None
        self._activ = False
        self._cale = None
        self._decodare_pornita = False
        self.fara_date = False   # devine True daca vocea a pornit si decodarea nu a dat nimic
        self._mpg123 = shutil.which("mpg123") if os.name != "nt" else None
        self._nice = shutil.which("nice") if self._mpg123 else None

    # ------------------------------------------------------------------ din firul vocii

    def pregateste(self, cale):
        """Fisierul audio e gata si urmeaza sa fie redat."""
        with self._lock:
            self._gen += 1
            gen = self._gen
            self._rms, self._stral = [], []
            self._ref, self._gata = REF_MINIM, False
            self._t0, self._activ = None, False
            self._cale = cale
            self._decodare_pornita = bool(self._mpg123 and cale)
        if self._mpg123 and cale:
            threading.Thread(target=self._decodeaza_mpg123, args=(cale, gen), name="FaceLipSync", daemon=True).start()

    def porneste(self, t=None):
        """Redarea a pornit la momentul t (time.monotonic)."""
        with self._lock:
            self._t0 = time.monotonic() if t is None else float(t)
            self._activ = True
            porneste_decodare = bool(self._cale) and not self._decodare_pornita
            if porneste_decodare:
                self._decodare_pornita = True
            cale, gen = self._cale, self._gen
        if porneste_decodare:
            threading.Thread(target=self._decodeaza_pygame, args=(cale, gen), name="FaceLipSync", daemon=True).start()

    def opreste(self):
        """Redarea s-a terminat sau a fost intrerupta: gura se inchide la urmatoarea citire."""
        with self._lock:
            self._gen += 1
            self._activ = False
            self._t0 = None
            self._cale = None

    # ------------------------------------------------------------------ din firul fetei

    @property
    def activ(self):
        return self._activ

    @property
    def durata_s(self):
        return len(self._rms) * FEREASTRA_S

    def citeste(self, acum=None):
        """(vorbeste, deschidere 0..1, forma 0..1) pentru momentul dat; forma 0 = rotunda, 1 = lata."""
        with self._lock:
            if not self._activ or self._t0 is None:
                return False, 0.0, 0.5
            t = (time.monotonic() if acum is None else acum) - self._t0 - self.offset_s
            rms, stral, ref = self._rms, self._stral, self._ref
            n = len(rms)
            gata = self._gata
        i = int(math.floor(t / FEREASTRA_S))
        if n == 0 and not gata and t > 0.6:
            # Decodarea nu a produs nimic: gura se misca dupa o anvelopa artificiala, ca sa nu stea inchisa
            self.fara_date = True
            return True, nivel_simulat(t), 0.5
        if i < 0 or i >= n:
            return True, 0.0, 0.5
        a, b = max(0, i - 1), min(n - 1, i + 1)
        tarie = 0.25 * rms[a] + 0.5 * rms[i] + 0.25 * rms[b]
        liniste = max(60.0, ref * 0.04)
        nivel = (tarie - liniste) / max(1.0, ref - liniste)
        nivel = 0.0 if nivel <= 0.0 else min(1.0, nivel) ** 0.9
        a, b = max(0, i - 2), min(n, i + 3)
        luciu = sum(stral[a:b]) / (b - a)
        # Masurat pe vocea ro-RO-EmilNeural: vocalele stau intre 0.1 si 0.5, consoanele suieratoare peste 0.8
        return True, nivel, min(1.0, max(0.0, (luciu - 0.10) / 0.45))

    # ------------------------------------------------------------------ decodare

    def _adauga(self, ferestre, gen, gata=False):
        with self._lock:
            if gen != self._gen:
                return False
            for tarie, luciu in ferestre:
                self._rms.append(tarie)
                self._stral.append(luciu)
            if self._rms:
                if gata:
                    # Referinta = varful obisnuit al vocii (percentila 97): gura ajunge rar la maximum
                    ordonat = sorted(r for r in self._rms if r > 80.0) or [REF_MINIM]
                    self._ref = max(REF_MINIM, ordonat[int(0.97 * (len(ordonat) - 1))])
                else:
                    self._ref = max(REF_MINIM, 0.87 * max(self._rms))
            self._gata = self._gata or gata
            return True

    @staticmethod
    def _ferestre(date):
        n = len(date) // OCTETI_FEREASTRA
        return [analizeaza_fereastra(date[k * OCTETI_FEREASTRA:(k + 1) * OCTETI_FEREASTRA]) for k in range(n)], \
            date[n * OCTETI_FEREASTRA:]

    def _decodeaza_mpg123(self, cale, gen):
        proc = None
        try:
            cmd = [self._mpg123, "-q", "-s", "-e", "s16", "-r", str(RATA), "--mono", cale]
            if self._nice:
                cmd = [self._nice, "-n", "10"] + cmd
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            rest = b""
            while True:
                date = proc.stdout.read(OCTETI_FEREASTRA * 25)
                if not date:
                    break
                ferestre, rest = self._ferestre(rest + date)
                if not self._adauga(ferestre, gen):
                    return
            self._adauga([], gen, gata=True)
        except Exception as e:
            logger.debug(f"[FACE LIPSYNC MPG123]: {e}")
        finally:
            if proc is not None:
                try:
                    if proc.poll() is None:
                        proc.kill()
                    proc.stdout.close()
                    proc.wait(timeout=1)
                except Exception as e:
                    logger.debug(f"[FACE LIPSYNC STOP]: {e}")

    def _decodeaza_pygame(self, cale, gen):
        try:
            import pygame
            init = pygame.mixer.get_init()
            if not init:
                return
            frecventa, format_bits, canale = init
            if abs(format_bits) != 16:
                return
            raw = _la_mono_16k(pygame.mixer.Sound(cale).get_raw(), frecventa, canale)
            ferestre, _rest = self._ferestre(raw)
            self._adauga(ferestre, gen, gata=True)
        except Exception as e:
            logger.debug(f"[FACE LIPSYNC PYGAME]: {e}")

    def incarca_pcm(self, raw_mono_16k):
        """Pentru teste: incarca direct PCM 16 biti mono 16 kHz, ca si cum ar fi fost decodat."""
        with self._lock:
            self._gen += 1
            gen = self._gen
            self._rms, self._stral, self._gata = [], [], False
        ferestre, _rest = self._ferestre(raw_mono_16k)
        self._adauga(ferestre, gen, gata=True)
