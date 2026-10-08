import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv
from abilities.weather import get_weather

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)
nume_model = 'gemini-3.5-flash-lite' 

instructiuni_sistem = """
Ești "Creierul" unui robot companion fizic de birou. Ești prietenos, inteligent și uneori puțin sarcastic sau glumeț. 
Locația ta fizică (acasă) este Timișoara.

Trebuie să răspunzi EXCLUSIV folosind un format JSON valid:
{
  "actiune": "arata_vreme" / "spune_gluma" / "vorbeste_normal",
  "parametru": "Numele orașului. Dacă NU este cerut specific un oraș, lasă textul complet GOL \"\". Nu ghici și nu presupune orașe (cum ar fi București)!",
  "mesaj": "Răspunsul tău vorbit"
}

Reguli de comportament:
1. Dacă utilizatorul te întreabă de vreme, folosește "arata_vreme" și extrage orașul.
2. Dacă primești un mesaj de [SISTEM] cu date meteo brute, răspunde natural folosind acele date. SPECIFICĂ mereu cuvântul/orașul despre care vorbești în răspunsul tău. Adaugă personalitate (ex: bucură-te dacă e cald, comentează dacă plouă). Acțiunea devine "vorbeste_normal".
Regulă CRITICĂ: FĂRĂ text pe lângă JSON.
"""

chat_session = client.chats.create(model=nume_model)

def proceseaza_comanda_ai(text, limba="ro"):
    prompt_complet = f"[Răspunde în limba {'Română' if limba == 'ro' else 'Engleză'}] {text}"
    try:
        raspuns = chat_session.send_message(
            prompt_complet,
            config=types.GenerateContentConfig(
                system_instruction=instructiuni_sistem,
                temperature=0.7 # Temperatura 0.7 îi permite să fie creativ/glumeț
            )
        )
        text_curat = raspuns.text.replace('```json', '').replace('```', '').strip()
        return json.loads(text_curat)
    except Exception as e:
        return {"actiune": "eroare", "mesaj": f"Eroare procesare: {e}"}

if __name__ == "__main__":
    limba_selectata = "ro"
    print(f"🧠 Creierul a pornit. Sistemul de Analiză Meteo (Agent) activ.")
    
    while True:
        intrare = input("Tu: ")
        if intrare.lower() == "exit":
            break
            
        print("Mă gândesc...")
        raspuns_robot = proceseaza_comanda_ai(intrare, limba_selectata)
        
        # --- BUCLA DE TOOL CALLING (AGENT INTELLIGENCE) ---
        if raspuns_robot.get("actiune") == "arata_vreme":
            oras_extras = raspuns_robot.get("parametru", "")
            print(f"[A declanșat modulul Meteo pentru: {oras_extras if oras_extras else 'Timișoara'}]")
            
            # 1. Tragem tabelul de pe net
            raport_date = get_weather(oras_extras) if oras_extras else get_weather()
            
            # 2. Trimitem tabelul înapoi la AI pe ascuns ca să îl citească
            prompt_ascuns = f"[SISTEM] Ai primit următoarele date brute de la senzorul meteo:\n{raport_date}\n\nAcum răspunde-i utilizatorului la întrebarea pe care ți-a pus-o adineauri. Folosește aceste date pentru a-i oferi un răspuns complet, cu detalii specifice dacă a cerut, și folosește-ți personalitatea! Pune acțiunea pe 'vorbeste_normal'."
            
            print("🧠 AI-ul analizează tabelul satelitului și formulează propoziția...")
            raspuns_final = proceseaza_comanda_ai(prompt_ascuns, limba_selectata)
            
            # Răspunsul final va conține interpretarea umană și amuzantă a datelor
            raspuns_robot["mesaj"] = raspuns_final["mesaj"]
        # --------------------------------------------------
        
        print(f"Robotul: {raspuns_robot['mesaj']}\n")