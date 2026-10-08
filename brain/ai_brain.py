import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

# IMPORTUL MODULAR: Acum apelăm fix fișierul weather.py din folderul abilities
from abilities.weather import get_weather

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)
nume_model = 'gemini-3.5-flash-lite' 

instructiuni_sistem = """
Ești "Creierul" unui robot companion. 
Rolul tău este să analizezi ce spune utilizatorul și să iei o decizie logică.
Trebuie să răspunzi EXCLUSIV folosind un format JSON valid, care să conțină trei chei:
- "actiune": poți alege dintre "arata_vreme", "spune_gluma", "schimba_limba", sau "vorbeste_normal".
- "parametru": Dacă utilizatorul cere vremea pentru un oraș anume, pune aici numele orașului. Dacă nu specifică orașul, lasă textul gol "".
- "mesaj": un răspuns natural, prietenos și scurt de confirmare.

Regulă CRITICĂ: Nu adăuga absolut niciun alt text pe lângă JSON. Nici măcar marcaje (```json).
"""

chat_session = client.chats.create(model=nume_model)

def proceseaza_comanda_ai(text, limba="ro"):
    prompt_complet = f"[Răspunde obligatoriu în limba {'Română' if limba == 'ro' else 'Engleză'}] {text}"
    
    try:
        raspuns = chat_session.send_message(
            prompt_complet,
            config=types.GenerateContentConfig(
                system_instruction=instructiuni_sistem,
                temperature=0.7
            )
        )
        
        text_curat = raspuns.text.replace('```json', '').replace('```', '').strip()
        return json.loads(text_curat)
        
    except json.JSONDecodeError:
         return {"actiune": "eroare", "mesaj": "M-am încurcat și nu am răspuns în JSON."}
    except Exception as e:
        return {"actiune": "eroare", "mesaj": f"Ups, eroare de conexiune: {e}"}


if __name__ == "__main__":
    limba_selectata = "ro"
    print(f"🧠 Creierul AI s-a conectat. Arhitectura modulară e activă. Scrie 'exit' pentru a ieși.")
    
    while True:
        intrare = input("Tu: ")
        if intrare.lower() == "exit":
            break
            
        print("Mă gândesc...")
        raspuns_robot = proceseaza_comanda_ai(intrare, limba_selectata)
        
        # --- EXECUTAREA ABILITĂȚILOR MODULARE ---
        if raspuns_robot.get("actiune") == "arata_vreme":
            oras_extras = raspuns_robot.get("parametru", "")
            print("⏳ Mă conectez la satelit...")
            
            # Dacă AI-a găsit un oraș, îl trimitem la funcția get_weather
            if oras_extras != "":
                date_reale = get_weather(oras_extras)
            else:
                date_reale = get_weather() # Va folosi orașul implicit (Timișoara)
                
            # Robotul își actualizează mesajul cu temperatura reală!
            raspuns_robot["mesaj"] = date_reale
        # ----------------------------------------
        
        print(f"Decizia finală AI: {raspuns_robot}\n")