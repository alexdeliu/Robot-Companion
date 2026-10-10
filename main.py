import tkinter as tk
from tkinter import scrolledtext
import threading
from brain.ai_brain import proceseaza_comanda_ai

class RobotCompanionUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Robot Companion")
        
        # --- SECRETUL PENTRU KIOSK MODE PERFECT ---
        self.root.overrideredirect(True) 
        
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_width}x{screen_height}+0+0")
        self.root.configure(bg="#1E222A")

        # --- CONSTRUIREA INTERFEȚEI ---
        
        # 1. Buton Ieșire (dreapta-sus)
        self.btn_exit = tk.Button(
            self.root, text="X", font=("Arial", 12, "bold"), 
            bg="#E06C75", fg="white", command=self.root.destroy, relief="flat"
        )
        self.btn_exit.place(relx=0.88, rely=0.02, relwidth=0.1, relheight=0.1)

        # 2. Zona de afișare text
        self.text_display = scrolledtext.ScrolledText(
            self.root, font=("Arial", 12), bg="#1E222A", fg="#ABB2BF",
            wrap=tk.WORD, relief="flat", state=tk.DISABLED
        )
        self.text_display.place(relx=0.05, rely=0.12, relwidth=0.9, relheight=0.58)
        self.afiseaza_mesaj("Sistem", "Sisteme online. Aștept comenzi...")

        # 3. Zona pentru input
        self.entry_input = tk.Entry(
            self.root, font=("Arial", 14), 
            bg="#282C34", fg="white", insertbackground="white", relief="flat"
        )
        self.entry_input.place(relx=0.05, rely=0.72, relwidth=0.9, relheight=0.12)
        self.entry_input.bind("<Return>", lambda event: self.start_procesare())

        # 4. Buton Tastatură Virtuală (stânga jos)
        self.tastatura_activa = False
        self.btn_kb = tk.Button(
            self.root, text="⌨", font=("Arial", 16),
            bg="#4B5263", fg="white", command=self.toggle_tastatura, relief="flat"
        )
        self.btn_kb.place(relx=0.05, rely=0.86, relwidth=0.15, relheight=0.12)

        # 5. Butonul TRIMITE (micșorat pentru a face loc tastaturii)
        self.btn_send = tk.Button(
            self.root, text="TRIMITE", font=("Arial", 12, "bold"),
            bg="#61AFEF", fg="#1E222A", command=self.start_procesare, relief="flat"
        )
        self.btn_send.place(relx=0.22, rely=0.86, relwidth=0.73, relheight=0.12)
        
        # 6. Containerul Tastaturii Virtuale (ascuns inițial)
        self.frame_kb = tk.Frame(self.root, bg="#1E222A")
        self.construieste_tastatura()

        self.entry_input.focus_force()

    # --- LOGICA TASTATURII VIRTUALE ---
    def construieste_tastatura(self):
        # 5 rânduri optimizate pentru ecrane mici, incluzând cifre și punctuație
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
        # Inserare inteligentă la poziția cursorului, nu doar la final
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
            
        self.entry_input.focus_force() # Păstrează clipitorul în căsuță

    def toggle_tastatura(self):
        if self.tastatura_activa:
            self.frame_kb.place_forget()
            self.btn_kb.config(bg="#4B5263")
            self.tastatura_activa = False
        else:
            # Tastatura acoperă exact zona de chat (text_display)
            self.frame_kb.place(relx=0.05, rely=0.12, relwidth=0.9, relheight=0.58)
            self.frame_kb.lift() # O forțăm să stea deasupra textului
            self.btn_kb.config(bg="#98C379") # Se face verde când e activă
            self.tastatura_activa = True

    # --- LOGICA AI ---
    def afiseaza_mesaj(self, expeditor, mesaj):
        self.text_display.config(state=tk.NORMAL)
        self.text_display.insert(tk.END, f"{expeditor}: {mesaj}\n\n")
        self.text_display.see(tk.END)
        self.text_display.config(state=tk.DISABLED)

    def start_procesare(self):
        mesaj_utilizator = self.entry_input.get()
        if not mesaj_utilizator.strip():
            return
            
        self.entry_input.delete(0, tk.END)
        self.afiseaza_mesaj("Tu", mesaj_utilizator)
        
        # Ascundem tastatura automat când trimitem un mesaj
        if self.tastatura_activa:
            self.toggle_tastatura()
            
        self.btn_send.config(state=tk.DISABLED, text="MĂ GÂNDESC...", bg="#E5C07B")
        self.root.update()

        threading.Thread(target=self.obtine_raspuns, args=(mesaj_utilizator,)).start()

    def obtine_raspuns(self, mesaj):
        try:
            raspuns = proceseaza_comanda_ai(mesaj, limba="ro")
            text_final = raspuns.get("mesaj", "Eroare: Răspuns invalid.")
            actiune = raspuns.get("actiune", "info")
            self.afiseaza_mesaj(f"Robot [{actiune.upper()}]", text_final)
        except Exception as e:
            self.afiseaza_mesaj("Eroare Sistem", f"Eroare: {e}")
        finally:
            self.btn_send.config(state=tk.NORMAL, text="TRIMITE", bg="#61AFEF")

if __name__ == "__main__":
    app = tk.Tk()
    ui = RobotCompanionUI(app)
    app.mainloop()