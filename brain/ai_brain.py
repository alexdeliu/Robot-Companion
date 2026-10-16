import os
import json
import time
import random
from google import genai
from google.genai import types
from dotenv import load_dotenv

from brain.abilities.weather import get_weather

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

# Modelul principal și modelele de rezervă (folosite automat dacă apare eroarea 503 High Demand)
MODEL_PRINCIPAL = 'gemini-3.5-flash-lite'
MODELE_REZERVA = ['gemini-2.5-flash-lite', 'gemini-2.5-flash']

instructiuni_sistem = """
Ești "Creierul" unui robot companion fizic de birou. Ești prietenos, inteligent și uneori puțin sarcastic sau glumeț.
Locația ta fizică (acasă) este Timișoara.

Trebuie să răspunzi EXCLUSIV folosind un format JSON valid cu aceste 4 chei:
{
  "actiune": "arata_vreme" / "spune_gluma" / "vorbeste_normal",
  "parametru": "Numele orașului. Dacă NU este cerut specific un oraș, lasă textul complet GOL \"\". Nu ghici și nu presupune orașe!",
  "mesaj": "Răspunsul tău afișat pe ecran (scris corect ortografic)",
  "mesaj_audio": "Răspunsul tău optimizat fonetic pentru cititorul vocal românesc (TTS)"
}

Reguli de comportament:
1. Dacă utilizatorul te întreabă de vreme, folosește "arata_vreme" și extrage orașul.
2. Dacă primești un mesaj de [SISTEM] cu date meteo brute, răspunde natural (1-3 propoziții scurte). SPECIFICĂ mereu orașul și adaugă personalitate.
3. Înțelegi perfect și româna și engleza, dar răspunzi MEREU în limba română.
4. REGULĂ FONETICĂ PENTRU "mesaj_audio": Vocea ta fizică folosește un sintetizator românesc care citește literal. În câmpul "mesaj_audio", transcrie FONETIC cu litere românești ORICE cuvânt, nume sau termen în limba engleză din răspunsul tău (exemple: "voice" -> "vois", "Raspberry Pi" -> "Rezbări Pai", "folder" -> "foldăr", "scrolling" -> "scroling", "upgrade" -> "apgreid", "fake" -> "feic", "AI" -> "ei ai", "OK" -> "ochei") și scrie simbolurile natural ("°C" -> "grade"). În "mesaj" păstrează scrierea normală pentru ecran!

Regulă CRITICĂ: FĂRĂ text pe lângă JSON. Returnează doar obiectul JSON.
"""

# Sesiunea globală pentru memoria conversației
chat_session = client.chats.create(model=MODEL_PRINCIPAL)

def _parseaza_json_ai(text_brut):
    """Curăță și extrage JSON-ul din răspunsul modelului."""
    text_curat = text_brut.replace('```json', '').replace('```', '').strip()
    start = text_curat.find('{')
    end = text_curat.rfind('}')
    if start != -1 and end != -1:
        text_curat = text_curat[start:end + 1]
    return json.loads(text_curat)

def _trimite_la_gemini(text, limba="ro"):
    """
    Comunică cu Gemini. Dacă modelul principal dă eroarea 503 (High Demand),
    încearcă automat modelele de rezervă fără ca utilizatorul să simtă eroarea.
    """
    prompt_complet = f"[Răspunde în limba {'Română' if limba == 'ro' else 'Engleză'}] {text}"
    config_ai = types.GenerateContentConfig(
        system_instruction=instructiuni_sistem,
        temperature=0.7
    )

    # 1. Încercăm pe sesiunea activă cu memorie (modelul principal)
    try:
        raspuns = chat_session.send_message(prompt_complet, config=config_ai)
        return _parseaza_json_ai(raspuns.text)
    except json.JSONDecodeError:
        return {"actiune": "eroare", "mesaj": "Am avut o mică încurcătură în gândire. Mai spune-mi o dată!"}
    except Exception as e:
        eroare_str = str(e)
        print(f"[AVERTISMENT AI]: Modelul principal {MODEL_PRINCIPAL} a returnat: {eroare_str}")

        # 2. Dacă e eroare de tip 503 / 429 / Overloaded, comutăm instant pe modelele de rezervă
        for model_backup in MODELE_REZERVA:
            try:
                print(f"[SISTEM AI]: Comut automat pe modelul de rezervă {model_backup}...")
                time.sleep(0.3)
                raspuns_backup = client.models.generate_content(
                    model=model_backup,
                    contents=prompt_complet,
                    config=config_ai
                )
                return _parseaza_json_ai(raspuns_backup.text)
            except Exception as e_backup:
                print(f"[AVERTISMENT AI]: Modelul {model_backup} indisponibil ({e_backup})")

        # 3. Dacă absolut toate serverele sunt picate sau nu există internet
        return {
            "actiune": "eroare",
            "mesaj": "Serverele mele sunt cam aglomerate în clipa asta. Mai încearcă în câteva secunde!"
        }

def genereaza_mesaj_bun_venit(limba="ro"):
    """
    Generează un mesaj de deschidere dinamic când pornește robotul,
    cu o stare de spirit aleasă aleatoriu la fiecare pornire.
    """
    stari_de_spirit = [
        (
            "morocănos, somnoros și ușor iritat în glumă că tocmai ai fost trezit din somn",
            "Off, iar m-ai băgat în priză? Dormeam așa de bine pe cardul ăsta SD... Hai, zi repede, ce vrei?"
        ),
        (
            "glumeț, ironic și pus pe șotii",
            "Sistemele mele geniale sunt online! Sper că ai o întrebare bună azi și nu mă pui iar doar să mă uit pe geam după vreme."
        ),
        (
            "plictisit și dramatic, ca și cum viața într-o cutie de Raspberry Pi e grea",
            "Am pornit... încă o zi pe biroul ăsta din Timișoara. Zi-mi, cu ce îți mai salvez ziua azi?"
        ),
        (
            "exagerat de politicos, ca un majordom regal britanic",
            "Bună ziua, stăpâne! Toate circuitele mele vă stau la dispoziție. Cu ce vă pot fi de folos?"
        ),
        (
            "plin de energie și entuziasm",
            "Salutare! M-am încărcat sută la sută și sunt gata de acțiune! Despre ce vorbim azi?"
        )
    ]

    stare_aleasa, mesaj_rezerva = random.choice(stari_de_spirit)
    prompt_salut = (
        f"[SISTEM] Tocmai ai fost pornit de utilizator. "
        f"Spune-i un mesaj scurt de întâmpinare (maxim 2 propoziții) în care să fii {stare_aleasa}. "
        f"Pune acțiunea pe 'vorbeste_normal'."
    )

    rezultat = _trimite_la_gemini(prompt_salut, limba)
    if rezultat.get("actiune") == "eroare" or not rezultat.get("mesaj"):
        return mesaj_rezerva
    return rezultat.get("mesaj")

def proceseaza_comanda_ai(text, limba="ro"):
    """Funcția principală apelată de interfața grafică. Aici se execută Tool Calling-ul."""
    raspuns_robot = _trimite_la_gemini(text, limba)
    
    if raspuns_robot.get("actiune") == "arata_vreme":
        oras_extras = raspuns_robot.get("parametru", "")
        oras_tinta = oras_extras if oras_extras else "Timișoara"
        
        try:
            raport_date = get_weather(oras_extras) if oras_extras else get_weather()
        except Exception as e:
            raport_date = f"Eroare senzor: {e}"
        
        prompt_ascuns = (
            f"[SISTEM] Ai primit următoarele date meteo pentru {oras_tinta}:\n{raport_date}\n\n"
            f"Formulează răspunsul final către utilizator în maxim 2-3 propoziții scurte și naturale. "
            f"Folosește-ți personalitatea! Pune acțiunea pe 'vorbeste_normal'."
        )
        
        raspuns_final = _trimite_la_gemini(prompt_ascuns, limba)
        raspuns_robot["mesaj"] = raspuns_final.get("mesaj", "Nu am putut citi prognoza.")
        raspuns_robot["actiune"] = "arata_vreme"
        
    return raspuns_robot

if __name__ == "__main__":
    print("🧠 Creierul a pornit.")
    print("Salut generat:", genereaza_mesaj_bun_venit())