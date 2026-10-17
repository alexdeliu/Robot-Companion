import json
import time
import urllib.parse
import urllib.request

_WIKI_CACHE = {}
_ULTIMUL_ARTICOL = {"titlu": "", "paragrafe": [], "index": 0, "imagine": "", "url": ""}

HEADERS_WIKI = {"User-Agent": "RobotCompanionPi/1.0 (Timisoara; Educational Python Project)"}


def _cerere_json(url):
    req = urllib.request.Request(url, headers=HEADERS_WIKI)
    with urllib.request.urlopen(req, timeout=4) as rasp:
        return json.loads(rasp.read().decode("utf-8"))


def cauta_wikipedia(subiect, limba="ro"):
    """
    Caută cel mai relevant articol pe Wikipedia, tratează paginile de dezambiguizare
    și returnează primele 2-3 propoziții + metadate pentru cardul vizual din UI.
    """
    global _ULTIMUL_ARTICOL
    termen = subiect.strip()
    if not termen:
        return {"eroare": "Nu mi-ai spus ce subiect să caut pe Wikipedia."}

    cheie_cache = f"{limba}:{termen.lower()}"
    if cheie_cache in _WIKI_CACHE and (time.time() - _WIKI_CACHE[cheie_cache][0] < 900):
        return _WIKI_CACHE[cheie_cache][1]

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

                # Dacă e pagină de dezambiguizare, trecem automat la următorul rezultat relevant
                if sum_data.get("type") == "disambiguation":
                    continue

                extract = sum_data.get("extract", "").strip()
                if not extract:
                    continue

                propozitii = [p.strip() for p in extract.split(". ") if p.strip()]
                rezumat_scurt = ". ".join(propozitii[:3])
                if not rezumat_scurt.endswith("."):
                    rezumat_scurt += "."

                restul = ". ".join(propozitii[3:])
                info_card = {
                    "titlu": sum_data.get("title", titlu_gasit),
                    "rezumat": rezumat_scurt,
                    "imagine": sum_data.get("thumbnail", {}).get("source", ""),
                    "url": sum_data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                    "limba": cod_limba
                }

                _ULTIMUL_ARTICOL = {
                    "titlu": info_card["titlu"],
                    "paragrafe": [ restul ] if restul else [],
                    "index": 0,
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
    """Returnează continuarea articolului curent când utilizatorul spune 'Spune-mi mai mult'."""
    global _ULTIMUL_ARTICOL
    if not _ULTIMUL_ARTICOL["titlu"]:
        return "Nu avem niciun articol Wikipedia deschis în acest moment."
    idx = _ULTIMUL_ARTICOL["index"]
    if idx < len(_ULTIMUL_ARTICOL["paragrafe"]) and _ULTIMUL_ARTICOL["paragrafe"][idx]:
        _ULTIMUL_ARTICOL["index"] += 1
        return f"Despre {_ULTIMUL_ARTICOL['titlu']}: {_ULTIMUL_ARTICOL['paragrafe'][idx]}"
    return f"Acestea au fost toate informațiile din rezumatul despre {_ULTIMUL_ARTICOL['titlu']}."