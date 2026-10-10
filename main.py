import tkinter as tk
from tkinter import scrolledtext
import threading
from brain.ai_brain import proceseaza_comanda_ai

class RobotCompanionUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Robot Companion")
        
        # --- SECRETUL PENTRU KIOSK MODE PERFECT ---
        # Scoatem marginile ferestrei și preluăm controlul absolut
        self.root.overrideredirect(True) 
        
        # Luăm dimensiunea reală a ecranului, oricare ar fi ea
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_width}x{screen_height}+0+0")
        self.root.configure(bg="#1E222A") # Fundal închis

        # --- CONSTRUIREA INTERFEȚEI (Adaptabilă) ---
        
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
        self.text_display.place(relx=0.05, rely=0.15, relwidth=0.9, relheight=0.55)
        self.afiseaza_mesaj("Sistem", "Sisteme online. Aștept comenzi...")

        # 3. Zona pentru input
        self.entry_input = tk.Entry(
            self.root, font=("Arial", 14), 
            bg="#282C34", fg="white", insertbackground="white", relief="flat"
        )
        self.entry_input.place(relx=0.05, rely=0.75, relwidth=0.9, relheight=0.1)
        self.entry_input.bind("<Return>", lambda event: self.start_procesare())

        # 4. Butonul TRIMITE
        self.btn_send = tk.Button(
            self.root, text="TRIMITE", font=("Arial", 12, "bold"),
            bg="#61AFEF", fg="#1E222A", command=self.start_procesare, relief="flat"
        )
        self.btn_send.place(relx=0.05, rely=0.87, relwidth=0.9, relheight=0.1)
        
        # Forțăm cursorul în căsuța de text la pornire!
        self.entry_input.focus_force()

    # --- LOGICA ---
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