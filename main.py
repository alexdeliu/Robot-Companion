import io
import time
import signal
import urllib.request
from datetime import datetime
import tkinter as tk
from tkinter import scrolledtext
import threading

from config import CFG
from system_health import logger, MonitorSanatatePi, citeste_stare_hardware
from brain.ai_brain import (
    proceseaza_comanda_ai,
    genereaza_salut_pornire,
    reseteaza_memorie_ai
)
from brain.abilities.timers import seteaza_callback_alarma, opreste_toate_timerele
from ears.listen import asculta_voce, preincalzeste_microfon, _obtine_index_microfon
from ears.wake_word import asteapta_wake_word, obtine_strategie_activa
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
    este_media_activa
)


class RobotState:
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    MUSIC = "MUSIC"
    VIDEO = "VIDEO"
    ERROR = "ERROR"


FETE_IDLE = ["( ^ _ ^ )", "( o _ o )", "( - _ - )", "( ^ o ^ )"]


class RobotCompanionUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Robot Companion")

        # Sursă unică de adevăr pentru starea aplicației și anularea task-urilor concurente
        self._state_lock = threading.RLock()
        self.stare = RobotState.IDLE
        self._task_id = 0
        self._last_click_ts = {}

        self.wake_word_activ = bool(CFG["wake_word"].get("enabled_by_default", True))
        self.oprire_wake_event = threading.Event()
        self.fir_wake_activ = False
        self.inchidere_aplicatie = False
        self._img_referinta_ui = None
        self._ultimul_cautare_yt = ""
        self._ultimele_rezultate_yt = []
        self._idx_fata = 0

        self.monitor_sanatate = MonitorSanatatePi(interval_sec=25)
        self.monitor_sanatate.start()
        seteaza_callback_alarma(self._declanseaza_alarma_timer)

        seteaza_volum_sistem(int(CFG["audio_out"].get("volum_normal", 95)), salveaza_ca_normal=True)

        # --- KIOSK MODE PE DISPLAY SPI ---
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.lift()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_width}x{screen_height}+0+0")
        self.root.configure(bg="#1E222A")

        # --- BARA DE SUS (Wake Word + Stop Media + Curăță Chat + Status Sistem + Ceas + Ieșire) ---
        txt_w = "WAKE: 'ROBOT' [ON]" if self.wake_word_activ else "WAKE: 'ROBOT' [OFF]"
        bg_w = "#98C379" if self.wake_word_activ else "#4B5263"
        self.btn_wake = tk.Button(
            self.root, text=txt_w, font=("Arial", 9, "bold"),
            bg=bg_w, fg="#1E222A", command=lambda: self._debounce("wake", self.toggle_wake_word), relief="flat"
        )
        self.btn_wake.place(relx=0.03, rely=0.02, relwidth=0.25, relheight=0.08)

        self.btn_stop_media = tk.Button(
            self.root, text="STOP", font=("Arial", 9, "bold"),
            bg="#3B4252", fg="white", command=lambda: self._debounce("stop", self.opreste_tot_media), relief="flat"
        )
        self.btn_stop_media.place(relx=0.29, rely=0.02, relwidth=0.13, relheight=0.08)

        self.btn_clear = tk.Button(
            self.root, text="CLR", font=("Arial", 9, "bold"),
            bg="#3B4252", fg="#ABB2BF", command=lambda: self._debounce("clr", self.curata_conversatia), relief="flat"
        )
        self.btn_clear.place(relx=0.43, rely=0.02, relwidth=0.11, relheight=0.08)

        self.btn_status = tk.Button(
            self.root, text="( ^ _ ^ ) STATUS", font=("Arial", 9, "bold"),
            bg="#282C34", fg="#E5C07B", command=lambda: self._debounce("status", self.afiseaza_overlay_status), relief="flat"
        )
        self.btn_status.place(relx=0.55, rely=0.02, relwidth=0.18, relheight=0.08)

        self.lbl_ceas = tk.Label(
            self.root, text="00:00", font=("Arial", 11, "bold"),
            bg="#282C34", fg="#61AFEF"
        )
        self.lbl_ceas.place(relx=0.74, rely=0.02, relwidth=0.14, relheight=0.08)

        self.btn_exit = tk.Button(
            self.root, text="X", font=("Arial", 12, "bold"),
            bg="#E06C75", fg="white", command=self.inchide_curat, relief="flat"
        )
        self.btn_exit.place(relx=0.89, rely=0.02, relwidth=0.08, relheight=0.08)

        # --- ZONA DE AFIȘARE TEXT (CHAT) ---
        self.text_display = scrolledtext.ScrolledText(
            self.root, font=("Arial", 12), bg="#1E222A", fg="#ABB2BF",
            wrap=tk.WORD, relief="flat", state=tk.DISABLED
        )
        self.text_display.place(relx=0.03, rely=0.12, relwidth=0.94, relheight=0.58)
        self.afiseaza_mesaj("Sistem", "Sisteme online. Îmi trezesc creierul AI...")

        # --- CONTAINER OVERLAY-URI ---
        self.frame_overlay = tk.Frame(
            self.root, bg="#21252B",
            highlightbackground="#61AFEF", highlightthickness=2
        )

        # --- ZONA PENTRU INPUT ---
        self.entry_input = tk.Entry(
            self.root, font=("Arial", 14, "bold"),
            bg="#282C34", fg="white", insertbackground="white", relief="flat"
        )
        self.entry_input.place(relx=0.03, rely=0.72, relwidth=0.94, relheight=0.12)
        self.entry_input.bind("<Return>", lambda event: self.start_procesare())

        # --- BUTOANE JOS (KB, MIC PUSH-TO-TALK, TRIMITE) ---
        self.tastatura_activa = False
        self.btn_kb = tk.Button(
            self.root, text="KB", font=("Arial", 14, "bold"),
            bg="#4B5263", fg="white", activebackground="#4B5263", activeforeground="white",
            command=lambda: self._debounce("kb", self.toggle_tastatura), relief="flat"
        )
        self.btn_kb.place(relx=0.03, rely=0.86, relwidth=0.15, relheight=0.12)

        self.btn_mic = tk.Button(
            self.root, text="MIC", font=("Arial", 14, "bold"),
            bg="#C678DD", fg="white", activebackground="#C678DD", activeforeground="white",
            command=lambda: self._debounce("mic", self.declanseaza_ascultare), relief="flat"
        )
        self.btn_mic.place(relx=0.20, rely=0.86, relwidth=0.17, relheight=0.12)

        self.btn_send = tk.Button(
            self.root, text="TRIMITE", font=("Arial", 12, "bold"),
            bg="#61AFEF", fg="#1E222A", activebackground="#61AFEF", activeforeground="#1E222A",
            command=lambda: self._debounce("send", self.start_procesare), relief="flat"
        )
        self.btn_send.place(relx=0.39, rely=0.86, relwidth=0.58, relheight=0.12)

        self.frame_kb = tk.Frame(self.root, bg="#1E222A")
        self.construieste_tastatura()

        self._actualizeaza_ceas()
        self.entry_input.focus_force()
        self.root.after(120, self.porneste_salut_initial)

    # --- DEBOUNCE & MANAGEMENTUL STĂRII (P3) ---
    def _debounce(self, cheie, functie):
        acum = time.monotonic()
        prag = float(CFG["ui"].get("debounce_ms", 250)) / 1000.0
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
            if stare_noua == RobotState.IDLE:
                self.btn_send.config(text="TRIMITE", bg="#61AFEF", fg="#1E222A")
                self.btn_mic.config(text="MIC", bg="#C678DD", fg="white")
            elif stare_noua == RobotState.LISTENING:
                self.btn_mic.config(bg="#E06C75", fg="white", text="REC")
                self.btn_send.config(bg="#E06C75", fg="white", text="VORBEȘTE ACUM!")
            elif stare_noua == RobotState.THINKING:
                self.btn_send.config(text="GÂNDESC...", bg="#E5C07B", fg="#1E222A")
                self.btn_mic.config(bg="#C678DD", fg="white", text="MIC")
            elif stare_noua == RobotState.SPEAKING:
                self.btn_send.config(text="VORBESC...", bg="#98C379", fg="#1E222A")
                self.btn_mic.config(bg="#C678DD", fg="white", text="MIC")
            elif stare_noua in (RobotState.MUSIC, RobotState.VIDEO):
                self.btn_send.config(text="TRIMITE", bg="#61AFEF", fg="#1E222A")
                self.btn_mic.config(text="MIC", bg="#C678DD", fg="white")

        self.root.after(0, _update)

    def _actualizeaza_ceas(self):
        if self.inchidere_aplicatie:
            return
        self.lbl_ceas.config(text=datetime.now().strftime("%H:%M"))
        # Animație ușoară fără cost CPU în bara de sus când robotul este în IDLE
        if self.stare == RobotState.IDLE:
            self._idx_fata = (self._idx_fata + 1) % len(FETE_IDLE)
            st_hw = self.monitor_sanatate.ultima_stare
            temp_txt = f"{int(st_hw['temp_c'])}°C" if st_hw["temp_c"] > 0 else "OK"
            self.btn_status.config(text=f"{FETE_IDLE[self._idx_fata]} {temp_txt}")
        self.root.after(int(CFG["ui"].get("clock_refresh_ms", 10000)), self._actualizeaza_ceas)

    def _declanseaza_alarma_timer(self, mesaj_alarma):
        def _afis():
            self.afiseaza_mesaj("ALARMĂ / TIMER", mesaj_alarma)
        self.root.after(0, _afis)
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
        except Exception:
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
        except Exception:
            pass

    # --- OVERLAY 0: PAGINĂ STATUS SISTEM (P7) ---
    def afiseaza_overlay_status(self, st_preluat=None):
        self.ascunde_overlay()
        for w in self.frame_overlay.winfo_children():
            w.destroy()

        st = st_preluat or citeste_stare_hardware()
        bara = tk.Frame(self.frame_overlay, bg="#282C34")
        bara.pack(fill="x", padx=6, pady=4)

        tk.Label(
            bara, text="DIAGNOSTIC & STATUS HARDWARE (RASPBERRY PI)",
            font=("Arial", 11, "bold"), bg="#282C34", fg="#E5C07B"
        ).pack(side="left", padx=6, pady=4)

        tk.Button(
            bara, text="ÎNCHIDE", font=("Arial", 10, "bold"),
            bg="#E06C75", fg="white", relief="flat", command=self.ascunde_overlay
        ).pack(side="right", padx=4, pady=2)

        corp = tk.Frame(self.frame_overlay, bg="#21252B")
        corp.pack(fill="both", expand=True, padx=14, pady=8)

        mic_idx = _obtine_index_microfon()
        strat_w = obtine_strategie_activa()
        alim_txt = "UNDERVOLTAGE DETECTAT!" if st["undervoltage_acum"] else f"Normală ({st['throttled_hex']})"
        av_txt = ", ".join(st["avertismente"]) if st["avertismente"] else "Niciun avertisment activ."

        linii = [
            f"• Stare Curentă Robot: {self.stare}",
            f"• Temperatură Procesor (SoC): {st['temp_c']} °C",
            f"• Memorie RAM Liberă: {st['ram_avail_mb']} MB / {st['ram_total_mb']} MB ({st['ram_procent']}% utilizat)",
            f"• Alimentare 5V (vcgencmd): {alim_txt}",
            f"• Microfon Selectat: Port Index #{mic_idx} | Wake Word: {strat_w} ({'ON' if self.wake_word_activ else 'OFF'})",
            f"• Avertismente Sănătate: {av_txt}"
        ]
        for l_txt in linii:
            tk.Label(
                corp, text=l_txt, font=("Arial", 11, "bold"),
                bg="#21252B", fg="#ABB2BF", anchor="w"
            ).pack(fill="x", pady=2)

        self.frame_overlay.place(relx=0.03, rely=0.12, relwidth=0.94, relheight=0.58)
        self.frame_overlay.lift()

    # --- OVERLAY 1: CARD VIZUAL WIKIPEDIA ---
    def afiseaza_overlay_wikipedia(self, info_wiki):
        self.ascunde_overlay()
        for w in self.frame_overlay.winfo_children():
            w.destroy()

        bara_titlu = tk.Frame(self.frame_overlay, bg="#282C34")
        bara_titlu.pack(fill="x", padx=6, pady=4)

        partea = info_wiki.get("partea_curenta", 1)
        total = info_wiki.get("total_parti", 1)
        tk.Label(
            bara_titlu,
            text=f"WIKIPEDIA: {info_wiki.get('titlu', '')} (Partea {partea}/{total})",
            font=("Arial", 11, "bold"), bg="#282C34", fg="#61AFEF", anchor="w"
        ).pack(side="left", padx=6, pady=4)

        tk.Button(
            bara_titlu, text="ÎNCHIDE", font=("Arial", 10, "bold"),
            bg="#E06C75", fg="white", relief="flat", command=self.opreste_tot_media
        ).pack(side="right", padx=4, pady=2)

        if partea < total:
            tk.Button(
                bara_titlu, text="SPUNE MAI MULT >>", font=("Arial", 10, "bold"),
                bg="#98C379", fg="#1E222A", relief="flat",
                command=lambda: self._trimite_comanda_rapida("Spune-mi mai mult")
            ).pack(side="right", padx=4, pady=2)

        corp_wiki = tk.Frame(self.frame_overlay, bg="#21252B")
        corp_wiki.pack(fill="both", expand=True, padx=10, pady=6)

        txt_wiki = scrolledtext.ScrolledText(
            corp_wiki, font=("Arial", 12), bg="#21252B", fg="#ABB2BF",
            wrap=tk.WORD, relief="flat"
        )
        txt_wiki.pack(side="right", fill="both", expand=True)
        txt_wiki.insert(tk.END, info_wiki.get("rezumat", ""))
        txt_wiki.config(state=tk.DISABLED)

        self.frame_overlay.place(relx=0.03, rely=0.12, relwidth=0.94, relheight=0.58)
        self.frame_overlay.lift()

        # Încărcăm imaginea în thread secundar ca să nu blocheze UI-ul pe SPI!
        url_img = info_wiki.get("imagine", "")
        if url_img:
            def _load_img():
                img_tk = self._incarca_imagine_url(url_img, latime=100, inaltime=100)
                if img_tk and not self.inchidere_aplicatie:
                    def _pin():
                        if corp_wiki.winfo_exists():
                            self._img_referinta_ui = img_tk
                            tk.Label(corp_wiki, image=img_tk, bg="#21252B").pack(side="left", padx=(2, 8), anchor="n")
                    self.root.after(0, _pin)
            threading.Thread(target=_load_img, daemon=True).start()

    # --- OVERLAY 2: SELECTOR 5 REZULTATE YOUTUBE VIDEO ---
    def afiseaza_overlay_youtube_lista(self, cautare, rezultate):
        self._ultimul_cautare_yt = cautare
        self._ultimele_rezultate_yt = rezultate
        self.ascunde_overlay()
        for w in self.frame_overlay.winfo_children():
            w.destroy()

        bara_titlu = tk.Frame(self.frame_overlay, bg="#282C34")
        bara_titlu.pack(fill="x", padx=6, pady=4)

        tk.Label(
            bara_titlu,
            text=f"YOUTUBE: {cautare.upper()[:28]} (Spune 'Primul'... sau apasă)",
            font=("Arial", 10, "bold"), bg="#282C34", fg="#E06C75", anchor="w"
        ).pack(side="left", padx=6, pady=4)

        tk.Button(
            bara_titlu, text="ÎNCHIDE", font=("Arial", 10, "bold"),
            bg="#E06C75", fg="white", relief="flat", command=self.opreste_tot_media
        ).pack(side="right", padx=4, pady=2)

        container = tk.Frame(self.frame_overlay, bg="#21252B")
        container.pack(fill="both", expand=True, padx=8, pady=4)

        for item in rezultate[:5]:
            nr = item["numar"]
            rand = tk.Frame(container, bg="#282C34")
            rand.pack(fill="x", pady=2)

            tk.Button(
                rand, text=f"#{nr} PLAY", font=("Arial", 10, "bold"),
                bg="#E06C75", fg="white", relief="flat", width=8,
                command=lambda n=nr: self.porneste_video_selectat(n)
            ).pack(side="left", padx=4, pady=2)

            titlu_scurt = item["titlu"][:55] + ("..." if len(item["titlu"]) > 55 else "")
            tk.Label(
                rand, text=f"{titlu_scurt} [{item.get('durata', '')}]",
                font=("Arial", 10, "bold"), bg="#282C34", fg="white", anchor="w"
            ).pack(side="left", fill="x", expand=True, padx=6)

        self.frame_overlay.place(relx=0.03, rely=0.12, relwidth=0.94, relheight=0.58)
        self.frame_overlay.lift()

    # --- OVERLAY 2B: PLAYER VIDEO ÎNCORPORAT CU SEEK ±10s ȘI PAUZĂ IPC ---
    def afiseaza_overlay_video_activ(self, piesa):
        self._seteaza_stare_ui(RobotState.VIDEO)
        self.ascunde_overlay()
        for w in self.frame_overlay.winfo_children():
            w.destroy()

        bara_sus = tk.Frame(self.frame_overlay, bg="#181A1F")
        bara_sus.pack(fill="x", padx=4, pady=2)

        titlu_scurt = piesa.get("titlu", "Video")[:28]
        tk.Label(
            bara_sus, text=f"VIDEO: {titlu_scurt}",
            font=("Arial", 9, "bold"), bg="#181A1F", fg="#61AFEF"
        ).pack(side="left", padx=4, pady=2)

        tk.Button(
            bara_sus, text="STOP", font=("Arial", 9, "bold"),
            bg="#E06C75", fg="white", relief="flat", command=self.opreste_tot_media
        ).pack(side="right", padx=2, pady=2)

        tk.Button(
            bara_sus, text="+10s", font=("Arial", 9, "bold"),
            bg="#3B4252", fg="white", relief="flat", command=lambda: deruleaza_media(10)
        ).pack(side="right", padx=2, pady=2)

        tk.Button(
            bara_sus, text="PAUZĂ", font=("Arial", 9, "bold"),
            bg="#E5C07B", fg="#1E222A", relief="flat", command=toggle_pauza_media
        ).pack(side="right", padx=2, pady=2)

        tk.Button(
            bara_sus, text="-10s", font=("Arial", 9, "bold"),
            bg="#3B4252", fg="white", relief="flat", command=lambda: deruleaza_media(-10)
        ).pack(side="right", padx=2, pady=2)

        tk.Button(
            bara_sus, text="AUDIO", font=("Arial", 9, "bold"),
            bg="#C678DD", fg="white", relief="flat",
            command=lambda: self._comuta_pe_muzica(piesa)
        ).pack(side="right", padx=2, pady=2)

        if self._ultimele_rezultate_yt:
            tk.Button(
                bara_sus, text="<< LISTĂ", font=("Arial", 9, "bold"),
                bg="#4B5263", fg="white", relief="flat",
                command=self._inapoi_la_lista_yt
            ).pack(side="right", padx=2, pady=2)

        self.video_surface = tk.Frame(self.frame_overlay, bg="black")
        self.video_surface.pack(fill="both", expand=True, padx=4, pady=4)

        self.frame_overlay.place(relx=0.03, rely=0.12, relwidth=0.94, relheight=0.58)
        self.frame_overlay.lift()
        self.root.update_idletasks()

        wid = self.video_surface.winfo_id()
        threading.Thread(
            target=deschide_overlay_youtube,
            args=(piesa["video_id"], False, wid),
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
            args=(piesa["video_id"], True, None),
            daemon=True
        ).start()

    # --- OVERLAY 3: YOUTUBE MUSIC PLAYER ---
    def afiseaza_overlay_youtube_music(self, piesa):
        self._seteaza_stare_ui(RobotState.MUSIC)
        self.ascunde_overlay()
        for w in self.frame_overlay.winfo_children():
            w.destroy()

        bara_sus = tk.Frame(self.frame_overlay, bg="#181A1F")
        bara_sus.pack(fill="x", padx=6, pady=4)

        tk.Label(
            bara_sus, text="YOUTUBE MUSIC PLAYER",
            font=("Arial", 10, "bold"), bg="#181A1F", fg="#C678DD"
        ).pack(side="left", padx=6, pady=4)

        tk.Button(
            bara_sus, text="OPREȘTE", font=("Arial", 9, "bold"),
            bg="#E06C75", fg="white", relief="flat", command=self.opreste_tot_media
        ).pack(side="right", padx=4)

        tk.Button(
            bara_sus, text="COMUTĂ VIDEO", font=("Arial", 9, "bold"),
            bg="#61AFEF", fg="#1E222A", relief="flat",
            command=lambda: self.afiseaza_overlay_video_activ(piesa)
        ).pack(side="right", padx=4)

        corp = tk.Frame(self.frame_overlay, bg="#21252B")
        corp.pack(fill="both", expand=True, padx=12, pady=6)

        info_zona = tk.Frame(corp, bg="#21252B")
        info_zona.pack(fill="x", pady=4)

        text_zona = tk.Frame(info_zona, bg="#21252B")
        text_zona.pack(side="right", fill="both", expand=True)

        self.lbl_music_title = tk.Label(
            text_zona, text=piesa.get("titlu", "Melodie"),
            font=("Arial", 12, "bold"), bg="#21252B", fg="white",
            wraplength=int(self.root.winfo_screenwidth() * 0.62), justify="left", anchor="w"
        )
        self.lbl_music_title.pack(fill="x", pady=(2, 4))

        self.lbl_music_artist = tk.Label(
            text_zona, text=f"Canal: {piesa.get('canal', 'YouTube Music')} • {piesa.get('durata', 'Audio')}",
            font=("Arial", 10, "bold"), bg="#21252B", fg="#98C379", anchor="w"
        )
        self.lbl_music_artist.pack(fill="x")

        controale = tk.Frame(corp, bg="#21252B")
        controale.pack(pady=8)

        tk.Button(
            controale, text="VOL -", font=("Arial", 10, "bold"),
            bg="#3B4252", fg="white", relief="flat", width=6,
            command=lambda: schimba_volum_relativ(-12)
        ).pack(side="left", padx=3, ipady=5)

        tk.Button(
            controale, text="<< PREV", font=("Arial", 10, "bold"),
            bg="#4B5263", fg="white", relief="flat", width=7,
            command=self._muzica_prev
        ).pack(side="left", padx=3, ipady=5)

        self.btn_pauza_muzica = tk.Button(
            controale, text="PAUZĂ", font=("Arial", 10, "bold"),
            bg="#E5C07B", fg="#1E222A", relief="flat", width=7,
            command=self._toggle_pauza_ui
        )
        self.btn_pauza_muzica.pack(side="left", padx=3, ipady=5)

        tk.Button(
            controale, text="STOP", font=("Arial", 10, "bold"),
            bg="#E06C75", fg="white", relief="flat", width=6,
            command=self.opreste_tot_media
        ).pack(side="left", padx=3, ipady=5)

        tk.Button(
            controale, text="NEXT >>", font=("Arial", 10, "bold"),
            bg="#4B5263", fg="white", relief="flat", width=7,
            command=self._muzica_next
        ).pack(side="left", padx=3, ipady=5)

        tk.Button(
            controale, text="VOL +", font=("Arial", 10, "bold"),
            bg="#3B4252", fg="white", relief="flat", width=6,
            command=lambda: schimba_volum_relativ(12)
        ).pack(side="left", padx=3, ipady=5)

        self.frame_overlay.place(relx=0.03, rely=0.12, relwidth=0.94, relheight=0.58)
        self.frame_overlay.lift()

        url_min = piesa.get("miniatura", "")
        if url_min:
            def _load_cov():
                img_cov = self._incarca_imagine_url(url_min, latime=100, inaltime=75)
                if img_cov and not self.inchidere_aplicatie:
                    def _pin():
                        if info_zona.winfo_exists():
                            self._img_referinta_ui = img_cov
                            tk.Label(info_zona, image=img_cov, bg="#21252B").pack(side="left", padx=(4, 10))
                    self.root.after(0, _pin)
            threading.Thread(target=_load_cov, daemon=True).start()

    def _toggle_pauza_ui(self):
        in_pauza = toggle_pauza_media()
        if hasattr(self, "btn_pauza_muzica") and self.btn_pauza_muzica.winfo_exists():
            if in_pauza:
                self.btn_pauza_muzica.config(text="PLAY", bg="#98C379", fg="#1E222A")
            else:
                self.btn_pauza_muzica.config(text="PAUZĂ", bg="#E5C07B", fg="#1E222A")

    def _muzica_next(self):
        def _bg():
            ales = piesa_urmatoare()
            if ales and not self.inchidere_aplicatie:
                self.root.after(0, self.afiseaza_overlay_youtube_music, ales)
        threading.Thread(target=_bg, daemon=True).start()

    def _muzica_prev(self):
        def _bg():
            ales = piesa_anterioara()
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
        self.afiseaza_overlay_video_activ(ales)

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
            self.btn_wake.config(text="WAKE: 'ROBOT' [ON]", bg="#98C379", fg="#1E222A")
            self.porneste_ascultare_wake_word()
        else:
            self.oprire_wake_event.set()
            self.btn_wake.config(text="WAKE: 'ROBOT' [OFF]", bg="#4B5263", fg="white")

    def porneste_ascultare_wake_word(self):
        if not self.wake_word_activ or self.stare == RobotState.LISTENING or self.inchidere_aplicatie or self.fir_wake_activ:
            return
        self.oprire_wake_event.clear()
        self.fir_wake_activ = True
        threading.Thread(target=self._fir_wake_word, name="WakeWordThread", daemon=True).start()

    def _fir_wake_word(self):
        try:
            while self.wake_word_activ and not self.oprire_wake_event.is_set() and not self.inchidere_aplicatie:
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
            if text_salut and self._este_task_valid(tid):
                self._seteaza_stare_ui(RobotState.SPEAKING)
                vorbeste(text_salut, limba="ro")
        except Exception as e:
            logger.error(f"[EROARE SALUT]: {e}")
        finally:
            if self._este_task_valid(tid):
                self._seteaza_stare_ui(RobotState.IDLE)
                self.root.after(0, self.porneste_ascultare_wake_word)

    # --- PUSH-TO-TALK MIC (FUNCȚIONEAZĂ ÎN ORICE STARE - BARGE-IN GARANTAT) ---
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
        # Dacă este deja în ascultare, ignorăm dubla apăsare
        if self.stare == RobotState.LISTENING:
            return
        # Barge-in: anulăm imediat orice vorbire sau gândire anterioară!
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

        if not text_recunoscut:
            threading.Thread(target=vorbeste, args=("Nu am înțeles, repetă te rog.", "ro"), daemon=True).start()
        self.root.after(0, self.finalizare_ascultare, text_recunoscut, tid)

    def finalizare_ascultare(self, text, tid):
        if not self._este_task_valid(tid):
            return
        self.entry_input.delete(0, tk.END)
        self.entry_input.config(fg="white", bg="#282C34")
        self.btn_mic.config(bg="#C678DD", fg="white", text="MIC")

        if text:
            self.entry_input.insert(0, text)
            self.start_procesare(fortat=True)
        else:
            self._seteaza_stare_ui(RobotState.MUSIC if este_media_activa() else RobotState.IDLE)
            self.afiseaza_mesaj("Sistem", "Nu am înțeles, repetă te rog.")
            self.porneste_ascultare_wake_word()

    # --- TASTATURA VIRTUALĂ (FUNCȚIONEAZĂ MEREU) ---
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
            self.frame_kb.place(relx=0.03, rely=0.12, relwidth=0.94, relheight=0.58)
            self.frame_kb.lift()
            self.btn_kb.config(bg="#98C379")
            self.tastatura_activa = True

    # --- PROCESARE COMANDĂ AI ---
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
                self.root.after(0, self.afiseaza_overlay_video_activ, date_ui)
            elif actiune == "reda_muzica" and isinstance(date_ui, dict):
                self.root.after(0, self.afiseaza_overlay_youtube_music, date_ui)
            elif actiune == "opreste_media":
                self.root.after(0, self.ascunde_overlay)

            text_final = rez.get("mesaj", "")
            if text_final and self._este_task_valid(tid):
                self._seteaza_stare_ui(RobotState.SPEAKING)
                vorbeste(text_final, limba="ro")

            if actiune == "reda_muzica" and isinstance(date_ui, dict) and self._este_task_valid(tid):
                self._seteaza_stare_ui(RobotState.MUSIC)
                threading.Thread(
                    target=deschide_overlay_youtube,
                    args=(date_ui["video_id"], True, None),
                    daemon=True
                ).start()

        except Exception as e:
            logger.error(f"Eroare în obtine_raspuns: {e}")
            self.root.after(0, lambda: self.afiseaza_mesaj("Eroare Sistem", f"Eroare: {e}"))
        finally:
            if self._este_task_valid(tid):
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