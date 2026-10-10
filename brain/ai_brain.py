import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Importul complet pentru a funcționa apelat din exterior
from brain.abilities.weather import get_weather

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
2. Dacă primești un mesaj de [SISTEM] cu date meteo brute, răspunde natural folosind acele date. SPECIFICĂ mereu cuvântul/orașul despre care vorbești în răspunsul tău. Adaugă personalitate (ex: bucură-te dacă e cald, comentează dacă plouă).
Regulă CRITICĂ: FĂRĂ text pe lângă JSON. Returnează doar obiectul JSON.
"""

# Această sesiune globală acționează ca o memorie pe termen scurt.
chat_session = client.chats.create(model=nume_model)

def _trimite_la_gemini(text, limba="ro"):
    """Funcție internă care doar comunică cu Google și se asigură că primim JSON."""
    prompt_complet = f"[Răspunde în limba {'Română' if limba == 'ro' else 'Engleză'}] {text}"
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
        return {"actiune": "eroare", "mesaj": "Eroare internă: AI-ul a generat un format invalid."}
    except Exception as e:
        return {"actiune": "eroare", "mesaj": f"Eroare procesare rețea: {e}"}

def proceseaza_comanda_ai(text, limba="ro"):
    """Funcția principală apelată de interfața grafică. Aici se execută Tool Calling-ul."""
    # 1. Întrebăm AI-ul ce vrea să facă
    raspuns_robot = _trimite_la_gemini(text, limba)
    
    # 2. Dacă alege să caute vremea, interceptăm comanda
    if raspuns_robot.get("actiune") == "arata_vreme":
        oras_extras = raspuns_robot.get("parametru", "")
        oras_tinta = oras_extras if oras_extras else "Timișoara"
        
        # Extragem datele reale de la senzor/API
        try:
            raport_date = get_weather(oras_extras) if oras_extras else get_weather()
        except Exception as e:
            raport_date = f"Eroare senzor: {e}"
        
        # Trimitem datele înapoi la Gemini pe ascuns pentru a le interpreta
        prompt_ascuns = f"[SISTEM] Ai primit următoarele date brute de la senzorul meteo pentru {oras_tinta}:\n{raport_date}\n\nFormulează răspunsul final către utilizator. Folosește-ți personalitatea! Pune acțiunea pe 'vorbeste_normal'."
        
        raspuns_final = _trimite_la_gemini(prompt_ascuns, limba)
        
        # Construim răspunsul final pentru interfață:
        # Păstrăm acțiunea 'arata_vreme' (ca pe viitor UI-ul să afișeze o animație cu nori/soare)
        # Dar înlocuim mesajul cu prognoza interpretată frumos de AI
        raspuns_robot["mesaj"] = raspuns_final.get("mesaj", "Nu am putut citi prognoza.")
        raspuns_robot["actiune"] = "arata_vreme" 
        
    return raspuns_robot

if __name__ == "__main__":
    # Acest bloc rămâne doar pentru teste rapide direct din terminalul VS Code
    print("🧠 Creierul a pornit. Sistemul de Analiză Meteo (Agent) activ.")
    while True:
        intrare = input("Tu: ")
        if intrare.lower() == "exit":
            break
        print("Mă gândesc...")
        rezultat = proceseaza_comanda_ai(intrare, "ro")
        print(f"Robotul [{rezultat.get('actiune')}]: {rezultat.get('mesaj')}\n")