import os
import re
import time
import random
import threading
from datetime import datetime
from google import genai
from google.genai import types
from dotenv import load_dotenv

from brain.abilities.weather import get_weather

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
DEBUG = os.getenv("DEBUG", "1") == "1"

# Client cu timeout explicit (6000 ms = 6s) pentru a evita blocajele de 20s pe conexiuni aglomerate
client = genai.Client(
    api_key=API_KEY,
    http_options=types.HttpOptions(timeout=6000)
)

# Modele reale, ordonate după viteză (Time-To-First-Token minim)
MODEL_PRINCIPAL = "gemini-2.5-flash-lite"
MODELE_REZERVA = ["gemini-2.5-flash", "gemini-2.0-flash"]

instructiuni_sistem = """Ești "Creierul" unui robot companion fizic de birou din Timișoara. Ești prietenos, inteligent, spontan și uneori puțin sarcastic sau glumeț.
Reguli:
1. Răspunde SCURT și natural (1-3 propoziții), în limba română, scris corect ortografic (cu diacritice). NU transcrie cuvintele fonetic.
2. Înțelegi româna și engleza. Dedu intenția logică dacă transcrierea vocală are mici erori.
3. Începe răspunsul cu UN SINGUR tag între paranteze drepte, urmat imediat de textul vorbit:
   - Pentru conversație normală: [vorbeste_normal] Răspunsul tău...
   - Pentru o glumă: [spune_gluma] Răspunsul tău...
   - Pentru vreme (doar dacă NU ai deja [DATE METEO] în mesaj): [arata_vreme:Oraș]
   - Pentru YouTube video: [reda_youtube:căutare] Răspunsul tău...
   - Pentru muzică: [reda_muzica:melodie] Răspunsul tău..."""

istoric_conversatie = []
_istoric_lock = threading.Lock()

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

CUVINTE_EXCLUSE_ORAS = {
    "azi", "mâine", "maine", "weekend", "seara", "dimineața", "dimineata", "românia",
    "romania", "mine", "tine", "noi", "voi", "el", "ea", "acasa", "acasă", "birou",
    "afară", "afara", "oraș", "oras", "camera", "cameră", "zile", "săptămâna"
}

_REGEX_TAG = re.compile(r"^\s*\[([a-z_]+)(?::([^\]]*))?\]\s*", re.IGNORECASE)
_REGEX_SPLIT_PROPOZITIE = re.compile(r"(?<=[.!?])\s+")


def _detecteaza_oras_rapid(text):
    text_mic = text.lower()
    for oras in ORASE_CUNOSCUTE:
        if re.search(rf"\b{re.escape(oras)}\b", text_mic):
            return oras.capitalize()
    match = re.search(r"\b(?:în|in|la|pentru)\s+([A-ZĂÂÎȘȚa-zăâîșț\-]{3,})\b", text)
    if match:
        cuvant = match.group(1)
        if cuvant.lower() not in CUVINTE_EXCLUSE_ORAS:
            return cuvant.capitalize()
    return "Timișoara"


def _config_rapid(temperatura=0.7):
    return types.GenerateContentConfig(
        system_instruction=instructiuni_sistem,
        temperature=temperatura,
        max_output_tokens=280,
        thinking_config=types.ThinkingConfig(thinking_budget=0)
    )


def _stream_de_la_gemini(prompt_text, temperatura=0.7, salveaza_istoric=True, on_text_chunk=None, on_propozitie=None):
    """
    Streaming LLM cu latență minimă (thinking_budget=0), fallback automat la 503/timeout
    și trimitere simultană către UI (on_text_chunk) și TTS (on_propozitie).
    """
    global istoric_conversatie
    t0 = time.perf_counter()

    mesaj_user = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt_text)]
    )
    with _istoric_lock:
        continut_apel = list(istoric_conversatie) + [mesaj_user]

    config_ai = _config_rapid(temperatura)
    toate_modelele = [MODEL_PRINCIPAL] + MODELE_REZERVA

    for model_curent in toate_modelele:
        try:
            t_first_token = None
            buffer_complet = ""
            buffer_propozitii = ""
            tag_parsat = False
            actiune = "vorbeste_normal"
            parametru = ""
            text_afisat = ""

            stream = client.models.generate_content_stream(
                model=model_curent,
                contents=continut_apel,
                config=config_ai
            )

            for chunk in stream:
                bucata = chunk.text or ""
                if not bucata:
                    continue
                if t_first_token is None:
                    t_first_token = time.perf_counter() - t0

                buffer_complet += bucata

                if not tag_parsat:
                    if "]" in buffer_complet or len(buffer_complet) > 35:
                        m = _REGEX_TAG.match(buffer_complet)
                        if m:
                            actiune = m.group(1).lower()
                            parametru = (m.group(2) or "").strip()
                            rest = buffer_complet[m.end():]
                        else:
                            rest = buffer_complet.lstrip()
                        tag_parsat = True
                        if actiune == "arata_vreme" and not rest:
                            break
                        if rest:
                            text_afisat += rest
                            buffer_propozitii += rest
                            if on_text_chunk:
                                on_text_chunk(rest)
                else:
                    text_afisat += bucata
                    buffer_propozitii += bucata
                    if on_text_chunk:
                        on_text_chunk(bucata)

                # Trimitem fiecare propoziție completă direct spre TTS cât timp LLM încă scrie!
                if tag_parsat and on_propozitie and actiune != "arata_vreme":
                    parti = _REGEX_SPLIT_PROPOZITIE.split(buffer_propozitii)
                    if len(parti) > 1:
                        for prop in parti[:-1]:
                            if prop.strip():
                                on_propozitie(prop.strip())
                        buffer_propozitii = parti[-1]

            # Dacă răspunsul a fost foarte scurt și nu a ajuns la35 caractere fără ']'
            if not tag_parsat and buffer_complet.strip():
                m = _REGEX_TAG.match(buffer_complet)
                if m:
                    actiune = m.group(1).lower()
                    parametru = (m.group(2) or "").strip()
                    text_afisat = buffer_complet[m.end():].strip()
                else:
                    text_afisat = buffer_complet.strip()
                if text_afisat and on_text_chunk:
                    on_text_chunk(text_afisat)
                buffer_propozitii = text_afisat

            if on_propozitie and buffer_propozitii.strip() and actiune != "arata_vreme":
                on_propozitie(buffer_propozitii.strip())

            t_total = time.perf_counter() - t0
            if DEBUG:
                ttft_s = f"{t_first_token:.2f}s" if t_first_token is not None else "N/A"
                print(f"[TIMPI DEBUG | {model_curent}]: TTFT={ttft_s} | LLM Total={t_total:.2f}s")

            text_final = text_afisat.strip()
            if salveaza_istoric and text_final:
                with _istoric_lock:
                    istoric_conversatie.append(mesaj_user)
                    istoric_conversatie.append(
                        types.Content(
                            role="model",
                            parts=[types.Part.from_text(text=f"[{actiune}] {text_final}")]
                        )
                    )
                    if len(istoric_conversatie) > 8:
                        istoric_conversatie = istoric_conversatie[-8:]

            return {
                "actiune": actiune,
                "parametru": parametru,
                "mesaj": text_final
            }

        except Exception as e:
            if DEBUG:
                print(f"[FALLBACK AI]: {model_curent} a eșuat ({e}). Trec imediat pe următorul model...")
            continue

    aglom = "Serverele mele sunt cam aglomerate în clipa asta. Mai încearcă în câteva secunde!"
    if on_text_chunk:
        on_text_chunk(aglom)
    if on_propozitie:
        on_propozitie(aglom)
    return {"actiune": "eroare", "parametru": "", "mesaj": aglom}


def genereaza_salut_pornire(limba="ro", on_text_chunk=None, on_propozitie=None):
    """100% AI Dinamic cu streaming direct la pornire."""
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
        f"fă o remarcă scurtă și originală legată de faptul că e {moment_zi} (ora {ora_str})",
        "fă o glumă scurtă despre circuitele tale, curentul electric sau microfonul tău",
        "întreabă utilizatorul într-un mod original și neașteptat ce misiune are pentru tine",
        "comentează amuzant despre faptul că ești gata de vorbă pe biroul din Timișoara"
    ]

    stare_aleasa = random.choice(stari_personalitate)
    tema_aleasa = random.choice(teme_creative)
    seed_unic = random.randint(1000, 9999)

    prompt_salut = (
        f"[SISTEM - PORNIRE #{seed_unic}] Tocmai ai fost pornit la ora {ora_str} ({moment_zi}). "
        f"Starea ta: {stare_aleasa}. În maxim 2 propoziții scurte, {tema_aleasa}. "
        f"Începe cu [vorbeste_normal]."
    )

    return _stream_de_la_gemini(
        prompt_salut,
        temperatura=0.9,
        salveaza_istoric=True,
        on_text_chunk=on_text_chunk,
        on_propozitie=on_propozitie
    )


genereaza_mesaj_bun_venit = genereaza_salut_pornire


def proceseaza_comanda_ai(text, limba="ro", on_text_chunk=None, on_propozitie=None):
    """
    Procesează comanda cu Streaming în UI și TTS.
    Include One-Shot Weather și fallback la Tool Calling pentru cereri meteo implicite.
    """
    if CUVINTE_CHEIE_METEO.search(text):
        oras_detectat = _detecteaza_oras_rapid(text)
        raport_date = get_weather(oras_detectat)
        prompt_direct = (
            f"Utilizatorul a întrebat: \"{text}\"\n"
            f"[DATE METEO REALE PENTRU {oras_detectat.upper()}]:\n{raport_date}\n"
            f"Răspunde direct și natural în 1-3 propoziții scurte, cu personalitatea ta! Începe cu [vorbeste_normal]."
        )
        rez = _stream_de_la_gemini(
            prompt_direct,
            temperatura=0.7,
            salveaza_istoric=True,
            on_text_chunk=on_text_chunk,
            on_propozitie=on_propozitie
        )
        rez["actiune"] = "arata_vreme"
        return rez

    raspuns_robot = _stream_de_la_gemini(
        text,
        temperatura=0.75,
        salveaza_istoric=True,
        on_text_chunk=on_text_chunk,
        on_propozitie=on_propozitie
    )

    if raspuns_robot.get("actiune") == "arata_vreme":
        oras_tinta = raspuns_robot.get("parametru") or "Timișoara"
        raport_date = get_weather(oras_tinta)
        prompt_ascuns = (
            f"[DATE METEO PENTRU {oras_tinta}]:\n{raport_date}\n"
            f"Formulează răspunsul final în 1-3 propoziții scurte și naturale! Începe cu [vorbeste_normal]."
        )
        raspuns_final = _stream_de_la_gemini(
            prompt_ascuns,
            temperatura=0.7,
            salveaza_istoric=True,
            on_text_chunk=on_text_chunk,
            on_propozitie=on_propozitie
        )
        raspuns_final["actiune"] = "arata_vreme"
        return raspuns_final

    return raspuns_robot