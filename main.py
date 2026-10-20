import time
from datetime import datetime
import tkinter as tk
from tkinter import scrolledtext
import threading

from brain.ai_brain import (
    proceseaza_comanda_ai,
    genereaza_salut_pornire,
    reseteaza_memorie_ai
)
from ears.listen import asculta_voce, preincalzeste_microfon
from ears.wake_word import asteapta_wake_word
from voice.speak import vorbeste, opreste_voce
from brain.abilities.youtube_player import (
    reda_rezultat_dupa_numar,
    deschide_overlay_youtube,
    inchide_overlay_youtube,
    piesa_urmatoare,
    piesa_anterioara,
    seteaza_volum_sistem,
    schimba_volum_relativ
)


class RobotCompanionUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Robot Companion")

        self.ocupat = False
        self.wake_word_activ = True
        self.oprire_wake_event = threading.Event()
        self.inchidere_aplicatie = False

        # --- SECRETUL PENTRU KIOSK MODE PERFECT ---
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.lift()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_width}x{screen_height}+0+0")
        self.root.configure(bg="#1E222A")

        # --- BARA DE SUS (Wake Word + Stop Media + Curăță Chat + Ceas Live + Ieșire) ---
        self.btn_wake = tk.Button(
            self.root, text="WAKE: 'ROBOT' [ON]", font=("Arial", 10, "bold"),
            bg="#98C379", fg="#1E222A", command=self.toggle_wake_word, relief="flat"
        )
        self.btn_wake.place(relx=0.05, rely=0.02, relwidth=0.28, relheight=0.08)

        self.btn_stop_media = tk.Button(
            self.root, text="STOP MEDIA", font=("Arial", 10, "bold"),
            bg="#3B4252", fg="white", command=self.opreste_tot_media, relief="flat"
        )
        self.btn_stop_media.place(relx=0.34, rely=0.02, relwidth=0.18, relheight=0.08)

        self.btn_clear = tk.Button(
            self.root, text="CLR CHAT", font=("Arial", 10, "bold"),
            bg="#3B4252", fg="#ABB2BF", command=self.curata_conversatia, relief="flat"
        )
        self.btn_clear.place(relx=0.53, rely=0.02, relwidth=0.15, relheight=0.08)

        self.lbl_ceas = tk.Label(
            self.root, text="00:00", font=("Arial", 12, "bold"),
            bg="#282C34", fg="#61AFEF"
        )
        self.lbl_ceas.place(relx=0.69, rely=0.02, relwidth=0.17, relheight=0.08)
        self._actualizeaza_ceas()

        self.btn_exit = tk.Button(
            self.root, text="X", font=("Arial", 12, "bold"),
            bg="#E06C75", fg="white", command=self.inchide_curat, relief="flat"
        )
        self.btn_exit.place(relx=0.88, rely=0.02, relwidth=0.07, relheight=0.08)

        # --- ZONA DE AFIȘARE TEXT (CHAT) ---
        self.text_display = scrolledtext.ScrolledText(
            self.root, font=("Arial", 12), bg="#1E222A", fg="#ABB2BF",
            wrap=tk.WORD, relief="flat", state=tk.DISABLED
        )
        self.text_display.place(relx=0.05, rely=0.12, relwidth=0.9, relheight=0.58)
        self.afiseaza_mesaj("Sistem", "Sisteme online. Îmi trezesc creierul AI...")

        # --- OVERLAY-URI PENTRU ABILITĂȚI (Wikipedia, YouTube Video, YouTube Music) ---
        self.frame_overlay = tk.Frame(
            self.root, bg="#21252B",
            highlightbackground="#61AFEF", highlightthickness=2
        )

        # --- ZONA PENTRU INPUT ---
        self.entry_input = tk.Entry(
            self.root, font=("Arial", 14, "bold"),
            bg="#282C34", fg="white", insertbackground="white", relief="flat"
        )
        self.entry_input.place(relx=0.05, rely=0.72, relwidth=0.9, relheight=0.12)
        self.entry_input.bind("<Return>", lambda event: self.start_procesare())

        # --- BUTOANE JOS (KB, MIC, TRIMITE) ---
        self.tastatura_activa = False
        self.btn_kb = tk.Button(
            self.root, text="KB", font=("Arial", 14, "bold"),
            bg="#4B5263", fg="white", activebackground="#4B5263", activeforeground="white",
            command=self.toggle_tastatura, relief="flat"
        )
        self.btn_kb.place(relx=0.05, rely=0.86, relwidth=0.15, relheight=0.12)

        self.btn_mic = tk.Button(
            self.root, text="MIC", font=("Arial", 14, "bold"),
            bg="#C678DD", fg="white", activebackground="#C678DD", activeforeground="white",
            command=self.declanseaza_ascultare, relief="flat"
        )
        self.btn_mic.place(relx=0.22, rely=0.86, relwidth=0.15, relheight=0.12)

        self.btn_send = tk.Button(
            self.root, text="TRIMITE", font=("Arial", 12, "bold"),
            bg="#61AFEF", fg="#1E222A", activebackground="#61AFEF", activeforeground="#1E222A",
            command=self.start_procesare, relief="flat"
        )
        self.btn_send.place(relx=0.39, rely=0.86, relwidth=0.56, relheight=0.12)

        self.frame_kb = tk.Frame(self.root, bg="#1E222A")
        self.construieste_tastatura()

        self.entry_input.focus_force()
        self.root.after(100, self.porneste_salut_initial)

    def _actualizeaza_ceas(self):
        if not self.inchidere_aplicatie:
            self.lbl_ceas.config(text=datetime.now().strftime("%H:%M"))
            self.root.after(15000, self._actualizeaza_ceas)

    def curata_conversatia(self):
        opreste_voce()
        reseteaza_memorie_ai()
        self.ascunde_overlay()
        self.text_display.config(state=tk.NORMAL)
        self.text_display.delete("1.0", tk.END)
        self.text_display.config(state=tk.DISABLED)
        self.afiseaza_mesaj("Sistem", "Conversația și memoria au fost resetate.")

    def inchide_curat(self):
        self.inchidere_aplicatie = True
        self.oprire_wake_event.set()
        opreste_voce()
        inchide_overlay_youtube()
        self.root.destroy()

    # --- OVERLAY 1: CARD VIZUAL WIKIPEDIA ---
    def afiseaza_overlay_wikipedia(self, info_wiki):
        self.ascunde_overlay()
        for w in self.frame_overlay.winfo_children():
            w.destroy()

        bara_titlu = tk.Frame(self.frame_overlay, bg="#282C34")
        bara_titlu.pack(fill="x", padx=6, pady=4)

        lbl_titlu = tk.Label(
            bara_titlu, text=f"WIKIPEDIA: {info_wiki.get('titlu', '')}",
            font=("Arial", 13, "bold"), bg="#282C34", fg="#61AFEF", anchor="w"
        )
        lbl_titlu.pack(side="left", padx=6, pady=4)

        btn_inchide = tk.Button(
            bara_titlu, text="ÎNCHIDE", font=("Arial", 10, "bold"),
            bg="#E06C75", fg="white", relief="flat", command=self.ascunde_overlay
        )
        btn_inchide.pack(side="right", padx=4, pady=2)

        btn_mai_mult = tk.Button(
            bara_titlu, text="SPUNE MAI MULT", font=("Arial", 10, "bold"),
            bg="#98C379", fg="#1E222A", relief="flat",
            command=lambda: self._trimite_comanda_rapida("Spune-mi mai mult")
        )
        btn_mai_mult.pack(side="right", padx=4, pady=2)

        txt_rezumat = tk.Label(
            self.frame_overlay, text=info_wiki.get("rezumat", ""),
            font=("Arial", 11), bg="#21252B", fg="#ABB2BF",
            wraplength=int(self.root.winfo_screenwidth() * 0.84), justify="left"
        )
        txt_rezumat.pack(fill="both", expand=True, padx=12, pady=8)

        self.frame_overlay.place(relx=0.05, rely=0.12, relwidth=0.9, relheight=0.58)
        self.frame_overlay.lift()

    # --- OVERLAY 2: SELECTOR 5 REZULTATE YOUTUBE VIDEO ---
    def afiseaza_overlay_youtube_lista(self, cautare, rezultate):
        self.ascunde_overlay()
        for w in self.frame_overlay.winfo_children():
            w.destroy()

        bara_titlu = tk.Frame(self.frame_overlay, bg="#282C34")
        bara_titlu.pack(fill="x", padx=6, pady=4)

        tk.Label(
            bara_titlu,
            text=f"YOUTUBE VIDEO: {cautare.upper()} (Spune 'Primul', 'Al doilea'... sau apasă)",
            font=("Arial", 11, "bold"), bg="#282C34", fg="#E06C75", anchor="w"
        ).pack(side="left", padx=6, pady=4)

        tk.Button(
            bara_titlu, text="ÎNCHIDE", font=("Arial", 10, "bold"),
            bg="#E06C75", fg="white", relief="flat", command=self.ascunde_overlay
        ).pack(side="right", padx=4, pady=2)

        container = tk.Frame(self.frame_overlay, bg="#21252B")
        container.pack(fill="both", expand=True, padx=8, pady=4)

        for item in rezultate[:5]:
            nr = item["numar"]
            rand = tk.Frame(container, bg="#282C34")
            rand.pack(fill="x", pady=2)

            btn_play = tk.Button(
                rand, text=f"#{nr} PLAY", font=("Arial", 10, "bold"),
                bg="#E06C75", fg="white", relief="flat", width=9,
                command=lambda n=nr: self.porneste_video_selectat(n)
            )
            btn_play.pack(side="left", padx=4, pady=3)

            titlu_scurt = item["titlu"][:65] + ("..." if len(item["titlu"]) > 65 else "")
            tk.Label(
                rand, text=f"{titlu_scurt}  [{item.get('canal', '')} • {item.get('durata', '')}]",
                font=("Arial", 10, "bold"), bg="#282C34", fg="white", anchor="w"
            ).pack(side="left", fill="x", expand=True, padx=6)

        self.frame_overlay.place(relx=0.05, rely=0.12, relwidth=0.9, relheight=0.58)
        self.frame_overlay.lift()

    # --- OVERLAY 3: YOUTUBE MUSIC PLAYER MINIMALIST ---
    def afiseaza_overlay_youtube_music(self, piesa):
        self.ascunde_overlay()
        for w in self.frame_overlay.winfo_children():
            w.destroy()

        bara_sus = tk.Frame(self.frame_overlay, bg="#181A1F")
        bara_sus.pack(fill="x", padx=6, pady=4)

        tk.Label(
            bara_sus, text="YOUTUBE MUSIC PLAYER",
            font=("Arial", 11, "bold"), bg="#181A1F", fg="#C678DD"
        ).pack(side="left", padx=8, pady=4)

        tk.Button(
            bara_sus, text="COMUTĂ VIDEO", font=("Arial", 9, "bold"),
            bg="#61AFEF", fg="#1E222A", relief="flat",
            command=lambda: deschide_overlay_youtube(piesa["video_id"], mod_muzica=False)
        ).pack(side="right", padx=4)

        tk.Button(
            bara_sus, text="OPREȘTE", font=("Arial", 9, "bold"),
            bg="#E06C75", fg="white", relief="flat", command=self.opreste_tot_media
        ).pack(side="right", padx=4)

        corp = tk.Frame(self.frame_overlay, bg="#21252B")
        corp.pack(fill="both", expand=True, padx=16, pady=10)

        self.lbl_music_title = tk.Label(
            corp, text=piesa.get("titlu", "Melodie"),
            font=("Arial", 14, "bold"), bg="#21252B", fg="white",
            wraplength=int(self.root.winfo_screenwidth() * 0.8), justify="center"
        )
        self.lbl_music_title.pack(pady=(12, 4))

        self.lbl_music_artist = tk.Label(
            corp, text=f"Artist / Canal: {piesa.get('canal', 'YouTube Music')}",
            font=("Arial", 11), bg="#21252B", fg="#98C379"
        )
        self.lbl_music_artist.pack(pady=(0, 14))

        controale = tk.Frame(corp, bg="#21252B")
        controale.pack(pady=6)

        tk.Button(
            controale, text="VOL -", font=("Arial", 11, "bold"),
            bg="#3B4252", fg="white", relief="flat", width=7,
            command=lambda: schimba_volum_relativ(-12)
        ).pack(side="left", padx=5, ipady=6)

        tk.Button(
            controale, text="<< PREV", font=("Arial", 11, "bold"),
            bg="#4B5263", fg="white", relief="flat", width=8,
            command=self._muzica_prev
        ).pack(side="left", padx=5, ipady=6)

        tk.Button(
            controale, text="STOP", font=("Arial", 11, "bold"),
            bg="#E06C75", fg="white", relief="flat", width=8,
            command=self.opreste_tot_media
        ).pack(side="left", padx=5, ipady=6)

        tk.Button(
            controale, text="NEXT >>", font=("Arial", 11, "bold"),
            bg="#4B5263", fg="white", relief="flat", width=8,
            command=self._muzica_next
        ).pack(side="left", padx=5, ipady=6)

        tk.Button(
            controale, text="VOL +", font=("Arial", 11, "bold"),
            bg="#3B4252", fg="white", relief="flat", width=7,
            command=lambda: schimba_volum_relativ(12)
        ).pack(side="left", padx=5, ipady=6)

        self.frame_overlay.place(relx=0.05, rely=0.12, relwidth=0.9, relheight=0.58)
        self.frame_overlay.lift()

    def _muzica_next(self):
        ales = piesa_urmatoare()
        if ales:
            self.afiseaza_overlay_youtube_music(ales)

    def _muzica_prev(self):
        ales = piesa_anterioara()
        if ales:
            self.afiseaza_overlay_youtube_music(ales)

    def porneste_video_selectat(self, numar):
        opreste_voce()
        ales = reda_rezultat_dupa_numar(numar)
        if ales:
            self.afiseaza_mesaj("Sistem", f"Redau videoclipul #{numar}: {ales['titlu']}")

    def opreste_tot_media(self):
        opreste_voce()
        inchide_overlay_youtube()
        self.ascunde_overlay()

    def ascunde_overlay(self):
        self.frame_overlay.place_forget()

    def _trimite_comanda_rapida(self, text_comanda):
        opreste_voce()
        if self.ocupat:
            return
        self.entry_input.delete(0, tk.END)
        self.entry_input.insert(0, text_comanda)
        self.start_procesare()

    # --- WAKE WORD "ROBOT" (STIL ALEXA, FĂRĂ CONFLICT CU MIC) ---
    def toggle_wake_word(self):
        self.wake_word_activ = not self.wake_word_activ
        if self.wake_word_activ:
            self.btn_wake.config(text="WAKE: 'ROBOT' [ON]", bg="#98C379", fg="#1E222A")
            self.porneste_ascultare_wake_word()
        else:
            self.oprire_wake_event.set()
            self.btn_wake.config(text="WAKE: 'ROBOT' [OFF]", bg="#4B5263", fg="white")

    def porneste_ascultare_wake_word(self):
        if not self.wake_word_activ or self.ocupat or self.inchidere_aplicatie:
            return
        self.oprire_wake_event.clear()
        threading.Thread(target=self._fir_wake_word, daemon=True).start()

    def _fir_wake_word(self):
        detectat = asteapta_wake_word(self.oprire_wake_event)
        if detectat and not self.oprire_wake_event.is_set() and not self.ocupat:
            self.root.after(0, self._la_activare_wake_word)

    def _la_activare_wake_word(self):
        if self.ocupat:
            return
        seteaza_volum_sistem(25)
        self.declanseaza_ascultare()

    # --- STREAMING ÎN UI (CUVÂNT CU CUVÂNT) ---
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

    # --- SALUTUL DINAMIC 100% AI + PRE-ÎNCĂLZIRE HARDWARE ---
    def porneste_salut_initial(self):
        self.ocupat = True
        self.btn_send.config(text="MĂ TREZESC...", bg="#E5C07B", fg="#1E222A")
        self.btn_mic.config(bg="#4B5263", text="MIC")
        threading.Thread(target=preincalzeste_microfon, daemon=True).start()
        threading.Thread(target=self.fir_salut_initial, daemon=True).start()

    def fir_salut_initial(self):
        try:
            self.root.after(0, self._incepe_mesaj_stream, "Robot [SALUT]")

            def la_chunk(c):
                self.root.after(0, self._adauga_chunk_stream, c)

            rez = genereaza_salut_pornire(limba="ro", on_text_chunk=la_chunk)
            self.root.after(0, self._incheie_mesaj_stream)

            text_salut = rez.get("mesaj", "")
            if text_salut:
                self.root.after(0, lambda: self.btn_send.config(text="VORBESC...", bg="#98C379", fg="#1E222A"))
                vorbeste(text_salut, limba="ro")
        except Exception as e:
            print(f"[EROARE SALUT]: {e}")
        finally:
            self.root.after(0, self.reseteaza_butoane_dupa_raspuns)

    # --- LOGICA INTUITIVĂ DE ASCULTARE VOCALĂ ---
    def _seteaza_status_input(self, text_status, culoare_text="#FFFFFF", culoare_bg="#282C34"):
        self.entry_input.delete(0, tk.END)
        self.entry_input.config(fg=culoare_text, bg=culoare_bg)
        self.entry_input.insert(0, text_status)

    def actualizeaza_stare_mic(self, faza):
        if faza == "pregatire":
            self.btn_mic.config(bg="#E5C07B", fg="#1E222A", text="WAIT")
            self.btn_send.config(bg="#4B5263", fg="#ABB2BF", text="PREGĂTESC MIC...")
            self._seteaza_status_input("Pregătesc microfonul... Așteaptă o clipă...", "#E5C07B", "#282C34")
        elif faza == "asculta":
            self.btn_mic.config(bg="#E06C75", fg="white", text="REC")
            self.btn_send.config(bg="#E06C75", fg="white", text="VORBEȘTE ACUM!")
            self._seteaza_status_input("TE ASCULT! Vorbește acum (RO sau EN)...", "#FFFFFF", "#3B2328")
        elif faza == "procesare":
            self.btn_mic.config(bg="#E5C07B", fg="#1E222A", text="...")
            self.btn_send.config(bg="#E5C07B", fg="#1E222A", text="PROCESEZ VOCEA...")
            self._seteaza_status_input("Procesez cuvintele tale...", "#E5C07B", "#282C34")

    def declanseaza_ascultare(self):
        opreste_voce()
        if self.ocupat:
            return
        self.ocupat = True
        self.oprire_wake_event.set()
        seteaza_volum_sistem(25)

        if self.tastatura_activa:
            self.toggle_tastatura()

        self.actualizeaza_stare_mic("pregatire")
        threading.Thread(target=self.fir_executie_ascultare, daemon=True).start()

    def fir_executie_ascultare(self):
        time.sleep(0.12)
        text_recunoscut = asculta_voce(
            on_status=lambda faza: self.root.after(0, self.actualizeaza_stare_mic, faza)
        )
        if not text_recunoscut:
            threading.Thread(target=vorbeste, args=("Nu am înțeles, repetă te rog.", "ro"), daemon=True).start()
        self.root.after(0, self.finalizare_ascultare, text_recunoscut)

    def finalizare_ascultare(self, text):
        self.entry_input.delete(0, tk.END)
        self.entry_input.config(fg="white", bg="#282C34")
        self.btn_mic.config(bg="#C678DD", fg="white", text="MIC")

        if text:
            self.entry_input.insert(0, text)
            self.ocupat = False
            self.start_procesare()
        else:
            self.ocupat = False
            seteaza_volum_sistem(95)
            self.btn_send.config(bg="#61AFEF", fg="#1E222A", text="TRIMITE")
            self.afiseaza_mesaj("Sistem", "Nu am înțeles, repetă te rog.")
            self.porneste_ascultare_wake_word()

    # --- LOGICA TASTATURII VIRTUALE ---
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
        if self.ocupat:
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
        if self.ocupat and not self.tastatura_activa:
            return
        if self.tastatura_activa:
            self.frame_kb.place_forget()
            self.btn_kb.config(bg="#4B5263")
            self.tastatura_activa = False
        else:
            self.frame_kb.place(relx=0.05, rely=0.12, relwidth=0.9, relheight=0.58)
            self.frame_kb.lift()
            self.btn_kb.config(bg="#98C379")
            self.tastatura_activa = True

    # --- LOGICA AI STREAMING ÎN UI + VOCE FLUENTĂ + OVERLAY-URI ---
    def start_procesare(self):
        if self.ocupat:
            return
        mesaj_utilizator = self.entry_input.get()
        if not mesaj_utilizator.strip():
            return

        if mesaj_utilizator.strip().lower() in ("șterge conversația", "sterge conversatia", "reset chat"):
            self.entry_input.delete(0, tk.END)
            self.curata_conversatia()
            return

        self.ocupat = True
        self.oprire_wake_event.set()
        self.entry_input.delete(0, tk.END)
        self.afiseaza_mesaj("Tu", mesaj_utilizator)

        if self.tastatura_activa:
            self.toggle_tastatura()

        self.btn_send.config(text="GÂNDESC...", bg="#E5C07B", fg="#1E222A")
        self.btn_mic.config(bg="#4B5263", text="MIC")
        self.root.update()

        threading.Thread(target=self.obtine_raspuns, args=(mesaj_utilizator,), daemon=True).start()

    def obtine_raspuns(self, mesaj):
        try:
            antet_afisat = False

            def la_chunk(c):
                nonlocal antet_afisat
                if not antet_afisat:
                    antet_afisat = True
                    self.root.after(0, self._incepe_mesaj_stream, "Robot")
                self.root.after(0, self._adauga_chunk_stream, c)

            rez = proceseaza_comanda_ai(
                mesaj,
                limba="ro",
                on_text_chunk=la_chunk
            )
            if antet_afisat:
                self.root.after(0, self._incheie_mesaj_stream)

            actiune = rez.get("actiune", "vorbeste_normal")
            date_ui = rez.get("date_ui")
            parametru = rez.get("parametru", "")

            if actiune == "cauta_wikipedia" and isinstance(date_ui, dict):
                self.root.after(0, self.afiseaza_overlay_wikipedia, date_ui)
            elif actiune == "reda_youtube" and isinstance(date_ui, list):
                self.root.after(0, self.afiseaza_overlay_youtube_lista, parametru, date_ui)
            elif actiune == "reda_muzica" and isinstance(date_ui, dict):
                self.root.after(0, self.afiseaza_overlay_youtube_music, date_ui)
            elif actiune == "opreste_media":
                self.root.after(0, self.ascunde_overlay)

            text_final = rez.get("mesaj", "")
            if text_final:
                self.root.after(0, lambda: self.btn_send.config(text="VORBESC...", bg="#98C379", fg="#1E222A"))
                vorbeste(text_final, limba="ro")

            if actiune == "reda_muzica" and isinstance(date_ui, dict):
                deschide_overlay_youtube(date_ui["video_id"], mod_muzica=True)

            seteaza_volum_sistem(95)

        except Exception as e:
            self.root.after(0, lambda: self.afiseaza_mesaj("Eroare Sistem", f"Eroare: {e}"))
        finally:
            self.root.after(0, self.reseteaza_butoane_dupa_raspuns)

    def reseteaza_butoane_dupa_raspuns(self):
        self.ocupat = False
        self.btn_send.config(text="TRIMITE", bg="#61AFEF", fg="#1E222A")
        self.btn_mic.config(text="MIC", bg="#C678DD", fg="white")
        self.porneste_ascultare_wake_word()


if __name__ == "__main__":
    app = tk.Tk()
    ui = RobotCompanionUI(app)
    app.mainloop()