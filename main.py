import tkinter as tk
from tkinter import scrolledtext
import threading

# Importăm creierul din folderul 'brain'
from brain.ai_brain import proceseaza_comanda_ai

class RobotCompanionUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Robot Companion")
        self.root.geometry("480x320")
        self.root.attributes('-fullscreen', True)
        self.root.configure(bg="#2E3440")

        # --- CONSTRUIREA INTERFEȚEI ---
        
        # 1. Buton de închidere (mai ușor de apăsat cu degetul)
        self.btn_exit = tk.Button(
            self.root, text="X", font=("Arial", 12, "bold"), 
            bg="#BF616A", fg="white", command=self.root.destroy, relief="flat"
        )
        self.btn_exit.place(x=430, y=5, width=40, height=40)

        # 2. Zona de afișare text (Acum are SCROLL și istoric)
        self.text_display = scrolledtext.ScrolledText(
            self.root, font=("Arial", 12), bg="#2E3440", fg="#ECEFF4",
            wrap=tk.WORD, relief="flat", state=tk.DISABLED
        )
        self.text_display.pack(expand=True, fill="both", padx=10, pady=(15, 10))
        self.afiseaza_mesaj("Sistem", "Sisteme online. Aștept comenzi...")

        # 3. Zona pentru input
        self.entry_input = tk.Entry(
            self.root, font=("Arial", 14), 
            bg="#3B4252", fg="white", insertbackground="white", relief="flat"
        )
        self.entry_input.pack(fill="x", padx=10, pady=5, ipady=8)
        self.entry_input.bind("<Return>", lambda event: self.start_procesare())

        # 4. Butonul TRIMITE (Inteligent)
        self.btn_send = tk.Button(
            self.root, text="TRIMITE MESAJUL", font=("Arial", 12, "bold"),
            bg="#81A1C1", fg="#2E3440", command=self.start_procesare, relief="flat"
        )
        self.btn_send.pack(fill="x", padx=10, pady=(0, 10), ipady=8)

    # --- LOGICA ---

    def afiseaza_mesaj(self, expeditor, mesaj):
        """Funcție utilitară pentru a scrie curat în zona de text"""
        self.text_display.config(state=tk.NORMAL)
        self.text_display.insert(tk.END, f"{expeditor}: {mesaj}\n\n")
        self.text_display.see(tk.END) # Face scroll automat jos
        self.text_display.config(state=tk.DISABLED)

    def start_procesare(self):
        mesaj_utilizator = self.entry_input.get()
        if not mesaj_utilizator.strip():
            return
            
        self.entry_input.delete(0, tk.END)
        self.afiseaza_mesaj("Tu", mesaj_utilizator)
        
        # BLOCĂM butonul ca să nu poată fi spamat
        self.btn_send.config(state=tk.DISABLED, text="MĂ GÂNDESC...", bg="#EBCB8B")
        self.root.update()

        threading.Thread(target=self.obtine_raspuns, args=(mesaj_utilizator,)).start()

    def obtine_raspuns(self, mesaj):
        try:
            raspuns = proceseaza_comanda_ai(mesaj, limba="ro")
            text_final = raspuns.get("mesaj", "Eroare: Răspuns invalid.")
            actiune = raspuns.get("actiune", "info")
            
            self.afiseaza_mesaj(f"Robot [{actiune.upper()}]", text_final)
            
        except Exception as e:
            self.afiseaza_mesaj("Eroare Sistem", f"Nu m-am putut conecta: {e}")
            
        finally:
            # DEBLOCĂM butonul la final, indiferent de rezultat
            self.btn_send.config(state=tk.NORMAL, text="TRIMITE MESAJUL", bg="#81A1C1")

if __name__ == "__main__":
    app = tk.Tk()
    ui = RobotCompanionUI(app)
    app.mainloop()