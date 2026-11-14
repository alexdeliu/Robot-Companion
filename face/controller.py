"""
Controllerul fetei: leaga motorul si afisajul de interfata robotului (RobotCompanionUI din main.py).

Trei moduri de ecran:
  "fata"       fata pe tot ecranul (implicit)
  "controale"  fata + bara de sus si bara de jos, dupa o atingere; dispar singure
  "chat"       interfata clasica (chat, overlay-uri, tastatura); fata e retrasa si apare mica in bara de sus

Evenimentele vin prin eveniment(nume, **date), care e sigur intre fire: pune in coada, iar coada se
goleste pe firul Tk. Tot ce atinge Tk ruleaza doar pe firul Tk. Orice eroare opreste doar fata.
"""
import logging
import queue
import random
import threading
import time

from .afisaj_tk import AfisajFataTk
from .lipsync import LipSync
from .motor import MotorFata
from .parametri import EXPRESII
from .randare import Geometrie, compune_cadru

logger = logging.getLogger("RobotCompanion")

# actiune -> (expresia cat vorbeste, reactia de dupa ce termina)
EMOTII_ACTIUNE = {
    "vorbeste_normal": ("neutru", None),
    "spune_gluma": ("ironic", "ras"),
    "arata_vreme": ("curios", None),
    "cauta_wikipedia": ("curios", None),
    "continua_wikipedia": ("curios", None),
    "reda_youtube": ("fericit", None),
    "selecteaza_youtube": ("fericit", None),
    "reda_muzica": ("fericit", None),
    "opreste_media": ("neutru", None),
    "arata_status": ("mandru", None),
    "eroare": ("offline", None),
}
EXPRESII_STARE = {"LISTENING": "atent", "THINKING": "ganditor", "MUSIC": "muzica"}
CULOARE_TEXT, CULOARE_STINS = "#8B93A1", "#4B5263"


class ControllerFata:
    def __init__(self, ui, cfg=None):
        self.ui = ui
        self.root = ui.root
        self.cfg = dict(cfg or {})
        self._fir_ui = threading.get_ident()
        self._coada = queue.SimpleQueue()
        self._inchis = False
        self._rng = random.Random()

        latime, inaltime = int(ui.screen_width), int(ui.screen_height)
        # Pe ecrane mari (PC) randam la o marime rezonabila si marim imaginea, ca sa ramana rapid
        zoom = max(1, min(latime // 960, inaltime // 640))
        self.afisaj = AfisajFataTk(self.root, latime // zoom, inaltime // zoom, zoom=zoom)
        self.canvas = self.afisaj.canvas
        self.canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        self._k = self.afisaj.geo.s * zoom
        self._lat, self._inalt = latime, inaltime

        self.motor = MotorFata(
            fps_activ=self.cfg.get("fps_activ", 30), fps_idle=self.cfg.get("fps_idle", 1),
            adormire_dupa_sec=self.cfg.get("adormire_dupa_sec", 300))
        self.lipsync = LipSync(self.cfg.get("lipsync_offset_ms"))
        self._voce_activa = False
        self._avertizat_lipsync = False
        self._inghetat = False   # cat microfonul inregistreaza, fata sta nemiscata si nu foloseste procesorul

        self.mod = "fata"
        self._chat_fortat = False
        self._stare = "IDLE"
        self._dnd = bool(getattr(ui, "dnd_activ", False))
        self._obosit = False
        self._emotie_replica = None
        self._reactie_finala = None
        self._buffer_stream = ""
        self._t_sub = 0.0
        self._t_wake = 0.0
        self._t_comutare = 0.0
        self._t_apasare = 0.0
        self._xy_apasare = (0, 0)
        self._drum = 0
        self._mangaiat = False
        self._id_bucla = self._id_auto = self._id_sub = self._id_verif = None
        self._mini_cache = {}
        self._mini_curent = None
        self._ticks = self._desene = 0
        self._t_stat = time.monotonic()

        k = self._k
        f_mic, f_sub = max(7, int(round(9 * k))), max(8, int(round(11 * k)))
        self._punct = self.canvas.create_oval(10 * k, 10 * k, 18 * k, 18 * k, fill=CULOARE_STINS, outline="")
        self._txt_ceas = self.canvas.create_text(latime - 10 * k, 14 * k, text="", anchor="e",
                                                 font=("Arial", f_mic, "bold"), fill=CULOARE_STINS)
        self._txt_sub = self.canvas.create_text(latime / 2, inaltime - 8 * k, text="", anchor="s", justify="center",
                                                width=latime - 24 * k, font=("Arial", f_sub), fill=CULOARE_TEXT)
        self._txt_debug = None
        if self.cfg.get("debug_overlay", False):
            self._txt_debug = self.canvas.create_text(latime / 2, 14 * k, text="", anchor="center",
                                                      font=("Arial", f_mic), fill=CULOARE_STINS)

        self.canvas.bind("<ButtonPress-1>", self._apasa)
        self.canvas.bind("<B1-Motion>", self._trage)
        self.canvas.bind("<ButtonRelease-1>", self._elibereaza)
        self.root.bind_all("<ButtonPress>", self._la_orice_atingere, add="+")
        self.root.bind_all("<KeyPress>", self._la_tasta, add="+")
        for cadru in (ui.frame_overlay, ui.frame_kb):
            cadru.bind("<Map>", self._la_suprapunere, add="+")
            cadru.bind("<Unmap>", self._la_suprapunere, add="+")

        if self._dnd:
            self.motor.adoarme()
        self._actualizeaza_indicatori()
        self.arata_fata()
        logger.info(f"[FACE]: Fata pornita ({latime}x{inaltime}, zoom {zoom}, {self.motor.fps_activ} fps activ).")

    # ------------------------------------------------------------------ intrare evenimente

    def eveniment(self, nume, **date):
        """Sigur din orice fir. Pe firul Tk se aplica imediat, altfel la urmatorul tick."""
        if self._inchis:
            return
        self._coada.put((nume, date))
        if threading.get_ident() == self._fir_ui:
            self._goleste_coada()
            self._programeaza_acum()

    def la_redare(self, eveniment, **date):
        """Momentele redarii vocii, din firul vocii (voice/speak.py). Sigur intre fire, fara Tk."""
        if self._inchis or not self.cfg.get("lipsync", True):
            return
        if eveniment == "pregatit":
            self.lipsync.pregateste(date.get("cale"))
        elif eveniment == "pornit":
            self.lipsync.porneste(date.get("t"), date.get("viteza", 1.0))
        elif eveniment == "oprit":
            self.lipsync.opreste()

    def _sincronizeaza_voce(self):
        """Duce nivelul vocii la gura; la oprire (sau barge-in) gura se inchide in acelasi cadru."""
        activ, nivel, forma = self.lipsync.citeste()
        if activ != self._voce_activa:
            self._voce_activa = activ
            self.motor.seteaza_vorbire(activ)
        if activ:
            self.motor.seteaza_nivel_gura(nivel, forma)
            if self.lipsync.fara_date and not self._avertizat_lipsync:
                self._avertizat_lipsync = True
                logger.warning("[FACE]: Nu am putut citi sunetul vocii; gura se misca aproximativ, nu dupa voce.")

    def _goleste_coada(self):
        while True:
            try:
                nume, date = self._coada.get_nowait()
            except queue.Empty:
                return
            tratare = getattr(self, "_ev_" + nume, None)
            if tratare is not None:
                tratare(**date)

    # ------------------------------------------------------------------ bucla de desen

    def _programeaza_acum(self):
        if self._inchis:
            return
        if self._id_bucla is not None:
            self.root.after_cancel(self._id_bucla)
        self._id_bucla = self.root.after(1, self._bucla)

    def _bucla(self):
        self._id_bucla = None
        if self._inchis:
            return
        try:
            self._goleste_coada()
            self._sincronizeaza_voce()
            if self.mod == "chat" or self.motor.oprit or self._inghetat:
                pauza = 2.0   # fata nu se vede sau sta nemiscata: nu desenam nimic, doar golim coada
            else:
                t0 = time.perf_counter()
                st = self.motor.tick()
                self._ticks += 1
                if st is not None and self.afisaj.aplica(st):
                    self._desene += 1
                pauza = self.motor.interval_urmator()
                if self.afisaj.in_asteptare:
                    pauza = min(pauza, 1.0 / self.motor.fps_activ)
                # Dupa un cadru scump lasam procesorul liber de doua ori mai mult timp (microfon, wake word)
                pauza = max(pauza, 2.0 * (time.perf_counter() - t0))
                if self._txt_debug is not None:
                    self._actualizeaza_debug()
        except Exception as e:
            self._esec(e)
            return
        self._id_bucla = self.root.after(max(1, int(pauza * 1000)), self._bucla)

    def _deseneaza_final(self):
        """Deseneaza direct expresia tinta, fara tranzitie (inainte de a ingheta fata)."""
        st = dict(EXPRESII[self.motor.expresie_curenta])
        self.afisaj.max_grele = 8
        try:
            self.afisaj.aplica(st)
        finally:
            self.afisaj.max_grele = 1

    def _actualizeaza_debug(self):
        acum = time.monotonic()
        dt = acum - self._t_stat
        if dt < 2.0:
            return
        self.canvas.itemconfig(self._txt_debug, text=f"{self._ticks / dt:.0f} tick/s  {self._desene / dt:.0f} desene/s  "
                                                      f"cache {len(self.afisaj._cache)}  {self.motor.expresie_curenta}")
        self._ticks = self._desene = 0
        self._t_stat = acum

    def _esec(self, eroare):
        logger.error(f"[FACE]: Eroare in fata, revin la interfata clasica: {type(eroare).__name__}: {eroare}")
        self.inchide()
        if getattr(self.ui, "fata", None) is self:
            self.ui.fata = None

    def inchide(self):
        """Opreste fata si lasa interfata clasica exact cum era."""
        if self._inchis:
            return
        self._inchis = True
        for id_after in (self._id_bucla, self._id_auto, self._id_sub, self._id_verif):
            if id_after is not None:
                try:
                    self.root.after_cancel(id_after)
                except Exception as e:
                    logger.debug(f"[FACE INCHIDE AFTER]: {e}")
        try:
            self.canvas.place_forget()
            self.ui.btn_status.config(image="")
        except Exception as e:
            logger.debug(f"[FACE INCHIDE]: {e}")

    # ------------------------------------------------------------------ moduri de ecran

    def _ridica_canvas(self):
        if not self.canvas.winfo_manager():
            self.canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        # Canvas.lift() din tkinter muta elementele desenate, nu fereastra, deci chemam Tk direct
        self.root.tk.call("raise", self.canvas._w)

    def _coboara_canvas(self):
        # Scoasa de tot de pe ecran: altfel fata s-ar vedea prin spatiile dintre elementele interfetei
        self.canvas.place_forget()

    def arata_fata(self, animat=False):
        self.mod = "fata"
        self._chat_fortat = False
        self._ridica_canvas()
        self._seteaza_mini(False)
        self._actualizeaza_indicatori()
        if self._stare != "VIDEO":
            if self.motor.oprit:
                self.motor.porneste()
            if animat:
                self.motor.reapare()
        self._rearmeaza_auto()
        self._programeaza_acum()

    def arata_controale(self):
        self.mod = "controale"
        self._ridica_canvas()
        self.ui.bara_top.lift()
        self.ui.bara_jos.lift()
        self._seteaza_mini(False)
        self._rearmeaza_auto()
        self._programeaza_acum()

    def arata_chat(self, fortat=False):
        self.mod = "chat"
        self._chat_fortat = fortat
        self._coboara_canvas()
        self._seteaza_mini(True)
        self._rearmeaza_auto()

    def _poate_reveni(self):
        ui = self.ui
        if getattr(ui, "tastatura_activa", False) or self._stare == "VIDEO":
            return False
        if ui.frame_overlay.winfo_ismapped() and self._stare != "MUSIC":
            return False
        if self._stare == "IDLE" and ui.entry_input.get().strip():
            return False
        return True

    def _rearmeaza_auto(self):
        if self._id_auto is not None:
            self.root.after_cancel(self._id_auto)
            self._id_auto = None
        if self._inchis or self.mod == "fata":
            return
        cheie, implicit = (("ascunde_controale_dupa_sec", 8), ("revenire_dupa_sec", 20))[self.mod == "chat"]
        self._id_auto = self.root.after(int(float(self.cfg.get(cheie, implicit)) * 1000), self._auto)

    def _auto(self):
        self._id_auto = None
        if self._inchis:
            return
        if self.mod == "controale":
            if self._stare == "LISTENING":
                self._rearmeaza_auto()   # cat asculta, butoanele arata starea microfonului
            else:
                self.arata_fata()
        elif self.mod == "chat":
            if self._poate_reveni():
                self.arata_fata(animat=True)
            else:
                self._id_auto = self.root.after(3000, self._auto)

    def _la_suprapunere(self, _event=None):
        """Un overlay sau tastatura a aparut ori a disparut; verificam putin mai tarziu, fara palpait."""
        if self._inchis:
            return
        if self._id_verif is not None:
            self.root.after_cancel(self._id_verif)
        self._id_verif = self.root.after(60, self._verifica_suprapuneri)

    def _verifica_suprapuneri(self):
        self._id_verif = None
        if self._inchis:
            return
        try:
            ocupat = self.ui.frame_overlay.winfo_ismapped() or self.ui.frame_kb.winfo_ismapped()
            if ocupat:
                if self.mod != "chat":
                    self.arata_chat(fortat=True)
                else:
                    self._rearmeaza_auto()
            elif self.mod == "chat" and self._chat_fortat and self._poate_reveni():
                self.arata_fata(animat=True)
        except Exception as e:
            self._esec(e)

    # ------------------------------------------------------------------ atingere

    def _la_orice_atingere(self, _event=None):
        if not self._inchis:
            self._rearmeaza_auto()

    def _la_tasta(self, event=None):
        if self._inchis or self.mod == "chat":
            return
        if event is not None and (event.char or event.keysym in ("Return", "BackSpace")):
            try:
                self.arata_chat()
            except Exception as e:
                self._esec(e)

    def _priveste_spre(self, event):
        x = (event.x / max(1, self._lat)) * 2.0 - 1.0
        y = (event.y / max(1, self._inalt)) * 2.0 - 1.0
        self.motor.privire.seteaza(x, y, sursa="atingere", timeout_s=1.0)

    def _apasa(self, event):
        if self._inchis:
            return
        self._t_apasare = time.monotonic()
        self._xy_apasare = (event.x, event.y)
        self._drum = 0
        self._mangaiat = False
        self._priveste_spre(event)
        self._programeaza_acum()

    def _trage(self, event):
        if self._inchis:
            return
        x0, y0 = self._xy_apasare
        self._drum += abs(event.x - x0) + abs(event.y - y0)
        self._xy_apasare = (event.x, event.y)
        self._priveste_spre(event)
        if not self._mangaiat and self._drum > 60 * self._k:
            self._mangaiat = True
            if not self._dnd:
                self.motor.atinge("mangaiere")
        self._programeaza_acum()

    def _elibereaza(self, _event):
        if self._inchis or self._mangaiat:
            return
        try:
            acum = time.monotonic()
            if acum - self._t_apasare >= 0.6:
                if not self._dnd:
                    self.motor.atinge("apasare_lunga")
                self._programeaza_acum()
                return
            if acum - self._t_comutare < 0.25:
                return   # ecranul rezistiv poate da doua atingeri la una singura
            self._t_comutare = acum
            if self.mod == "fata":
                self.arata_controale()
            elif self.mod == "controale":
                self.arata_chat()
        except Exception as e:
            self._esec(e)

    # ------------------------------------------------------------------ indicatori, subtitrare, mini-fata

    def _actualizeaza_indicatori(self):
        ui = self.ui
        if self._dnd:
            culoare = "#E06C75"
        else:
            culoare = "#98C379" if getattr(ui, "wake_word_activ", False) else CULOARE_STINS
        self.canvas.itemconfig(self._punct, fill=culoare)
        ora = time.strftime("%H:%M")
        if self.canvas.itemcget(self._txt_ceas, "text") != ora:
            self.canvas.itemconfig(self._txt_ceas, text=ora)

    def _seteaza_subtitrare(self, text, sterge_dupa=None):
        if not self.cfg.get("subtitrare", True):
            return
        if self._id_sub is not None:
            self.root.after_cancel(self._id_sub)
            self._id_sub = None
        if self.canvas.itemcget(self._txt_sub, "text") != text:
            self.canvas.itemconfig(self._txt_sub, text=text)
        if text and sterge_dupa:
            self._id_sub = self.root.after(int(sterge_dupa * 1000), lambda: self._seteaza_subtitrare(""))

    def _seteaza_mini(self, activ):
        """Cand fata e retrasa (mod chat), o varianta mica a ei tine locul fetelor ASCII din bara de sus."""
        if not self.cfg.get("mini_fata", True):
            return
        nume = self.motor.expresie_curenta if activ else None
        if nume == self._mini_curent:
            return
        self._mini_curent = nume
        btn = self.ui.btn_status
        if nume is None:
            btn.config(image="")
            return
        foto = self._mini_cache.get(nume)
        if foto is None:
            from PIL import ImageTk
            lat, inalt = max(40, btn.winfo_width() - 12), max(16, btn.winfo_height() - 8)
            s = min(lat / 372.0, inalt / 118.0)
            geo = Geometrie(int(480 * s), int(320 * s))
            st, dr = geo.cutie_ochi("s"), geo.cutie_ochi("d")
            foto = ImageTk.PhotoImage(compune_cadru(geo, EXPRESII[nume]).crop((st[0], st[1], dr[2], dr[3])))
            self._mini_cache[nume] = foto
        btn.config(image=foto, compound="none")

    # ------------------------------------------------------------------ evenimente

    def _expresie_de_repaus(self):
        return "obosit" if self._obosit else "neutru"

    def _ev_stare(self, stare):
        anterioara, self._stare = self._stare, stare
        if stare != "LISTENING":
            self._inghetat = False
        m = self.motor
        if stare == "VIDEO":
            m.opreste()
            return
        if m.oprit and self.mod != "chat":
            m.porneste()
        if self._dnd:
            return
        if stare in EXPRESII_STARE:
            m.seteaza_expresie(EXPRESII_STARE[stare], viteza=1.4 if stare == "LISTENING" else 1.0)
        elif stare == "SPEAKING":
            m.seteaza_expresie(self._emotie_replica or "neutru")
        else:
            m.seteaza_expresie(self._expresie_de_repaus())
            if self._reactie_finala and anterioara == "SPEAKING":
                m.reactie(self._reactie_finala, 1.6)
            self._emotie_replica = self._reactie_finala = None
            if self.canvas.itemcget(self._txt_sub, "text"):
                self._seteaza_subtitrare(self.canvas.itemcget(self._txt_sub, "text"), sterge_dupa=6)
        if self.mod == "chat":
            self._mini_curent = None
            self._seteaza_mini(True)

    def _ev_mic(self, faza):
        if self._dnd:
            return
        if faza == "pregatire":
            self.motor.activitate()
            self._seteaza_subtitrare("")
        elif faza == "asculta":
            self.motor.seteaza_expresie("atent", viteza=1.4)
            if self.cfg.get("ingheata_la_ascultare", True):
                # Microfonul e deschis: desenam o data fata atenta, apoi o lasam nemiscata pana termini de vorbit
                self._deseneaza_final()
                self._inghetat = True
        elif faza == "procesare":
            self._inghetat = False
            self.motor.seteaza_expresie("ganditor")

    def _ev_wake_debug(self, text=""):
        """Vosk a auzit ceva care nu e inca 'Robot': o privire scurta intr-o parte, fara sa-l trezeasca."""
        acum = time.monotonic()
        if "Auzit" not in text or self._dnd or self._stare != "IDLE" or acum - self._t_wake < 4.0:
            return
        if self.motor.stadiu_somn >= 2:
            return
        self._t_wake = acum
        self.motor.privire.seteaza(self._rng.choice((-0.6, 0.6)), -0.15, sursa="eveniment", timeout_s=0.7)

    def _ev_actiune(self, actiune):
        self._emotie_replica, self._reactie_finala = EMOTII_ACTIUNE.get(actiune, ("neutru", None))

    def _ev_alarma(self):
        if not self._dnd:
            self.motor.reactie("entuziasmat", 4.0)

    def _ev_neinteles(self):
        if not self._dnd:
            self.motor.reactie("confuz", 2.5)
        self._seteaza_subtitrare("Nu am înțeles, repetă te rog.", sterge_dupa=5)

    def _ev_dnd(self, activ):
        self._dnd = bool(activ)
        if self._dnd:
            self.motor.adoarme()
        else:
            self.motor.seteaza_expresie(self._expresie_de_repaus())
            self.motor.activitate()
        self._actualizeaza_indicatori()

    def _ev_ceas(self):
        self._actualizeaza_indicatori()
        st = getattr(getattr(self.ui, "monitor_sanatate", None), "ultima_stare", None) or {}
        obosit = bool(st.get("undervoltage_acum") or st.get("throttled_acum") or st.get("temp_c", 0) >= 75.0)
        if obosit != self._obosit:
            self._obosit = obosit
            if self._stare == "IDLE" and not self._dnd:
                self.motor.seteaza_expresie(self._expresie_de_repaus())

    def _ev_mesaj(self, expeditor="", text=""):
        if expeditor == "Tu":
            self._seteaza_subtitrare(f"Tu: {self._scurteaza(text)}")
        elif expeditor.startswith("ALARM"):
            self._seteaza_subtitrare(self._scurteaza(text), sterge_dupa=10)

    def _ev_stream_start(self, expeditor=""):
        self._buffer_stream = ""
        if "SALUT" in expeditor:
            self._emotie_replica = "fericit"

    def _ev_stream_chunk(self, text=""):
        self._buffer_stream += text
        acum = time.monotonic()
        if acum - self._t_sub >= 0.3:
            self._t_sub = acum
            coada = " ".join(self._buffer_stream.split())
            self._seteaza_subtitrare(("…" + coada[-110:]) if len(coada) > 110 else coada)

    def _ev_stream_stop(self):
        self._seteaza_subtitrare(self._scurteaza(self._buffer_stream))

    def _ev_voce(self):
        """Vocea a pornit sau s-a oprit; bucla e deja trezita, iar gura se sincronizeaza la urmatorul cadru."""

    def _ev_expresie(self, nume, viteza=1.0):
        self.motor.seteaza_expresie(nume, viteza)

    def _ev_reactie(self, nume, durata=1.2):
        self.motor.reactie(nume, durata)

    @staticmethod
    def _scurteaza(text, limita=120):
        text = " ".join(str(text).split())
        return text if len(text) <= limita else text[:limita - 1].rstrip() + "…"
