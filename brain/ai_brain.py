import os
import json
from google import genai
from google.genai import types # Adăugăm importul pentru tipurile de date
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=API_KEY)

nume_model = 'gemini-3.5-flash-lite' 

# Setăm personalitatea separat 
instructiuni_sistem = """
Ești "Creierul" unui robot companion. 
Rolul tău este să analizezi ce spune utilizatorul și să iei o decizie logică.
Trebuie să răspunzi EXCLUSIV folosind un format JSON valid, care să conțină două chei:
- "actiune": poți alege dintre "arata_vreme", "spune_gluma", "schimba_limba", sau "vorbeste_normal".
- "mesaj": un răspuns natural, prietenos și scurt.

Regulă CRITICĂ: Nu adăuga absolut niciun alt text pe lângă JSON. Nici măcar marcaje (```json).
"""

# Inițializăm un 'chat' simplu
chat_session = client.chats.create(model=nume_model)

def proceseaza_comanda_ai(text, limba="ro"):
    prompt_complet = f"[Răspunde obligatoriu în limba {'Română' if limba == 'ro' else 'Engleză'}] {text}"
    
    try:
        # AICI este modificarea: trimitem config-ul împreună cu mesajul
        raspuns = chat_session.send_message(
            prompt_complet,
            config=types.GenerateContentConfig(
                system_instruction=instructiuni_sistem,
                temperature=0.7
            )
        )
        
        # Curățăm și returnăm JSON-ul
        text_curat = raspuns.text.replace('```json', '').replace('```', '').strip()
        return json.loads(text_curat)
        
    except json.JSONDecodeError:
         return {"actiune": "eroare", "mesaj": "M-am încurcat și nu am răspuns în format JSON."}
    except Exception as e:
        return {"actiune": "eroare", "mesaj": f"Ups, eroare de conexiune: {e}"}


if __name__ == "__main__":
    limba_selectata = "ro"
    print(f"🧠 Creierul AI s-a conectat la {nume_model}. Scrie 'exit' pentru a ieși.")
    
    while True:
        intrare = input("Tu: ")
        if intrare.lower() == "exit":
            break
            
        print("Mă gândesc...")
        raspuns_robot = proceseaza_comanda_ai(intrare, limba_selectata)
        print(f"Decizia AI-ului: {raspuns_robot}\n")