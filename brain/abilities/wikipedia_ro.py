import re
import json
import time
import urllib.parse
import urllib.request

_WIKI_CACHE = {}
_ULTIMUL_ARTICOL = {
    "titlu": "",
    "paragrafe": [],
    "index": 0,
    "imagine": "",
    "url": ""
}

HEADERS_WIKI = {
    "User-Agent": "RobotCompanionPi/2.0 (Timisoara; Educational Python Project)"
}

# Împarte în propoziții, dar ignoră abrevierile uzuale (n., d., sec., nr., cca., șt., dr., etc.)
_REGEX_SPLIT_WIKI = re.compile(
    r"(?<!\bn)(?<!\bd)(?<!\bsec)(?<!\bnr)(?<!\bcca)(?<!\bdr)(?<!\bprof)(?<!\bart)(?<!\bvol)"
    r"(?<=[.!?])\s+(?=[A-ZĂÂÎȘȚ0-9])"
)


def _cerere_json(url):
    req = urllib.request.Request(url, headers=HEADERS_WIKI)
    with urllib.request.urlopen(req, timeout=5) as rasp:
        return json.loads(rasp.read().decode("utf-8"))


def _curata_paranteze_fonetice(text):
    """Elimină parantezele goale sau cu pronunții IPA greu de citit, păstrând anii și explicațiile."""
    text = re.sub(r"\s*\([^)]*AFI[^)]*\)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _imparte_in_fragmente(text_complet, propozitii_per_fragment=3):
    text_curat = _curata_paranteze_fonetice(text_complet)
    propozitii = [p.strip() for p in _REGEX_SPLIT_WIKI.split(text_curat) if len(p.strip()) > 3]
    if not propozitii:
        return [text_curat] if text_curat else []

    fragmente = []
    for i in range(0, len(propozitii), propozitii_per_fragment):
        grup = " ".join(propozitii[i:i + propozitii_per_fragment]).strip()
        if not grup.endswith((".", "!", "?")):
            grup += "."
        fragmente.append(grup)
    return fragmente


def cauta_wikipedia(subiect, limba="ro"):
    """
    Caută cel mai relevant articol pe Wikipedia (ro -> fallback en),
    extrage rezumatul extins pe mai multe părți pentru 'Spune-mi mai mult'
    și returnează datele pentru Cardul Vizual Wikipedia.
    """
    global _ULTIMUL_ARTICOL
    termen = re.sub(
        r"^(caută pe wikipedia|wikipedia|cine a fost|cine este|ce este|spune-mi despre|despre)\s+",
        "",
        subiect.strip(),
        flags=re.IGNORECASE
    ).strip(" ?!.,")

    if not termen:
        return {"eroare": "Nu mi-ai spus ce subiect să caut pe Wikipedia."}

    cheie_cache = f"{limba}:{termen.lower()}"
    if cheie_cache in _WIKI_CACHE and (time.time() - _WIKI_CACHE[cheie_cache][0] < 900):
        info_salvat = _WIKI_CACHE[cheie_cache][1]
        _ULTIMUL_ARTICOL = {
            "titlu": info_salvat["titlu"],
            "paragrafe": info_salvat["toate_partile"],
            "index": 1,
            "imagine": info_salvat["imagine"],
            "url": info_salvat["url"]
        }
        return info_salvat

    for cod_limba in ([limba, "en"] if limba == "ro" else [limba]):
        try:
            q_enc = urllib.parse.quote(termen)
            search_url = (
                f"https://{cod_limba}.wikipedia.org/w/api.php?action=query&list=search"
                f"&srsearch={q_enc}&srlimit=3&format=json"
            )
            date_search = _cerere_json(search_url)
            rezultate = date_search.get("query", {}).get("search", [])
            if not rezultate:
                continue

            for item in rezultate:
                titlu_gasit = item["title"]
                titlu_enc = urllib.parse.quote(titlu_gasit.replace(" ", "_"))
                sum_url = f"https://{cod_limba}.wikipedia.org/api/rest_v1/page/summary/{titlu_enc}"
                sum_data = _cerere_json(sum_url)

                if sum_data.get("type") == "disambiguation":
                    continue

                # Preluăm textul introductiv extins (mai multe paragrafe) pentru ca 'Spune-mi mai mult' să aibă conținut bogat
                ext_url = (
                    f"https://{cod_limba}.wikipedia.org/w/api.php?action=query&prop=extracts"
                    f"&exintro=1&explaintext=1&titles={titlu_enc}&format=json"
                )
                ext_data = _cerere_json(ext_url)
                pages = ext_data.get("query", {}).get("pages", {})
                extract_lung = ""
                for _, page_obj in pages.items():
                    extract_lung = page_obj.get("extract", "").strip()
                    break

                text_baza = extract_lung if len(extract_lung) > len(sum_data.get("extract", "")) else sum_data.get("extract", "").strip()
                if not text_baza:
                    continue

                fragmente = _imparte_in_fragmente(text_baza, propozitii_per_fragment=3)
                if not fragmente:
                    continue

                info_card = {
                    "titlu": sum_data.get("title", titlu_gasit),
                    "rezumat": fragmente[0],
                    "partea_curenta": 1,
                    "total_parti": len(fragmente),
                    "toate_partile": fragmente,
                    "imagine": sum_data.get("thumbnail", {}).get("source", ""),
                    "url": sum_data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                    "limba": cod_limba
                }

                _ULTIMUL_ARTICOL = {
                    "titlu": info_card["titlu"],
                    "paragrafe": fragmente,
                    "index": 1,
                    "imagine": info_card["imagine"],
                    "url": info_card["url"]
                }
                _WIKI_CACHE[cheie_cache] = (time.time(), info_card)
                return info_card

        except Exception as e:
            print(f"[AVERTISMENT WIKIPEDIA ({cod_limba})]: {e}")
            continue

    return {"eroare": f"Nu am găsit niciun articol pe Wikipedia despre {termen}."}


def continua_wikipedia():
    """Returnează următorul fragment din articolul curent și metadatele actualizate pentru Cardul UI."""
    global _ULTIMUL_ARTICOL
    if not _ULTIMUL_ARTICOL["titlu"] or not _ULTIMUL_ARTICOL["paragrafe"]:
        msg = "Nu avem niciun articol Wikipedia deschis în acest moment."
        return {"mesaj": msg, "date_ui": None}

    idx = _ULTIMUL_ARTICOL["index"]
    total = len(_ULTIMUL_ARTICOL["paragrafe"])

    if idx < total:
        text_nou = _ULTIMUL_ARTICOL["paragrafe"][idx]
        _ULTIMUL_ARTICOL["index"] += 1
        card_actualizat = {
            "titlu": _ULTIMUL_ARTICOL["titlu"],
            "rezumat": text_nou,
            "partea_curenta": idx + 1,
            "total_parti": total,
            "imagine": _ULTIMUL_ARTICOL["imagine"],
            "url": _ULTIMUL_ARTICOL["url"]
        }
        return {"mesaj": text_nou, "date_ui": card_actualizat}

    msg_final = f"Am ajuns la finalul rezumatului Wikipedia despre {_ULTIMUL_ARTICOL['titlu']}."
    return {"mesaj": msg_final, "date_ui": None}