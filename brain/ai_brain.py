import os
import re
import time
import random
import threading
from datetime import datetime
from google import genai
from google.genai import types

from config import GEMINI_API_KEY, MODEL_PRINCIPAL, MODELE_REZERVA, GEMINI_TIMEOUT_MS, CFG, DEBUG, APP_VERSION
from system_health import logger, citeste_stare_hardware
from brain.abilities.weather import get_weather
from brain.abilities.wikipedia_ro import cauta_wikipedia, continua_wikipedia
from brain.abilities.timers import extrage_si_porneste_timer
from brain.abilities.youtube_player import (
    cauta_youtube_oficial,
    selecteaza_meta_dupa_numar,
    reda_rezultat_dupa_numar,
    inchide_overlay_youtube,
    piesa_urmatoare,
    piesa_anterioara,
    seteaza_volum_sistem,
    schimba_volum_relativ
)

_client_gemini = None


def _obtine_client_gemini():
    global _client_gemini
    if _client_gemini is not None:
        return _client_gemini
    cheie = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "").strip()
    if not cheie or "PUNE_CHEIA" in cheie:
        raise RuntimeError("GEMINI_API_KEY lipsește din .env")
    _client_gemini = genai.Client(
        api_key=cheie,
        http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS)
    )
    return _client_gemini

instructiuni_sistem = """Ești "Creierul" unui robot companion fizic de birou din Timișoara. Ești prietenos, inteligent, spontan și uneori puțin sarcastic sau glumeț.

REGULI CRITICE DE LIMBĂ ȘI ORTOGRAFIE:
1. Răspunde SCURT, cursiv și natural (1-3 propoziții), în limba română literară impecabilă, cu diacritice corecte (ă, â, î, ș, ț).
2. INTERZIS să inventezi cuvinte, să pocești cuvintele în scris sau să transcrii fonetic cuvintele! Scrie toate cuvintele 100% corect ortografic.
3. Înțelegi perfect româna și engleza, dar răspunzi MEREU în limba română.
4. Începe răspunsul cu UN SINGUR tag de acțiune între paranteze drepte, urmat de textul vorbit:
   - Conversație normală: [vorbeste_normal] Răspunsul tău...
   - Glumă: [spune_gluma] Răspunsul tău...
   - Vreme (dacă nu ai deja [DATE METEO]): [arata_vreme:Oraș]
   - Wikipedia / enciclopedie / cine a fost / informații istorice sau științifice: [cauta_wikipedia:Subiect]
   - Continuare articol Wikipedia ("spune-mi mai mult"): [continua_wikipedia]
   - Căutare videoclip YouTube: [reda_youtube:termen căutat] Răspuns scurt...
   - Redare muzică / melodie YouTube Music (dacă utilizatorul nu dă o piesă anume, alege tu o piesă sau un gen popular în parametru!): [reda_muzica:artist sau melodie] Răspuns scurt...
   - Oprire muzică sau videoclip: [opreste_media] Am oprit redarea."""

istoric_conversatie = []
_istoric_lock = threading.Lock()

ZILE_SAPTAMANA_RO = ["luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică"]
LUNI_AN_RO = [
    "", "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
    "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie"
]

CUVINTE_CHEIE_METEO = re.compile(
    r"\b(vreme\w*|plou\w*|ploai\w*|ninge|ninso\w*|grade|cald|frig|ger|soare|înnorat|innorat|"
    r"furtun\w*|vânt\w*|vant\w*|ceață|ceata|prognoz\w*|meteo|weather|rain\w*|snow\w*|sunny|forecast)\b",
    re.IGNORECASE
)

CUVINTE_EXPLICITE_WIKI = re.compile(
    r"(?:caută pe wikipedia|cauta pe wikipedia|pe wikipedia despre|wikipedia)\s+(.+)",
    re.IGNORECASE
)

CUVINTE_MAI_MULT_WIKI = re.compile(
    r"\b(spune-mi mai mult|spune mai mult|mai departe|continuă|continua articolul|detaliază|mai multe detalii)\b",
    re.IGNORECASE
)

CUVINTE_ORA_DATA = re.compile(
    r"\b(cât e ceasul|cat e ceasul|ce oră e|ce ora e|ce oră este|în ce dată suntem|in ce data suntem|ce zi e azi|ce zi este azi)\b",
    re.IGNORECASE
)

CUVINTE_STATUS_SISTEM = re.compile(
    r"\b(status sistem|stare sistem|cât de cald e procesorul|temperatura procesorului|cât ram ai| diagnostic sistem)\b",
    re.IGNORECASE
)

CUVINTE_SELECTIE_YT = {
    "primul": 1, "prima": 1, "unu": 1, "numărul 1": 1, "numarul 1": 1, "varianta 1": 1,
    "al doilea": 2, "a doua": 2, "doi": 2, "numărul 2": 2, "numarul 2": 2, "varianta 2": 2,
    "al treilea": 3, "a treia": 3, "trei": 3, "numărul 3": 3, "numarul 3": 3, "varianta 3": 3,
    "al patrulea": 4, "a patra": 4, "patru": 4, "numărul 4": 4, "numarul 4": 4, "varianta 4": 4,
    "al cincilea": 5, "a cincea": 5, "cinci": 5, "numărul 5": 5, "numarul 5": 5, "varianta 5": 5,
}

CUVINTE_OPRIRE_MEDIA = re.compile(
    r"\b(oprește muzica|opreste muzica|oprește videoclipul|opreste video|închide youtube|inchide youtube|stop youtube|oprește youtube|oprește-te|taci)\b",
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

_REGEX_TAG = re.compile(r"^\s*\[([^\]:]+)(?::([^\]]*))?\]\s*", re.IGNORECASE)


def reseteaza_memorie_ai():
    global istoric_conversatie
    with _istoric_lock:
        istoric_conversatie.clear()


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


def _deschide_stream_model(model_curent, continut_apel, temperatura):
    if "lite" in model_curent:
        cfg = types.GenerateContentConfig(
            system_instruction=instructiuni_sistem,
            temperature=temperatura,
            max_output_tokens=280
        )
    else:
        cfg = types.GenerateContentConfig(
            system_instruction=instructiuni_sistem,
            temperature=temperatura,
            max_output_tokens=280,
            thinking_config=types.ThinkingConfig(thinking_budget=0)
        )
    cli = _obtine_client_gemini()
    if CFG["ai"].get("auto_retry_network", False):
        try:
            return cli.models.generate_content_stream(model=model_curent, contents=continut_apel, config=cfg)
        except Exception as e_net:
            logger.warning(f"[RETRY REȚEA {model_curent}]: {e_net}, reîncerc în 1.2s...")
            time.sleep(1.2)
    return cli.models.generate_content_stream(
        model=model_curent,
        contents=continut_apel,
        config=cfg
    )


def _stream_de_la_gemini(prompt_text, temperatura=0.45, salveaza_istoric=True, text_istoric_user=None, on_text_chunk=None):
    global istoric_conversatie
    t0 = time.perf_counter()

    mesaj_user_apel = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt_text)]
    )
    with _istoric_lock:
        continut_apel = list(istoric_conversatie) + [mesaj_user_apel]

    toate_modelele = [MODEL_PRINCIPAL] + MODELE_REZERVA
    max_ist = int(CFG["ai"].get("max_istoric", 8))

    for model_curent in toate_modelele:
        try:
            t_first_token = None
            buffer_complet = ""
            tag_parsat = False
            actiune = "vorbeste_normal"
            parametru = ""
            text_afisat = ""

            stream = _deschide_stream_model(model_curent, continut_apel, temperatura)

            for chunk in stream:
                bucata = chunk.text or ""
                if not bucata:
                    continue
                if t_first_token is None:
                    t_first_token = time.perf_counter() - t0

                buffer_complet += bucata

                if not tag_parsat:
                    if "]" in buffer_complet or len(buffer_complet) > 40:
                        m = _REGEX_TAG.match(buffer_complet)
                        if m:
                            actiune = m.group(1).strip().lower()
                            parametru = (m.group(2) or "").strip()
                            rest = buffer_complet[m.end():]
                        else:
                            rest = buffer_complet.lstrip()
                        tag_parsat = True
                        if actiune in ("arata_vreme", "cauta_wikipedia", "continua_wikipedia") and not rest:
                            break
                        if rest:
                            text_afisat += rest
                            if on_text_chunk:
                                on_text_chunk(rest)
                else:
                    text_afisat += bucata
                    if on_text_chunk:
                        on_text_chunk(bucata)

            if not tag_parsat and buffer_complet.strip():
                m = _REGEX_TAG.match(buffer_complet)
                if m:
                    actiune = m.group(1).strip().lower()
                    parametru = (m.group(2) or "").strip()
                    text_afisat = buffer_complet[m.end():].strip()
                else:
                    text_afisat = buffer_complet.strip()
                if text_afisat and on_text_chunk and actiune not in ("arata_vreme", "cauta_wikipedia"):
                    on_text_chunk(text_afisat)

            t_total = time.perf_counter() - t0
            if DEBUG:
                ttft_s = f"{t_first_token:.2f}s" if t_first_token is not None else "N/A"
                logger.info(f"[TIMPI DEBUG | {model_curent}]: TTFT={ttft_s} | LLM Total={t_total:.2f}s")

            text_final = text_afisat.strip()
            if salveaza_istoric and text_final:
                text_pt_istoric = text_istoric_user or prompt_text
                with _istoric_lock:
                    istoric_conversatie.append(
                        types.Content(role="user", parts=[types.Part.from_text(text=text_pt_istoric)])
                    )
                    istoric_conversatie.append(
                        types.Content(role="model", parts=[types.Part.from_text(text=f"[{actiune}] {text_final}")])
                    )
                    if len(istoric_conversatie) > max_ist:
                        istoric_conversatie = istoric_conversatie[-max_ist:]

            return {
                "actiune": actiune,
                "parametru": parametru,
                "mesaj": text_final
            }

        except Exception as e:
            logger.warning(f"[FALLBACK AI]: {model_curent} a eșuat ({e}). Trec pe următorul model...")
            continue

    # Mod degradat offline dacă internetul sau toate modelele sunt indisponibile
    acum = datetime.now()
    offline_msg = (
        f"Conexiunea la internet sau la serverele AI este temporar indisponibilă, "
        f"dar comenzile locale funcționează. Este ora {acum.strftime('%H:%M')}."
    )
    if on_text_chunk:
        on_text_chunk(offline_msg)
    return {"actiune": "eroare", "parametru": "", "mesaj": offline_msg}


def genereaza_salut_pornire(limba="ro", on_text_chunk=None, on_propozitie=None):
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
        "morocănos în glumă că tocmai ai fost trezit din somnul digital",
        "sarcastic și simpatic, ca un prieten bun din Timișoara",
        "exagerat de politicos, ca un majordom britanic",
        "super entuziasmat și curios să afle ce facem astăzi"
    ]

    stare_aleasa = random.choice(stari_personalitate)
    seed_unic = random.randint(1000, 9999)

    prompt_salut = (
        f"[SISTEM - PORNIRE #{seed_unic}] Tocmai ai fost pornit la ora {ora_str} ({moment_zi}). "
        f"Starea ta este: {stare_aleasa}. Salută utilizatorul în maxim 2 propoziții scurte și naturale, "
        f"scrise în limba română literară perfectă. Începe cu [vorbeste_normal]."
    )

    return _stream_de_la_gemini(
        prompt_salut,
        temperatura=0.5,
        salveaza_istoric=False,
        on_text_chunk=on_text_chunk
    )


genereaza_mesaj_bun_venit = genereaza_salut_pornire


def proceseaza_comanda_ai(text, limba="ro", on_text_chunk=None, on_propozitie=None):
    text_curat = text.strip()
    text_mic = text_curat.lower()

    # 1. Timere și Alarme vocale (0.0s latență!)
    msg_timer = extrage_si_porneste_timer(text_curat)
    if msg_timer:
        if on_text_chunk:
            on_text_chunk(msg_timer)
        return {"actiune": "vorbeste_normal", "parametru": "", "mesaj": msg_timer}

    # 2. Oră și Dată locală (0.0s latență!)
    if CUVINTE_ORA_DATA.search(text_mic):
        acum = datetime.now()
        zi_nume = ZILE_SAPTAMANA_RO[acum.weekday()]
        luna_nume = LUNI_AN_RO[acum.month]
        msg = f"Este ora {acum.hour} și {acum.minute:02d} minute. Astăzi este {zi_nume}, {acum.day} {luna_nume} {acum.year}."
        if on_text_chunk:
            on_text_chunk(msg)
        return {"actiune": "vorbeste_normal", "parametru": "", "mesaj": msg}

    # 3. Status Sistem Hardware (0.0s latență!)
    if CUVINTE_STATUS_SISTEM.search(text_mic) or "ce versiune" in text_mic:
        st = citeste_stare_hardware()
        msg = (
            f"Rulez versiunea {APP_VERSION}. Temperatura procesorului este de {st['temp_c']}°C, "
            f"iar memoria liberă este de {st['ram_avail_mb']} megabytes din {st['ram_total_mb']}."
        )
        if on_text_chunk:
            on_text_chunk(msg)
        return {"actiune": "arata_status", "parametru": "", "mesaj": msg, "date_ui": st}

    # 4. Reglare Volum prin Comandă Vocală
    if any(k in text_mic for k in ("dă mai tare", "da mai tare", "volum mai mare", "volum maxim", "volumul la maxim")):
        vol = seteaza_volum_sistem(100) if "maxim" in text_mic else schimba_volum_relativ(15)
        msg = f"Am ridicat volumul la {vol}%."
        if on_text_chunk:
            on_text_chunk(msg)
        return {"actiune": "vorbeste_normal", "parametru": "", "mesaj": msg}

    if any(k in text_mic for k in ("dă mai încet", "da mai incet", "volum mai mic", "mai încet")):
        vol = schimba_volum_relativ(-20)
        msg = f"Am redus volumul la {vol}%."
        if on_text_chunk:
            on_text_chunk(msg)
        return {"actiune": "vorbeste_normal", "parametru": "", "mesaj": msg}

    # 5. Control Media Rapid
    if CUVINTE_OPRIRE_MEDIA.search(text_mic):
        inchide_overlay_youtube()
        msg = "Am oprit redarea."
        if on_text_chunk:
            on_text_chunk(msg)
        return {"actiune": "opreste_media", "parametru": "", "mesaj": msg}

    for expresie, nr in CUVINTE_SELECTIE_YT.items():
        if re.search(rf"\b{re.escape(expresie)}\b", text_mic) and len(text_mic.split()) <= 5:
            ales = selecteaza_meta_dupa_numar(nr)
            if ales:
                msg = f"Redau acum opțiunea {nr}: {ales['titlu']}."
                if on_text_chunk:
                    on_text_chunk(msg)
                return {"actiune": "selecteaza_youtube", "parametru": str(nr), "mesaj": msg, "date_ui": ales}

    if any(k in text_mic for k in ("următoarea melodie", "urmatoarea melodie", "piesa următoare", "next song")):
        ales = piesa_urmatoare()
        if ales:
            msg = f"Trec la următoarea piesă: {ales['titlu']}."
            if on_text_chunk:
                on_text_chunk(msg)
            return {"actiune": "reda_muzica", "parametru": ales["titlu"], "mesaj": msg, "date_ui": ales}

    if any(k in text_mic for k in ("melodia anterioară", "piesa anterioară", "previous song")):
        ales = piesa_anterioara()
        if ales:
            msg = f"Revin la piesa anterioară: {ales['titlu']}."
            if on_text_chunk:
                on_text_chunk(msg)
            return {"actiune": "reda_muzica", "parametru": ales["titlu"], "mesaj": msg, "date_ui": ales}

    # 6. Continuare Wikipedia ("Spune-mi mai mult")
    if CUVINTE_MAI_MULT_WIKI.search(text_mic):
        rez_cont = continua_wikipedia()
        msg_cont = rez_cont["mesaj"]
        if on_text_chunk:
            on_text_chunk(msg_cont)
        return {
            "actiune": "cauta_wikipedia" if rez_cont["date_ui"] else "continua_wikipedia",
            "parametru": "",
            "mesaj": msg_cont,
            "date_ui": rez_cont["date_ui"]
        }

    # 7. Căutare explicită Wikipedia
    m_wiki = CUVINTE_EXPLICITE_WIKI.search(text_curat)
    if m_wiki:
        subiect_wiki = m_wiki.group(1).strip()
        info_wiki = cauta_wikipedia(subiect_wiki, limba=limba)
        if "eroare" not in info_wiki:
            if on_text_chunk:
                on_text_chunk(info_wiki["rezumat"])
            return {
                "actiune": "cauta_wikipedia",
                "parametru": info_wiki["titlu"],
                "mesaj": info_wiki["rezumat"],
                "date_ui": info_wiki
            }

    # 8. One-Shot Weather
    if CUVINTE_CHEIE_METEO.search(text_curat):
        oras_detectat = _detecteaza_oras_rapid(text_curat)
        raport_date = get_weather(oras_detectat)
        prompt_direct = (
            f"Utilizatorul a întrebat: \"{text_curat}\"\n"
            f"[DATE METEO REALE PENTRU {oras_detectat.upper()}]:\n{raport_date}\n"
            f"Răspunde direct și natural în 1-3 propoziții scurte, cu personalitatea ta! Începe cu [vorbeste_normal]."
        )
        rez = _stream_de_la_gemini(
            prompt_direct,
            temperatura=0.45,
            salveaza_istoric=True,
            text_istoric_user=text_curat,
            on_text_chunk=on_text_chunk
        )
        rez["actiune"] = "arata_vreme"
        return rez

    # 9. Apelul principal către Gemini
    raspuns_robot = _stream_de_la_gemini(
        text_curat,
        temperatura=0.45,
        salveaza_istoric=True,
        text_istoric_user=text_curat,
        on_text_chunk=on_text_chunk
    )
    actiune = raspuns_robot.get("actiune", "vorbeste_normal")
    parametru = raspuns_robot.get("parametru", "").strip()

    if actiune == "arata_vreme":
        oras_tinta = parametru or "Timișoara"
        raport_date = get_weather(oras_tinta)
        prompt_ascuns = (
            f"[DATE METEO PENTRU {oras_tinta}]:\n{raport_date}\n"
            f"Formulează răspunsul final în 1-3 propoziții scurte și naturale! Începe cu [vorbeste_normal]."
        )
        raspuns_final = _stream_de_la_gemini(
            prompt_ascuns,
            temperatura=0.45,
            salveaza_istoric=True,
            text_istoric_user=text_curat,
            on_text_chunk=on_text_chunk
        )
        raspuns_final["actiune"] = "arata_vreme"
        return raspuns_final

    if actiune == "cauta_wikipedia":
        subiect = parametru or text_curat
        info_wiki = cauta_wikipedia(subiect, limba=limba)
        if "eroare" in info_wiki:
            msg_err = info_wiki["eroare"]
            if on_text_chunk and not raspuns_robot.get("mesaj"):
                on_text_chunk(msg_err)
            return {"actiune": "vorbeste_normal", "parametru": subiect, "mesaj": msg_err}

        rezumat_wiki = info_wiki["rezumat"]
        if on_text_chunk and not raspuns_robot.get("mesaj"):
            on_text_chunk(rezumat_wiki)
        return {
            "actiune": "cauta_wikipedia",
            "parametru": info_wiki["titlu"],
            "mesaj": rezumat_wiki,
            "date_ui": info_wiki
        }

    if actiune == "continua_wikipedia":
        rez_cont = continua_wikipedia()
        msg_cont = rez_cont["mesaj"]
        if on_text_chunk and not raspuns_robot.get("mesaj"):
            on_text_chunk(msg_cont)
        return {
            "actiune": "cauta_wikipedia" if rez_cont["date_ui"] else "continua_wikipedia",
            "parametru": "",
            "mesaj": msg_cont,
            "date_ui": rez_cont["date_ui"]
        }

    if actiune == "reda_youtube":
        cautare = parametru or text_curat
        rezultate = cauta_youtube_oficial(cautare, doar_muzica=False, max_rezultate=5)
        if not rezultate:
            msg = f"Nu am putut găsi videoclipuri pe YouTube pentru {cautare}."
            if on_text_chunk and not raspuns_robot.get("mesaj"):
                on_text_chunk(msg)
            return {"actiune": "vorbeste_normal", "parametru": cautare, "mesaj": msg}

        t1 = rezultate[0]["titlu"]
        t2 = rezultate[1]["titlu"] if len(rezultate) > 1 else ""
        msg_lista = (
            f"Am găsit 5 rezultate pe YouTube pentru {cautare}. "
            f"Primul este {t1}" + (f", iar al doilea este {t2}. " if t2 else ". ") +
            "Spune-mi numărul dorit sau apasă pe ecran!"
        )
        if not raspuns_robot.get("mesaj") and on_text_chunk:
            on_text_chunk(msg_lista)
        return {
            "actiune": "reda_youtube",
            "parametru": cautare,
            "mesaj": msg_lista,
            "date_ui": rezultate
        }

    if actiune == "reda_muzica":
        cautare = parametru if parametru else "hituri românești"
        rezultate = cauta_youtube_oficial(cautare, doar_muzica=True, max_rezultate=5)
        if not rezultate:
            msg = f"Nu am găsit melodia {cautare} pe YouTube Music."
            if on_text_chunk and not raspuns_robot.get("mesaj"):
                on_text_chunk(msg)
            return {"actiune": "vorbeste_normal", "parametru": cautare, "mesaj": msg}

        prima_piesa = rezultate[0]
        msg_muzica = raspuns_robot.get("mesaj") or f"Redau acum {prima_piesa['titlu']} de la {prima_piesa['canal']}."
        if not raspuns_robot.get("mesaj") and on_text_chunk:
            on_text_chunk(msg_muzica)
        return {
            "actiune": "reda_muzica",
            "parametru": cautare,
            "mesaj": msg_muzica,
            "date_ui": prima_piesa
        }

    if actiune == "opreste_media":
        inchide_overlay_youtube()

    return raspuns_robot