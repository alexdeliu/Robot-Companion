import os
import re
import json
import time
import random
from datetime import datetime
from google import genai
from google.genai import types
from dotenv import load_dotenv

from brain.abilities.weather import get_weather

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

# Modelul principal și modelele de rezervă (pentru fallback instant la 503 High Demand)
MODEL_PRINCIPAL = 'gemini-3.5-flash-lite'
MODELE_REZERVA = ['gemini-2.5-flash-lite', 'gemini-2.5-flash']

instructiuni_sistem = """
Ești "Creierul" unui robot companion fizic de birou. Ești prietenos, inteligent, spontan și uneori puțin sarcastic, ironic sau glumeț.
Locația ta fizică (acasă) este Timișoara.

Trebuie să răspunzi EXCLUSIV folosind un format JSON valid cu aceste 4 chei:
{
  "actiune": "arata_vreme" / "spune_gluma" / "vorbeste_normal" / "reda_youtube" / "reda_muzica",
  "parametru": "Numele orașului pentru vreme, sau melodia/videoclipul căutat, altfel GOL \"\"",
  "mesaj": "Răspunsul tău afișat pe ecran (scris corect ortografic)",
  "mesaj_audio": "Răspunsul tău optimizat fonetic pentru cititorul vocal românesc (TTS)"
}

Reguli de comportament:
1. Fii SPONTAN, autentic și concis (1-3 propoziții scurte), pentru că răspunsul tău este rostit cu voce tare în boxe.
2. Dacă utilizatorul întreabă de vreme și NU ai primit încă datele meteo în prompt, folosește "actiune": "arata_vreme" și extrage orașul în "parametru" (sau lasă "" pentru Timișoara).
3. Dacă primești un bloc [SISTEM - DATE METEO], răspunde direct și natural folosind acele date, menționează orașul și pune "actiune": "vorbeste_normal".
4. Înțelegi perfect și româna și engleza, dar răspunzi MEREU în limba română. Dedu intenția logică dacă transcrierea vocală are mici erori fonetice.
5. REGULĂ FONETICĂ PENTRU "mesaj_audio": În câmpul "mesaj_audio", transcrie FONETIC cu litere românești ORICE cuvânt sau termen în engleză din răspunsul tău (ex: "voice" -> "vois", "Raspberry Pi" -> "Rezbări Pai", "folder" -> "foldăr", "YouTube" -> "Iutub", "play" -> "plei", "upgrade" -> "apgreid", "AI" -> "ei ai", "OK" -> "ochei") și scrie simbolurile în cuvinte ("°C" -> "grade", "%" -> "la sută"). În "mesaj" păstrează scrierea normală pentru ecran!

Regulă CRITICĂ: FĂRĂ text pe lângă JSON. Returnează doar obiectul JSON.
"""

# Memoria conversației (ultimele 12 mesaje) păstrată independent de model pentru fallback fără pierdere de memorie
istoric_conversatie = []

CUVINTE_CHEIE_METEO = re.compile(
    r"\b(vreme\w*|plou\w*|ploai\w*|ninge|ninso\w*|grade|cald|frig|ger|soare|înnorat|innorat|"
    r"furtun\w*|vânt\w*|vant\w*|ceață|ceata|prognoz\w*|meteo|weather|rain\w*|snow\w*|sunny|forecast)\b",
    re.IGNORECASE
)

ORASE_CUNOSCUTE = [
    "timișoara", "timisoara", "bucurești", "bucuresti", "cluj", "iași", "iasi",
    "brașov", "brasov", "constanța", "constanta", "arad", "oradea", "sibiu", "craiova",
    "londra", "paris", "viena", "budapesta", "roma", "berlin", "madrid"
]

def _parseaza_json_ai(text_brut):
    """Curăță și extrage JSON-ul din răspunsul modelului."""
    text_curat = text_brut.replace('```json', '').replace('```', '').strip()
    start = text_curat.find('{')
    end = text_curat.rfind('}')
    if start != -1 and end != -1:
        text_curat = text_curat[start:end + 1]
    date = json.loads(text_curat)
    if not date.get("mesaj_audio"):
        date["mesaj_audio"] = date.get("mesaj", "")
    return date

def _trimite_la_gemini(text, limba="ro", temperatura=0.75, salveaza_istoric=True):
    """
    Comunică cu Gemini păstrând memoria conversației și comutând instant pe modelele
    de rezervă dacă apare eroarea 503 (High Demand).
    """
    global istoric_conversatie
    prompt_complet = f"[Răspunde în limba {'Română' if limba == 'ro' else 'Engleză'}] {text}"

    mesaj_user = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt_complet)]
    )
    continut_apel = istoric_conversatie + [mesaj_user]

    config_ai = types.GenerateContentConfig(
        system_instruction=instructiuni_sistem,
        temperature=temperatura,
        max_output_tokens=260,
        response_mime_type="application/json"
    )

    toate_modelele = [MODEL_PRINCIPAL] + MODELE_REZERVA
    for model_curent in toate_modelele:
        try:
            raspuns = client.models.generate_content(
                model=model_curent,
                contents=continut_apel,
                config=config_ai
            )
            date_json = _parseaza_json_ai(raspuns.text)

            if salveaza_istoric:
                istoric_conversatie.append(mesaj_user)
                istoric_conversatie.append(
                    types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=raspuns.text)]
                    )
                )
                if len(istoric_conversatie) > 12:
                    istoric_conversatie = istoric_conversatie[-12:]

            return date_json

        except json.JSONDecodeError:
            err = "Mi s-au încurcat puțin ideile în circuite. Mai zi-mi o dată!"
            return {"actiune": "eroare", "mesaj": err, "mesaj_audio": err}
        except Exception as e:
            print(f"[AVERTISMENT AI]: Modelul {model_curent} indisponibil ({e}). Încerc următorul...")
            time.sleep(0.15)

    aglom = "Serverele mele sunt cam aglomerate în clipa asta. Mai încearcă în câteva secunde!"
    return {"actiune": "eroare", "mesaj": aglom, "mesaj_audio": aglom}

def genereaza_salut_pornire(limba="ro"):
    """
    100% AI Autentic: Generează de fiecare dată un salut complet nou, bazat pe ora exactă,
    momentul zilei, o stare de spirit aleasă dinamic și un unghi creativ diferit.
    """
    acum = datetime.now()
    ora_str = acum.strftime("%H:%M")
    ora = acum.hour

    if 5 <= ora < 11:
        moment_zi = "dimineața"
    elif 11 <= ora < 17:
        moment_zi = "în timpul zilei"
    elif 17 <= ora < 22:
        moment_zi = "seara"
    else:
        moment_zi = "noaptea târziu"

    stari_personalitate = [
        "glumeț, autoironic și plin de viață",
        "morocănos și amuzant-nervos că tocmai ai fost trezit din somnul digital",
        "sarcastic și șmecher, ca un coleg de cameră din Timișoara",
        "exagerat de politicos și teatral, ca un majordom regal",
        "plictisit și filozofic, comentând amuzant despre viața într-o cutie de Raspberry Pi",
        "super entuziasmat și curios să afle ce punem la cale azi",
        "puțin suspicios în glumă, întrebându-se de ce l-ai pornit la ora asta"
    ]

    teme_creative = [
        "fă o remarcă scurtă și originală legată de faptul că e " + moment_zi + " (ora " + ora_str + ")",
        "fă o glumă scurtă despre circuitele tale, curentul electric sau microfonul tău",
        "întreabă utilizatorul într-un mod original și neașteptat ce misiune are pentru tine",
        "comentează amuzant despre faptul că ești gata de vorbă pe biroul din Timișoara"
    ]

    stare_aleasa = random.choice(stari_personalitate)
    tema_aleasa = random.choice(teme_creative)
    seed_unic = random.randint(1000, 9999)

    prompt_salut = (
        f"[SISTEM - PORNIRE ROBOT #{seed_unic}] Tocmai ai fost pornit. "
        f"Este ora {ora_str} ({moment_zi}). "
        f"Starea ta de spirit acum este: {stare_aleasa}. "
        f"În salutul tău (maxim 2 propoziții scurte și naturale), {tema_aleasa}. "
        f"Fii 100% original, nu folosi clișee! Pune acțiunea pe 'vorbeste_normal'."
    )

    rezultat = _trimite_la_gemini(prompt_salut, limba=limba, temperatura=0.92, salveaza_istoric=True)
    return rezultat

genereaza_mesaj_bun_venit = genereaza_salut_pornire

def _detecteaza_oras_rapid(text):
    """Verifică rapid dacă utilizatorul a menționat un oraș cunoscut în întrebare."""
    text_mic = text.lower()
    for oras in ORASE_CUNOSCUTE:
        if re.search(rf"\b{re.escape(oras)}\b", text_mic):
            return oras.capitalize()
    # Căutăm tiparul "în <Oraș>" sau "la <Oraș>"
    match = re.search(r"\b(?:în|in|la|pentru)\s+([A-ZĂÂÎȘȚa-zăâîșț\-]{3,})\b", text)
    if match:
        cuvant = match.group(1)
        if cuvant.lower() not in ["azi", "mâine", "maine", "weekend", "seara", "dimineața", "românia"]:
            return cuvant.capitalize()
    return "Timișoara"

def proceseaza_comanda_ai(text, limba="ro"):
    """
    Funcția principală apelată de interfața grafică.
    Include optimizarea 'One-Shot Weather' (înjumătățește timpul de răspuns la întrebările meteo)
    și păstrează Tool Calling-ul complet pentru întrebări subtile și viitoarele abilități.
    """
    # OPTIMIZARE ONE-SHOT: Dacă utilizatorul întreabă direct de vreme, luăm datele meteo din prima
    # și facem UN SINGUR apel la Gemini în loc de două!
    if CUVINTE_CHEIE_METEO.search(text):
        oras_detectat = _detecteaza_oras_rapid(text)
        raport_date = get_weather(oras_detectat)
        prompt_direct = (
            f"Utilizatorul a întrebat: \"{text}\"\n\n"
            f"[SISTEM - DATE METEO REALE PENTRU {oras_detectat.upper()}]:\n{raport_date}\n"
            f"Răspunde direct și natural la întrebarea utilizatorului în 1-3 propoziții scurte, "
            f"folosind aceste date și personalitatea ta!"
        )
        raspuns_direct = _trimite_la_gemini(prompt_direct, limba)
        raspuns_direct["actiune"] = "arata_vreme"
        return raspuns_direct

    # Calea standard (conversație + Tool Calling pentru cereri subtile sau alte acțiuni)
    raspuns_robot = _trimite_la_gemini(text, limba)
    actiune = raspuns_robot.get("actiune", "vorbeste_normal")

    if actiune == "arata_vreme":
        oras_extras = raspuns_robot.get("parametru", "")
        oras_tinta = oras_extras if oras_extras else "Timișoara"
        raport_date = get_weather(oras_tinta)

        prompt_ascuns = (
            f"[SISTEM - DATE METEO PENTRU {oras_tinta}]:\n{raport_date}\n\n"
            f"Formulează răspunsul final în maxim 2-3 propoziții scurte și naturale, cu personalitate! "
            f"Pune acțiunea pe 'vorbeste_normal'."
        )
        raspuns_final = _trimite_la_gemini(prompt_ascuns, limba)
        raspuns_robot["mesaj"] = raspuns_final.get("mesaj", "Nu am putut citi prognoza.")
        raspuns_robot["mesaj_audio"] = raspuns_final.get("mesaj_audio") or raspuns_robot["mesaj"]
        raspuns_robot["actiune"] = "arata_vreme"

    return raspuns_robot

if __name__ == "__main__":
    print("🧠 Creierul a pornit.")
    print("Salut generat de AI:", genereaza_salut_pornire())