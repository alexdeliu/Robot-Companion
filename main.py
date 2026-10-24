import io
import time
import signal
import urllib.request
from datetime import datetime
import tkinter as tk
import tkinter.font as tkfont
from tkinter import scrolledtext
import threading

from config import CFG, salveaza_config_local, APP_VERSION
from system_health import logger, MonitorSanatatePi, citeste_stare_hardware
from brain.ai_brain import (
    proceseaza_comanda_ai,
    genereaza_salut_pornire,
    reseteaza_memorie_ai
)
from brain.abilities.timers import seteaza_callback_alarma, opreste_toate_timerele
from ears.listen import asculta_voce, preincalzeste_microfon, _obtine_index_microfon
from ears.wake_word import asteapta_wake_word, obtine_strategie_activa, seteaza_callback_debug_wake
from voice.speak import vorbeste, opreste_voce
from brain.abilities.youtube_player import (
    deschide_overlay_youtube,
    inchide_overlay_youtube,
    toggle_pauza_media,
    deruleaza_media,
    piesa_urmatoare,
    piesa_anterioara,
    seteaza_volum_sistem,
    atenueaza_volum_temporar,
    restabileste_volum_normal,
    schimba_volum_relativ,
    este_media_activa,
    obtine_lista_curenta
)


class RobotState:
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    MUSIC = "MUSIC"
    VIDEO = "VIDEO"
    ERROR = "ERROR"


FETE_IDLE = ["(^_^)", "(o_o)", "(-_-)", "(^o^)"]


class RobotCompanionUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Robot Companion")

        self._state_lock = threading.RLock()
        self.stare = RobotState.IDLE
        self._task_id = 0
        self._last_click_ts = {}

        self.dnd_activ = bool(CFG["ui"].get("dnd_enabled", False))
        self.wake_word_activ = bool(CFG["wake_word"].get("enabled_by_default", True)) and not self.dnd_activ
        self.oprire_wake_event = threading.Event()
        self.fir_wake_activ = False
        self.inchidere_aplicatie = False
        self._img_referinta_ui = None
        self._img_video_frame = None
        self._ultimul_cautare_yt = ""
        self._ultimele_rezultate_yt = []
        self._idx_fata = 0

        self.monitor_sanatate = MonitorSanatatePi(interval_sec=25)
        self.monitor_sanatate.start()
        seteaza_callback_alarma(self._declanseaza_alarma_timer)
        seteaza_callback_debug_wake(self._actualizeaza_status_wake_live)

        seteaza_volum_sistem(int(CFG["audio_out"].get("volum_normal", 95)), salveaza_ca_normal=True)

        # --- KIOSK MODE ADAPTAT LA REZOLUȚIA REALĂ A ECRANULUI SPI ---
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.screen_width = max(320, self.root.winfo_screenwidth())
        self.screen_height = max(240, self.root.winfo_screenheight())
        self.root.geometry(f"{self.screen_width}x{self.screen_height}+0+0")
        self.root.configure(bg="#1E222A")

        self.ecran_mic = self.screen_width <= 520
        f_top = 9 if self.ecran_mic else 10
        f_bot = 11 if self.ecran_mic else 13

        # --- BARA DE SUS (Grilă Uniformă cu 6 Celule Clare, Înălțime 10% pentru Touch) ---
        self.bara_top = tk.Frame(self.root, bg="#1E222A")
        self.bara_top.place(relx=0.02, rely=0.01, relwidth=0.96, relheight=0.10)
        for col_i, w_col in enumerate((22, 13, 12, 18, 13, 12, 10)):
            self.bara_top.grid_columnconfigure(col_i, weight=w_col)
        self.bara_top.grid_rowconfigure(0, weight=1)

        txt_w = "● WAKE ON" if self.wake_word_activ else "○ WAKE OFF"
        bg_w = "#98C379" if self.wake_word_activ else "#4B5263"
        fg_w = "#1E222A" if self.wake_word_activ else "white"
        self.btn_wake = tk.Button(
            self.bara_top, text=txt_w, font=("Arial", f_top, "bold"),
            bg=bg_w, fg=fg_w, activebackground=bg_w, relief="flat", bd=1,
            command=lambda: self._debounce("wake", self.toggle_wake_word)
        )
        self.btn_wake._short_text = "WAKE"
        self.btn_wake.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

        self.btn_stop_media = tk.Button(
            self.bara_top, text="■ STOP", font=("Arial", f_top, "bold"),
            bg="#3B4252", fg="white", activebackground="#E06C75", relief="flat", bd=1,
            command=lambda: self._debounce("stop", self.opreste_tot_media)
        )
        self.btn_stop_media._short_text = "STOP"
        self.btn_stop_media.grid(row=0, column=1, sticky="nsew", padx=2, pady=2)

        self.btn_clear = tk.Button(
            self.bara_top, text="⌫ CLR", font=("Arial", f_top, "bold"),
            bg="#3B4252", fg="#ABB2BF", activebackground="#4B5263", relief="flat", bd=1,
            command=lambda: self._debounce("clr", self.curata_conversatia)
        )
        self.btn_clear._short_text = "CLR"
        self.btn_clear.grid(row=0, column=2, sticky="nsew", padx=2, pady=2)

        self.btn_status = tk.Button(
            self.bara_top, text="(^_^) OK", font=("Arial", f_top, "bold"),
            bg="#282C34", fg="#E5C07B", activebackground="#3B4252", relief="flat", bd=1,
            command=lambda: self._debounce("status", self.afiseaza_overlay_status)
        )
        self.btn_status._short_text = "INFO"
        self.btn_status.grid(row=0, column=3, sticky="nsew", padx=2, pady=2)

        txt_dnd = "DND ON" if self.dnd_activ else "DND OFF"
        bg_dnd = "#E06C75" if self.dnd_activ else "#282C34"
        self.btn_dnd = tk.Button(
            self.bara_top, text=txt_dnd, font=("Arial", f_top, "bold"),
            bg=bg_dnd, fg="white", relief="flat", bd=1,
            command=lambda: self._debounce("dnd", self.toggle_dnd)
        )
        self.btn_dnd._short_text = "DND"
        self.btn_dnd.grid(row=0, column=4, sticky="nsew", padx=2, pady=2)

        self.lbl_ceas = tk.Label(
            self.bara_top, text="00:00", font=("Arial", f_top + 1, "bold"),
            bg="#282C34", fg="#61AFEF"
        )
        self.lbl_ceas.grid(row=0, column=5, sticky="nsew", padx=2, pady=2)

        self.btn_exit = tk.Button(
            self.bara_top, text="✕", font=("Arial", f_top + 2, "bold"),
            bg="#E06C75", fg="white", activebackground="#BE5046", relief="flat", bd=1,
            command=self.inchide_curat
        )
        self.btn_exit._short_text = "X"
        self.btn_exit.grid(row=0, column=6, sticky="nsew", padx=2, pady=2)

        # --- ZONA DE AFIȘARE TEXT (CHAT) ---
        self.text_display = scrolledtext.ScrolledText(
            self.root, font=("Arial", 11 if self.ecran_mic else 12), bg="#1E222A", fg="#ABB2BF",
            wrap=tk.WORD, relief="flat", state=tk.DISABLED
        )
        self.text_display.place(relx=0.02, rely=0.12, relwidth=0.96, relheight=0.57)
        self.afiseaza_mesaj("Sistem", "Sisteme online. Îmi trezesc creierul AI...")

        # --- CONTAINER OVERLAY-URI ---
        self.frame_overlay = tk.Frame(
            self.root, bg="#21252B",
            highlightbackground="#61AFEF", highlightthickness=2
        )

        # --- BARĂ STATUS LIVE & INPUT ---
        self.lbl_wake_debug = tk.Label(
            self.root, text="Stare: IDLE | Spune 'Robot' sau apasă MIC",
            font=("Arial", 8, "bold"), bg="#1E222A", fg="#5C6370", anchor="w"
        )
        self.lbl_wake_debug.place(relx=0.02, rely=0.695, relwidth=0.96, relheight=0.035)

        self.entry_input = tk.Entry(
            self.root, font=("Arial", 12 if self.ecran_mic else 14, "bold"),
            bg="#282C34", fg="white", insertbackground="white", relief="flat"
        )
        self.entry_input.place(relx=0.02, rely=0.735, relwidth=0.96, relheight=0.105)
        self.entry_input.bind("<Return>", lambda event: self.start_procesare())

        # --- BUTOANE JOS (KB, MIC PUSH-TO-TALK, TRIMITE) ---
        self.bara_jos = tk.Frame(self.root, bg="#1E222A")
        self.bara_jos.place(relx=0.02, rely=0.855, relwidth=0.96, relheight=0.125)
        self.bara_jos.grid_columnconfigure(0, weight=18)
        self.bara_jos.grid_columnconfigure(1, weight=24)
        self.bara_jos.grid_columnconfigure(2, weight=58)
        self.bara_jos.grid_rowconfigure(0, weight=1)

        self.tastatura_activa = False
        self.btn_kb = tk.Button(
            self.bara_jos, text="⌨ KB", font=("Arial", f_bot, "bold"),
            bg="#4B5263", fg="white", activebackground="#5C6370", activeforeground="white",
            command=lambda: self._debounce("kb", self.toggle_tastatura), relief="flat"
        )
        self.btn_kb._short_text = "KB"
        self.btn_kb.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

        self.btn_mic = tk.Button(
            self.bara_jos, text="🎤 MIC", font=("Arial", f_bot, "bold"),
            bg="#C678DD", fg="white", activebackground="#98C379", activeforeground="#1E222A",
            command=lambda: self._debounce("mic", self.declanseaza_ascultare), relief="flat"
        )
        self.btn_mic._short_text = "MIC"
        self.btn_mic.grid(row=0, column=1, sticky="nsew", padx=2, pady=2)

        self.btn_send = tk.Button(
            self.bara_jos, text="➤ TRIMITE", font=("Arial", f_bot, "bold"),
            bg="#61AFEF", fg="#1E222A", activebackground="#98C379", activeforeground="#1E222A",
            command=lambda: self._debounce("send", self.start_procesare), relief="flat"
        )
        self.btn_send._short_text = "TRIMITE"
        self.btn_send.grid(row=0, column=2, sticky="nsew", padx=2, pady=2)

        self.frame_kb = tk.Frame(self.root, bg="#1E222A")
        self.construieste_tastatura()

        self._actualizeaza_ceas()
        self.root.after(80, self.adapteaza_toate_butoanele)
        self.entry_input.focus_force()
        self.root.after(150, self.porneste_salut_initial)

    # --- AUTO-FIT FONT PENTRU BUTOANE (P2: Măsoară cu tkfont.Font.measure) ---
    def adapteaza_buton_la_spatiu(self, btn):
        try:
            self.root.update_idletasks()
            latime_disp = btn.winfo_width() - 10
            if latime_disp <= 12:
                return
            text_curent = str(btn.cget("text"))
            f_actual = tkfont.Font(font=btn.cget("font"))
            marime = int(f_actual.cget("size"))
            familie = f_actual.cget("family")

            while marime > 8 and f_actual.measure(text_curent) > latime_disp:
                marime -= 1
                f_actual.configure(size=marime)

            if f_actual.measure(text_curent) > latime_disp and hasattr(btn, "_short_text"):
                btn.config(text=btn._short_text)
            btn.config(font=(familie, marime, "bold"))
        except Exception as e:
            logger.debug(f"[UI AUTOFIT]: {e}")

    def adapteaza_toate_butoanele(self, container=None):
        radacina = container or self.root
        for w in radacina.winfo_children():
            if isinstance(w, tk.Button):
                self.adapteaza_buton_la_spatiu(w)
            elif isinstance(w, tk.Frame):
                self.adapteaza_toate_butoanele(w)

    def _actualizeaza_status_wake_live(self, text_info):
        if self.inchidere_aplicatie:
            return
        self.root.after(0, lambda: self.lbl_wake_debug.config(text=f"Stare: {self.stare} | {text_info}"))

    def toggle_dnd(self):
        self.dnd_activ = not self.dnd_activ
        salveaza_config_local("ui", "dnd_enabled", self.dnd_activ)
        if self.dnd_activ:
            self.btn_dnd.config(text="DND ON", bg="#E06C75")
            if self.wake_word_activ:
                self.toggle_wake_word()
            opreste_voce()
        else:
            self.btn_dnd.config(text="DND OFF", bg="#282C34")

    # --- DEBOUNCE & MANAGEMENTUL STĂRII (P3) ---
    def _debounce(self, cheie, functie):
        acum = time.monotonic()
        prag = float(CFG["ui"].get("debounce_ms", 220)) / 1000.0
        if acum - self._last_click_ts.get(cheie, 0.0) < prag:
            return
        self._last_click_ts[cheie] = acum
        functie()

    def _nou_task(self):
        with self._state_lock:
            self._task_id += 1
            return self._task_id

    def _este_task_valid(self, tid):
        with self._state_lock:
            return tid == self._task_id and not self.inchidere_aplicatie

    def _seteaza_stare_ui(self, stare_noua):
        with self._state_lock:
            self.stare = stare_noua

        def _update():
            if self.inchidere_aplicatie:
                return
            self.lbl_wake_debug.config(text=f"Stare: {stare_noua} | Wake: {'ON' if self.wake_word_activ else 'OFF'}")
            if stare_noua == RobotState.IDLE:
                self.btn_send.config(text="➤ TRIMITE", bg="#61AFEF", fg="#1E222A")
                self.btn_mic.config(text="🎤 MIC", bg="#C678DD", fg="white")
            elif stare_noua == RobotState.LISTENING:
                self.btn_mic.config(bg="#E06C75", fg="white", text="● REC")
                self.btn_send.config(bg="#E06C75", fg="white", text="VORBEȘTE ACUM!")
            elif stare_noua == RobotState.THINKING:
                self.btn_send.config(text="GÂNDESC...", bg="#E5C07B", fg="#1E222A")
                self.btn_mic.config(bg="#C678DD", fg="white", text="🎤 MIC")
            elif stare_noua == RobotState.SPEAKING:
                self.btn_send.config(text="VORBESC...", bg="#98C379", fg="#1E222A")
                self.btn_mic.config(bg="#C678DD", fg="white", text="🎤 MIC")
            elif stare_noua in (RobotState.MUSIC, RobotState.VIDEO):
                self.btn_send.config(text="➤ TRIMITE", bg="#61AFEF", fg="#1E222A")
                self.btn_mic.config(text="🎤 MIC", bg="#C678DD", fg="white")

        self.root.after(0, _update)

    def _actualizeaza_ceas(self):
        if self.inchidere_aplicatie:
            return
        ora_noua = datetime.now().strftime("%H:%M")
        if self.lbl_ceas.cget("text") != ora_noua:
            self.lbl_ceas.config(text=ora_noua)
        interval_ms = int(CFG["ui"].get("clock_refresh_ms", 10000))
        if self.stare == RobotState.IDLE:
            self._idx_fata = (self._idx_fata + 1) % len(FETE_IDLE)
            st_hw = self.monitor_sanatate.ultima_stare
            temp_txt = f"{int(st_hw['temp_c'])}°C" if st_hw["temp_c"] > 0 else "OK"
            self.btn_status.config(text=f"{FETE_IDLE[self._idx_fata]} {temp_txt}")
            if CFG["ui"].get("adaptive_idle_polling", False) and st_hw["temp_c"] >= 70.0:
                interval_ms = max(interval_ms, 25000)
        self.root.after(interval_ms, self._actualizeaza_ceas)

    def _declanseaza_alarma_timer(self, mesaj_alarma):
        def _afis():
            self.afiseaza_mesaj("ALARMĂ / TIMER", mesaj_alarma)
        self.root.after(0, _afis)
        if not self.dnd_activ:
            threading.Thread(target=vorbeste, args=(mesaj_alarma, "ro"), daemon=True).start()

    def _incarca_imagine_url(self, url, latime=110, inaltime=85):
        if not url:
            return None
        try:
            from PIL import Image, ImageTk
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=3) as rasp:
                raw_data = rasp.read()
            pil_img = Image.open(io.BytesIO(raw_data)).convert("RGB")
            pil_img = pil_img.resize((latime, inaltime), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(pil_img)
        except Exception as e:
            logger.debug(f"[IMG URL]: {e}")
            return None

    def curata_conversatia(self):
        self._nou_task()
        opreste_voce()
        reseteaza_memorie_ai()
        self.ascunde_overlay()
        self.text_display.config(state=tk.NORMAL)
        self.text_display.delete("1.0", tk.END)
        self.text_display.config(state=tk.DISABLED)
        self.afiseaza_mesaj("Sistem", "Conversația și memoria au fost resetate.")
        self._seteaza_stare_ui(RobotState.IDLE)
        self.porneste_ascultare_wake_word()

    def inchide_curat(self):
        logger.info("Închidere curată a aplicației Robot Companion...")
        self.inchidere_aplicatie = True
        self._nou_task()
        self.oprire_wake_event.set()
        self.monitor_sanatate.stop()
        opreste_toate_timerele()
        opreste_voce()
        inchide_overlay_youtube()
        try:
            self.root.destroy()
        except Exception as e:
            logger.debug(f"[DESTROY]: {e}")

    # --- OVERLAY 0: PAGINĂ STATUS SISTEM (P2: Butonul ÎNCHIDE împachetat PRIMUL) ---
    def afiseaza_overlay_status(self, st_preluat=None):
        self.ascunde_overlay()
        for w in self.frame_overlay.winfo_children():
            w.destroy()

        st = st_preluat or citeste_stare_hardware()
        bara = tk.Frame(self.frame_overlay, bg="#282C34")
        bara.pack(fill="x", padx=4, pady=3)

        btn_close = tk.Button(
            bara, text="✕ ÎNCHIDE", font=("Arial", 10, "bold"),
            bg="#E06C75", fg="white", relief="flat", padx=8, pady=3, command=self.ascunde_overlay
        )
        btn_close._short_text = "✕"
        btn_close.pack(side="right", padx=4, pady=2)

        tk.Label(
            bara, text=f"STATUS HARDWARE & AUDIO (v{APP_VERSION})",
            font=("Arial", 10, "bold"), bg="#282C34", fg="#E5C07B", anchor="w"
        ).pack(side="left", fill="x", expand=True, padx=6, pady=2)

        corp = tk.Frame(self.frame_overlay, bg="#21252B")
        corp.pack(fill="both", expand=True, padx=10, pady=4)

        mic_idx = _obtine_index_microfon()
        strat_w = obtine_strategie_activa()
        alim_txt = "UNDERVOLTAGE!" if st["undervoltage_acum"] else f"OK ({st['throttled_hex']})"
        av_txt = ", ".join(st["avertismente"]) if st["avertismente"] else "Niciun avertisment."

        linii = [
            f"• Stare Robot: {self.stare} | DND: {'ON' if self.dnd_activ else 'OFF'}",
            f"• Temperatură CPU: {st['temp_c']} °C | Alimentare: {alim_txt}",
            f"• Memorie RAM Liberă: {st['ram_avail_mb']} MB / {st['ram_total_mb']} MB ({st['ram_procent']}%)",
            f"• Microfon: Index #{mic_idx} | Strategie Wake: {strat_w}",
            f"• Ecran Kiosk: {self.screen_width}x{self.screen_height} px",
            f"• Sănătate: {av_txt}"
        ]
        for l_txt in linii:
            tk.Label(
                corp, text=l_txt, font=("Arial", 9 if self.ecran_mic else 10, "bold"),
                bg="#21252B", fg="#ABB2BF", anchor="w"
            ).pack(fill="x", pady=1)

        self.frame_overlay.place(relx=0.02, rely=0.12, relwidth=0.96, relheight=0.57)
        self.frame_overlay.lift()
        self.adapteaza_toate_butoanele(self.frame_overlay)

    # --- OVERLAY 1: CARD VIZUAL WIKIPEDIA (Butoanele împachetate ÎNAINTEA titlului!) ---
    def afiseaza_overlay_wikipedia(self, info_wiki):
        self.ascunde_overlay()
        for w in self.frame_overlay.winfo_children():
            w.destroy()

        bara_titlu = tk.Frame(self.frame_overlay, bg="#282C34")
        bara_titlu.pack(fill="x", padx=4, pady=3)

        partea = info_wiki.get("partea_curenta", 1)
        total = info_wiki.get("total_parti", 1)

        btn_inchide = tk.Button(
            bara_titlu, text="✕ ÎNCHIDE", font=("Arial", 9, "bold"),
            bg="#E06C75", fg="white", relief="flat", padx=6, pady=3, command=self.opreste_tot_media
        )
        btn_inchide._short_text = "✕"
        btn_inchide.pack(side="right", padx=3, pady=2)

        if partea < total:
            btn_mai_mult = tk.Button(
                bara_titlu, text="MAI MULT ▶", font=("Arial", 9, "bold"),
                bg="#98C379", fg="#1E222A", relief="flat", padx=6, pady=3,
                command=lambda: self._trimite_comanda_rapida("Spune-mi mai mult")
            )
            btn_mai_mult._short_text = "▶"
            btn_mai_mult.pack(side="right", padx=3, pady=2)

        titlu_scurt = info_wiki.get("titlu", "")[:26]
        tk.Label(
            bara_titlu,
            text=f"WIKI: {titlu_scurt} ({partea}/{total})",
            font=("Arial", 10, "bold"), bg="#282C34", fg="#61AFEF", anchor="w"
        ).pack(side="left", fill="x", expand=True, padx=4, pady=2)

        corp_wiki = tk.Frame(self.frame_overlay, bg="#21252B")
        corp_wiki.pack(fill="both", expand=True, padx=8, pady=4)

        txt_wiki = scrolledtext.ScrolledText(
            corp_wiki, font=("Arial", 11), bg="#21252B", fg="#ABB2BF",
            wrap=tk.WORD, relief="flat"
        )
        txt_wiki.pack(side="right", fill="both", expand=True)
        txt_wiki.insert(tk.END, info_wiki.get("rezumat", ""))
        txt_wiki.config(state=tk.DISABLED)

        self.frame_overlay.place(relx=0.02, rely=0.12, relwidth=0.96, relheight=0.57)
        self.frame_overlay.lift()
        self.adapteaza_toate_butoanele(self.frame_overlay)

        url_img = info_wiki.get("imagine", "")
        if url_img:
            def _load_img():
                img_tk = self._incarca_imagine_url(url_img, latime=90, inaltime=90)
                if img_tk and not self.inchidere_aplicatie:
                    def _pin():
                        if corp_wiki.winfo_exists():
                            self._img_referinta_ui = img_tk
                            tk.Label(corp_wiki, image=img_tk, bg="#21252B").pack(side="left", padx=(2, 6), anchor="n")
                    self.root.after(0, _pin)
            threading.Thread(target=_load_img, daemon=True).start()

    # --- OVERLAY 2: SELECTOR 5 REZULTATE YOUTUBE ---
    def afiseaza_overlay_youtube_lista(self, cautare, rezultate):
        self._ultimul_cautare_yt = cautare
        self._ultimele_rezultate_yt = rezultate
        self.ascunde_overlay()
        for w in self.frame_overlay.winfo_children():
            w.destroy()

        bara_titlu = tk.Frame(self.frame_overlay, bg="#282C34")
        bara_titlu.pack(fill="x", padx=4, pady=3)

        btn_close = tk.Button(
            bara_titlu, text="✕ ÎNCHIDE", font=("Arial", 9, "bold"),
            bg="#E06C75", fg="white", relief="flat", padx=6, pady=2, command=self.opreste_tot_media
        )
        btn_close._short_text = "✕"
        btn_close.pack(side="right", padx=3, pady=2)

        tk.Label(
            bara_titlu,
            text=f"YOUTUBE: {cautare.upper()[:24]}",
            font=("Arial", 10, "bold"), bg="#282C34", fg="#E06C75", anchor="w"
        ).pack(side="left", fill="x", expand=True, padx=4, pady=2)

        container = tk.Frame(self.frame_overlay, bg="#21252B")
        container.pack(fill="both", expand=True, padx=6, pady=2)

        lim_chr = 36 if self.ecran_mic else 54
        for item in rezultate[:5]:
            nr = item["numar"]
            rand = tk.Frame(container, bg="#282C34")
            rand.pack(fill="x", pady=1)

            btn_p = tk.Button(
                rand, text=f"▶ #{nr}", font=("Arial", 9, "bold"),
                bg="#E06C75", fg="white", relief="flat", width=6,
                command=lambda n=nr: self.porneste_video_selectat(n)
            )
            btn_p._short_text = f"#{nr}"
            btn_p.pack(side="left", padx=3, pady=2)

            titlu_scurt = item["titlu"][:lim_chr] + ("..." if len(item["titlu"]) > lim_chr else "")
            tk.Label(
                rand, text=f"{titlu_scurt} [{item.get('durata', '')}]",
                font=("Arial", 9 if self.ecran_mic else 10, "bold"), bg="#282C34", fg="white", anchor="w"
            ).pack(side="left", fill="x", expand=True, padx=4)

        self.frame_overlay.place(relx=0.02, rely=0.12, relwidth=0.96, relheight=0.57)
        self.frame_overlay.lift()
        self.adapteaza_toate_butoanele(self.frame_overlay)

    # --- OVERLAY 2B: PLAYER VIDEO ÎNCORPORAT (P1 & P2: Canvas SPI + Grilă Uniformă 6 Butoane) ---
    def afiseaza_overlay_video_activ(self, piesa, asteapta_tts=False):
        self._seteaza_stare_ui(RobotState.VIDEO)
        self.ascunde_overlay()
        for w in self.frame_overlay.winfo_children():
            w.destroy()

        bara_ctrl = tk.Frame(self.frame_overlay, bg="#181A1F")
        bara_ctrl.pack(fill="x", padx=3, pady=2)
        for i in range(6):
            bara_ctrl.grid_columnconfigure(i, weight=1, uniform="vctrl")
        bara_ctrl.grid_rowconfigure(0, weight=1)

        f_v = 8 if self.ecran_mic else 9
        butoane_v = [
            ("◀ LISTĂ", "LIST", "#4B5263", "white", self._inapoi_la_lista_yt),
            ("♫ AUDIO", "AUD", "#C678DD", "white", lambda: self._comuta_pe_muzica(piesa)),
            ("⏪ -10s", "-10s", "#3B4252", "white", lambda: deruleaza_media(-10)),
            ("⏸ PAUZĂ", "PAU", "#E5C07B", "#1E222A", toggle_pauza_media),
            ("⏩ +10s", "+10s", "#3B4252", "white", lambda: deruleaza_media(10)),
            ("■ STOP", "STOP", "#E06C75", "white", self.opreste_tot_media),
        ]
        for idx, (txt, sh_txt, bg_c, fg_c, cmd_fn) in enumerate(butoane_v):
            b = tk.Button(
                bara_ctrl, text=txt, font=("Arial", f_v, "bold"),
                bg=bg_c, fg=fg_c, relief="flat", command=cmd_fn
            )
            b._short_text = sh_txt
            b.grid(row=0, column=idx, sticky="nsew", padx=1, pady=1)

        self.lbl_video_status = tk.Label(
            self.frame_overlay,
            text=f"Se încarcă video: {piesa.get('titlu', '')[:42]}...",
            font=("Arial", 9, "bold"), bg="#181A1F", fg="#98C379", anchor="w"
        )
        self.lbl_video_status.pack(fill="x", padx=4)

        self.video_surface = tk.Label(
            self.frame_overlay, bg="black", fg="#ABB2BF",
            text="Se pregătește fluxul video + audio YouTube...",
            font=("Arial", 10, "bold")
        )
        self.video_surface.pack(fill="both", expand=True, padx=4, pady=2)

        self.frame_overlay.place(relx=0.02, rely=0.12, relwidth=0.96, relheight=0.57)
        self.frame_overlay.lift()
        self.root.update_idletasks()
        self.adapteaza_toate_butoanele(self.frame_overlay)

        if not asteapta_tts:
            self._lanseaza_stream_video_in_surface(piesa)

    def _lanseaza_stream_video_in_surface(self, piesa):
        if not hasattr(self, "video_surface") or not self.video_surface.winfo_exists():
            return
        wid = self.video_surface.winfo_id()
        w_surf = max(240, self.video_surface.winfo_width())
        h_surf = max(135, self.video_surface.winfo_height())

        def _primeste_frame_rgb(raw_rgb, w, h):
            if self.inchidere_aplicatie or self.stare != RobotState.VIDEO:
                return
            try:
                from PIL import Image, ImageTk
                img_pil = Image.frombytes("RGB", (w, h), raw_rgb)
                img_tk = ImageTk.PhotoImage(img_pil)

                def _draw():
                    if hasattr(self, "video_surface") and self.video_surface.winfo_exists():
                        self._img_video_frame = img_tk
                        self.video_surface.config(image=img_tk, text="")
                self.root.after(0, _draw)
            except Exception as e:
                logger.debug(f"[DRAW SPI FRAME]: {e}")

        def _set_status(msg_st):
            if not self.inchidere_aplicatie:
                def _upd():
                    if hasattr(self, "lbl_video_status") and self.lbl_video_status.winfo_exists():
                        self.lbl_video_status.config(text=msg_st)
                self.root.after(0, _upd)

        threading.Thread(
            target=deschide_overlay_youtube,
            args=(piesa["video_id"], False, wid, _primeste_frame_rgb, _set_status, (w_surf, h_surf)),
            name="VideoStartWorker",
            daemon=True
        ).start()

    def _inapoi_la_lista_yt(self):
        inchide_overlay_youtube()
        if self._ultimele_rezultate_yt:
            self.afiseaza_overlay_youtube_lista(self._ultimul_cautare_yt, self._ultimele_rezultate_yt)

    def _comuta_pe_muzica(self, piesa):
        self.afiseaza_overlay_youtube_music(piesa)
        threading.Thread(
            target=deschide_overlay_youtube,
            args=(piesa["video_id"], True, None, None, self._set_music_status),
            daemon=True
        ).start()

    # --- OVERLAY 3: YOUTUBE MUSIC PLAYER (Grilă Uniformă 6 Butoane + Coadă Vizibilă) ---
    def afiseaza_overlay_youtube_music(self, piesa):
        self._seteaza_stare_ui(RobotState.MUSIC)
        self.ascunde_overlay()
        for w in self.frame_overlay.winfo_children():
            w.destroy()

        bara_sus = tk.Frame(self.frame_overlay, bg="#181A1F")
        bara_sus.pack(fill="x", padx=4, pady=3)

        btn_stop_m = tk.Button(
            bara_sus, text="■ OPREȘTE", font=("Arial", 9, "bold"),
            bg="#E06C75", fg="white", relief="flat", padx=6, command=self.opreste_tot_media
        )
        btn_stop_m._short_text = "STOP"
        btn_stop_m.pack(side="right", padx=3)

        btn_vid_m = tk.Button(
            bara_sus, text="🎬 VIDEO", font=("Arial", 9, "bold"),
            bg="#61AFEF", fg="#1E222A", relief="flat", padx=6,
            command=lambda: self.afiseaza_overlay_video_activ(piesa)
        )
        btn_vid_m._short_text = "VIDEO"
        btn_vid_m.pack(side="right", padx=3)

        lista_c, idx_c = obtine_lista_curenta()
        info_coada = f"({idx_c + 1}/{len(lista_c)})" if lista_c else ""
        tk.Label(
            bara_sus, text=f"YOUTUBE MUSIC {info_coada}",
            font=("Arial", 10, "bold"), bg="#181A1F", fg="#C678DD", anchor="w"
        ).pack(side="left", fill="x", expand=True, padx=4)

        corp = tk.Frame(self.frame_overlay, bg="#21252B")
        corp.pack(fill="both", expand=True, padx=8, pady=4)

        info_zona = tk.Frame(corp, bg="#21252B")
        info_zona.pack(fill="x", pady=2)

        text_zona = tk.Frame(info_zona, bg="#21252B")
        text_zona.pack(side="right", fill="both", expand=True)

        self.lbl_music_title = tk.Label(
            text_zona, text=piesa.get("titlu", "Melodie"),
            font=("Arial", 11 if self.ecran_mic else 12, "bold"), bg="#21252B", fg="white",
            wraplength=int(self.screen_width * 0.60), justify="left", anchor="w"
        )
        self.lbl_music_title.pack(fill="x", pady=(2, 2))

        self.lbl_music_artist = tk.Label(
            text_zona, text=f"Canal: {piesa.get('canal', 'YouTube')} • {piesa.get('durata', 'Audio')}",
            font=("Arial", 9, "bold"), bg="#21252B", fg="#98C379", anchor="w"
        )
        self.lbl_music_artist.pack(fill="x")

        # Grilă uniformă cu 6 coloane (garantează că niciun buton nu iese în afara ecranului SPI)
        controale = tk.Frame(corp, bg="#21252B")
        controale.pack(fill="x", pady=6)
        for col_i in range(6):
            controale.grid_columnconfigure(col_i, weight=1, uniform="mctrl")
        controale.grid_rowconfigure(0, weight=1)

        f_m = 9 if self.ecran_mic else 10
        cfg_butoane_m = [
            ("🔉 V-", "V-", "#3B4252", "white", lambda: schimba_volum_relativ(-12)),
            ("⏮ PREV", "PREV", "#4B5263", "white", self._muzica_prev),
            ("⏸ PAUZĂ", "PAU", "#E5C07B", "#1E222A", self._toggle_pauza_ui),
            ("■ STOP", "STOP", "#E06C75", "white", self.opreste_tot_media),
            ("⏭ NEXT", "NEXT", "#4B5263", "white", self._muzica_next),
            ("🔊 V+", "V+", "#3B4252", "white", lambda: schimba_volum_relativ(12)),
        ]
        for idx, (txt, sh_txt, bg_c, fg_c, cmd_fn) in enumerate(cfg_butoane_m):
            btn = tk.Button(
                controale, text=txt, font=("Arial", f_m, "bold"),
                bg=bg_c, fg=fg_c, relief="flat", command=cmd_fn
            )
            btn._short_text = sh_txt
            btn.grid(row=0, column=idx, sticky="nsew", padx=2, pady=2, ipady=4)
            if sh_txt == "PAU":
                self.btn_pauza_muzica = btn

        self.frame_overlay.place(relx=0.02, rely=0.12, relwidth=0.96, relheight=0.57)
        self.frame_overlay.lift()
        self.adapteaza_toate_butoanele(self.frame_overlay)

        url_min = piesa.get("miniatura", "")
        if url_min:
            def _load_cov():
                img_cov = self._incarca_imagine_url(url_min, latime=90, inaltime=68)
                if img_cov and not self.inchidere_aplicatie:
                    def _pin():
                        if info_zona.winfo_exists():
                            self._img_referinta_ui = img_cov
                            tk.Label(info_zona, image=img_cov, bg="#21252B").pack(side="left", padx=(2, 8))
                    self.root.after(0, _pin)
            threading.Thread(target=_load_cov, daemon=True).start()

    def _set_music_status(self, txt):
        if not self.inchidere_aplicatie:
            def _u():
                if hasattr(self, "lbl_music_artist") and self.lbl_music_artist.winfo_exists():
                    self.lbl_music_artist.config(text=txt)
            self.root.after(0, _u)

    def _toggle_pauza_ui(self):
        in_pauza = toggle_pauza_media()
        if hasattr(self, "btn_pauza_muzica") and self.btn_pauza_muzica.winfo_exists():
            if in_pauza:
                self.btn_pauza_muzica.config(text="▶ PLAY", bg="#98C379", fg="#1E222A")
            else:
                self.btn_pauza_muzica.config(text="⏸ PAUZĂ", bg="#E5C07B", fg="#1E222A")

    def _muzica_next(self):
        self._set_music_status("Se încarcă piesa următoare...")
        def _bg():
            ales = piesa_urmatoare(on_status_ui=self._set_music_status)
            if ales and not self.inchidere_aplicatie:
                self.root.after(0, self.afiseaza_overlay_youtube_music, ales)
        threading.Thread(target=_bg, daemon=True).start()

    def _muzica_prev(self):
        self._set_music_status("Se încarcă piesa anterioară...")
        def _bg():
            ales = piesa_anterioara(on_status_ui=self._set_music_status)
            if ales and not self.inchidere_aplicatie:
                self.root.after(0, self.afiseaza_overlay_youtube_music, ales)
        threading.Thread(target=_bg, daemon=True).start()

    def porneste_video_selectat(self, numar):
        self._nou_task()
        opreste_voce()
        if not self._ultimele_rezultate_yt:
            return
        idx = max(0, min(len(self._ultimele_rezultate_yt) - 1, int(numar) - 1))
        ales = self._ultimele_rezultate_yt[idx]
        self.afiseaza_mesaj("Sistem", f"Redau videoclipul #{numar}: {ales['titlu']}")
        self.afiseaza_overlay_video_activ(ales, asteapta_tts=False)

    def opreste_tot_media(self):
        self._nou_task()
        opreste_voce()
        inchide_overlay_youtube()
        self.ascunde_overlay()
        restabileste_volum_normal()
        self._seteaza_stare_ui(RobotState.IDLE)
        self.porneste_ascultare_wake_word()

    def ascunde_overlay(self):
        self.frame_overlay.place_forget()

    def _trimite_comanda_rapida(self, text_comanda):
        opreste_voce()
        self.entry_input.delete(0, tk.END)
        self.entry_input.insert(0, text_comanda)
        self.start_procesare(fortat=True)

    # --- WAKE WORD "ROBOT" ---
    def toggle_wake_word(self):
        self.wake_word_activ = not self.wake_word_activ
        if self.wake_word_activ:
            self.btn_wake.config(text="● WAKE ON", bg="#98C379", fg="#1E222A")
            self.porneste_ascultare_wake_word()
        else:
            self.oprire_wake_event.set()
            self.btn_wake.config(text="○ WAKE OFF", bg="#4B5263", fg="white")
        self.adapteaza_buton_la_spatiu(self.btn_wake)

    def porneste_ascultare_wake_word(self):
        if not self.wake_word_activ or self.dnd_activ or self.stare == RobotState.LISTENING or self.inchidere_aplicatie or self.fir_wake_activ:
            return
        self.oprire_wake_event.clear()
        self.fir_wake_activ = True
        threading.Thread(target=self._fir_wake_word, name="WakeWordThread", daemon=True).start()

    def _fir_wake_word(self):
        try:
            while self.wake_word_activ and not self.dnd_activ and not self.oprire_wake_event.is_set() and not self.inchidere_aplicatie:
                if self.stare in (RobotState.LISTENING, RobotState.THINKING):
                    time.sleep(0.2)
                    continue
                detectat = asteapta_wake_word(self.oprire_wake_event)
                if detectat and not self.oprire_wake_event.is_set() and self.stare != RobotState.LISTENING:
                    self.fir_wake_activ = False
                    self.root.after(0, self.declanseaza_ascultare)
                    return
                if not self.oprire_wake_event.is_set():
                    time.sleep(0.25)
        finally:
            self.fir_wake_activ = False

    # --- STREAMING ÎN UI ---
    def afiseaza_mesaj(self, expeditor, mesaj):
        self.text_display.config(state=tk.NORMAL)
        self.text_display.insert(tk.END, f"{expeditor}: {mesaj}\n\n")
        self.text_display.see(tk.END)
        self.text_display.config(state=tk.DISABLED)

    def _incepe_mesaj_stream(self, expeditor):
        self.text_display.config(state=tk.NORMAL)
        self.text_display.insert(tk.END, f"{expeditor}: ")
        self.text_display.see(tk.END)
        self.text_display.config(state=tk.DISABLED)

    def _adauga_chunk_stream(self, bucata_text):
        self.text_display.config(state=tk.NORMAL)
        self.text_display.insert(tk.END, bucata_text)
        self.text_display.see(tk.END)
        self.text_display.config(state=tk.DISABLED)

    def _incheie_mesaj_stream(self):
        self.text_display.config(state=tk.NORMAL)
        self.text_display.insert(tk.END, "\n\n")
        self.text_display.see(tk.END)
        self.text_display.config(state=tk.DISABLED)

    # --- SALUTUL DINAMIC 100% AI ---
    def porneste_salut_initial(self):
        tid = self._nou_task()
        self._seteaza_stare_ui(RobotState.THINKING)
        threading.Thread(target=preincalzeste_microfon, name="PrewarmMic", daemon=True).start()
        threading.Thread(target=self.fir_salut_initial, args=(tid,), name="InitGreeting", daemon=True).start()

    def fir_salut_initial(self, tid):
        try:
            self.root.after(0, self._incepe_mesaj_stream, "Robot [SALUT]")

            def la_chunk(c):
                if self._este_task_valid(tid):
                    self.root.after(0, self._adauga_chunk_stream, c)

            rez = genereaza_salut_pornire(limba="ro", on_text_chunk=la_chunk)
            if not self._este_task_valid(tid):
                return
            self.root.after(0, self._incheie_mesaj_stream)

            text_salut = rez.get("mesaj", "")
            if text_salut and self._este_task_valid(tid) and not self.dnd_activ:
                self._seteaza_stare_ui(RobotState.SPEAKING)
                vorbeste(text_salut, limba="ro")
        except Exception as e:
            logger.error(f"[EROARE SALUT]: {e}")
        finally:
            if self._este_task_valid(tid):
                self._seteaza_stare_ui(RobotState.IDLE)
                self.root.after(0, self.porneste_ascultare_wake_word)

    # --- PUSH-TO-TALK MIC ---
    def _seteaza_status_input(self, text_status, culoare_text="#FFFFFF", culoare_bg="#282C34"):
        self.entry_input.delete(0, tk.END)
        self.entry_input.config(fg=culoare_text, bg=culoare_bg)
        self.entry_input.insert(0, text_status)

    def actualizeaza_stare_mic(self, faza):
        if faza == "pregatire":
            self.btn_mic.config(bg="#E5C07B", fg="#1E222A", text="WAIT")
            self.btn_send.config(bg="#4B5263", fg="#ABB2BF", text="PREGĂTESC MIC...")
            self._seteaza_status_input("Pregătesc microfonul...", "#E5C07B", "#282C34")
        elif faza == "asculta":
            self._seteaza_stare_ui(RobotState.LISTENING)
            self._seteaza_status_input("TE ASCULT! Vorbește acum (RO sau EN)...", "#FFFFFF", "#3B2328")
        elif faza == "procesare":
            self.btn_mic.config(bg="#E5C07B", fg="#1E222A", text="...")
            self.btn_send.config(bg="#E5C07B", fg="#1E222A", text="PROCESEZ VOCEA...")
            self._seteaza_status_input("Procesez cuvintele tale...", "#E5C07B", "#282C34")

    def declanseaza_ascultare(self):
        if self.stare == RobotState.LISTENING:
            return
        tid = self._nou_task()
        opreste_voce()
        self.oprire_wake_event.set()
        atenueaza_volum_temporar()

        if self.tastatura_activa:
            self.toggle_tastatura()

        self._seteaza_stare_ui(RobotState.LISTENING)
        self.actualizeaza_stare_mic("pregatire")
        threading.Thread(target=self.fir_executie_ascultare, args=(tid,), name="ListenThread", daemon=True).start()

    def fir_executie_ascultare(self, tid):
        text_recunoscut = asculta_voce(
            on_status=lambda faza: self.root.after(0, self.actualizeaza_stare_mic, faza) if self._este_task_valid(tid) else None
        )
        restabileste_volum_normal()

        if not self._este_task_valid(tid):
            return

        if not text_recunoscut and not self.dnd_activ:
            threading.Thread(target=vorbeste, args=("Nu am înțeles, repetă te rog.", "ro"), daemon=True).start()
        self.root.after(0, self.finalizare_ascultare, text_recunoscut, tid)

    def finalizare_ascultare(self, text, tid):
        if not self._este_task_valid(tid):
            return
        self.entry_input.delete(0, tk.END)
        self.entry_input.config(fg="white", bg="#282C34")
        self.btn_mic.config(bg="#C678DD", fg="white", text="🎤 MIC")

        if text:
            self.entry_input.insert(0, text)
            self.start_procesare(fortat=True)
        else:
            self._seteaza_stare_ui(RobotState.MUSIC if este_media_activa() else RobotState.IDLE)
            self.afiseaza_mesaj("Sistem", "Nu am înțeles, repetă te rog.")
            self.porneste_ascultare_wake_word()

    # --- TASTATURA VIRTUALĂ ---
    def construieste_tastatura(self):
        randuri = [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
            ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
            ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', '-'],
            ['z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '?'],
            ['SPACE', 'DEL', 'CLR']
        ]
        for rand in randuri:
            frame_rand = tk.Frame(self.frame_kb, bg="#1E222A")
            frame_rand.pack(fill="both", expand=True, pady=1)
            for cheie in rand:
                culoare_bg = "#E06C75" if cheie in ['DEL', 'CLR'] else "#3B4252"
                text_btn = cheie if len(cheie) > 1 else cheie.upper()
                btn = tk.Button(
                    frame_rand, text=text_btn, font=("Arial", 10, "bold"),
                    bg=culoare_bg, fg="white", relief="flat",
                    command=lambda c=cheie: self.apasa_tasta(c)
                )
                btn.pack(side="left", fill="both", expand=True, padx=1)

    def apasa_tasta(self, tasta):
        if self.stare == RobotState.LISTENING:
            return
        cursor_pos = self.entry_input.index(tk.INSERT)
        if tasta == 'DEL':
            if cursor_pos > 0:
                self.entry_input.delete(cursor_pos - 1)
        elif tasta == 'CLR':
            self.entry_input.delete(0, tk.END)
        elif tasta == 'SPACE':
            self.entry_input.insert(cursor_pos, " ")
        else:
            self.entry_input.insert(cursor_pos, tasta)
        self.entry_input.focus_force()

    def toggle_tastatura(self):
        if self.tastatura_activa:
            self.frame_kb.place_forget()
            self.btn_kb.config(bg="#4B5263")
            self.tastatura_activa = False
        else:
            self.frame_kb.place(relx=0.02, rely=0.12, relwidth=0.96, relheight=0.57)
            self.frame_kb.lift()
            self.btn_kb.config(bg="#98C379")
            self.tastatura_activa = True

    # --- PROCESARE COMANDĂ AI (P1: Video și Muzică pornesc DUPĂ TTS fără conflict ALSA) ---
    def start_procesare(self, fortat=False):
        if self.stare == RobotState.LISTENING and not fortat:
            return
        mesaj_utilizator = self.entry_input.get()
        if not mesaj_utilizator.strip():
            return

        if mesaj_utilizator.strip().lower() in ("șterge conversația", "sterge conversatia", "reset chat"):
            self.entry_input.delete(0, tk.END)
            self.curata_conversatia()
            return

        tid = self._nou_task()
        opreste_voce()
        self.oprire_wake_event.set()
        self.entry_input.delete(0, tk.END)
        self.afiseaza_mesaj("Tu", mesaj_utilizator)

        if self.tastatura_activa:
            self.toggle_tastatura()

        self._seteaza_stare_ui(RobotState.THINKING)
        threading.Thread(target=self.obtine_raspuns, args=(mesaj_utilizator, tid), name="AIWorker", daemon=True).start()

    def obtine_raspuns(self, mesaj, tid):
        try:
            restabileste_volum_normal()
            antet_afisat = False

            def la_chunk(c):
                nonlocal antet_afisat
                if not self._este_task_valid(tid):
                    return
                if not antet_afisat:
                    antet_afisat = True
                    self.root.after(0, self._incepe_mesaj_stream, "Robot")
                self.root.after(0, self._adauga_chunk_stream, c)

            rez = proceseaza_comanda_ai(
                mesaj,
                limba="ro",
                on_text_chunk=la_chunk
            )
            if not self._este_task_valid(tid):
                return
            if antet_afisat:
                self.root.after(0, self._incheie_mesaj_stream)

            actiune = rez.get("actiune", "vorbeste_normal")
            date_ui = rez.get("date_ui")
            parametru = rez.get("parametru", "")

            if actiune == "arata_status" and isinstance(date_ui, dict):
                self.root.after(0, self.afiseaza_overlay_status, date_ui)
            elif actiune == "cauta_wikipedia" and isinstance(date_ui, dict):
                self.root.after(0, self.afiseaza_overlay_wikipedia, date_ui)
            elif actiune == "reda_youtube" and isinstance(date_ui, list):
                self.root.after(0, self.afiseaza_overlay_youtube_lista, parametru, date_ui)
            elif actiune == "selecteaza_youtube" and isinstance(date_ui, dict):
                self.root.after(0, self.afiseaza_overlay_video_activ, date_ui, True)
            elif actiune == "reda_muzica" and isinstance(date_ui, dict):
                self.root.after(0, self.afiseaza_overlay_youtube_music, date_ui)
            elif actiune == "opreste_media":
                self.root.after(0, self.ascunde_overlay)

            text_final = rez.get("mesaj", "")
            if text_final and self._este_task_valid(tid) and not self.dnd_activ:
                self._seteaza_stare_ui(RobotState.SPEAKING)
                vorbeste(text_final, limba="ro")

            if not self._este_task_valid(tid):
                return

            if actiune == "reda_muzica" and isinstance(date_ui, dict):
                self._seteaza_stare_ui(RobotState.MUSIC)
                threading.Thread(
                    target=deschide_overlay_youtube,
                    args=(date_ui["video_id"], True, None, None, self._set_music_status),
                    daemon=True
                ).start()
            elif actiune == "selecteaza_youtube" and isinstance(date_ui, dict):
                self._seteaza_stare_ui(RobotState.VIDEO)
                self.root.after(0, self._lanseaza_stream_video_in_surface, date_ui)

        except Exception as e:
            logger.error(f"Eroare în obtine_raspuns: {e}")
            self.root.after(0, lambda: self.afiseaza_mesaj("Eroare Sistem", f"Eroare: {e}"))
        finally:
            if self._este_task_valid(tid):
                if self.stare not in (RobotState.MUSIC, RobotState.VIDEO):
                    st_fin = RobotState.MUSIC if este_media_activa() else RobotState.IDLE
                    self._seteaza_stare_ui(st_fin)
                self.root.after(0, self.porneste_ascultare_wake_word)


if __name__ == "__main__":
    app = tk.Tk()
    ui = RobotCompanionUI(app)

    def _sig_handler(sig, frame):
        ui.inchide_curat()

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)
    app.mainloop()