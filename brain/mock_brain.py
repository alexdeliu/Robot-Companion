def genereaza_salut_pornire(limba="ro", on_text_chunk=None, on_propozitie=None):
    salut = "Salut! Rulez în modul offline de test (Mock Brain)."
    if on_text_chunk:
        on_text_chunk(salut)
    if on_propozitie:
        on_propozitie(salut)
    return {"actiune": "vorbeste_normal", "parametru": "", "mesaj": salut}


def proceseaza_comanda_ai(text, limba="ro", on_text_chunk=None, on_propozitie=None):
    t = text.lower()
    if "vreme" in t or "weather" in t:
        rasp = {"actiune": "arata_vreme", "parametru": "Timișoara", "mesaj": "În Timișoara sunt 20°C și cer senin (mod test)."}
    elif "glum" in t or "joke" in t:
        rasp = {"actiune": "spune_gluma", "parametru": "", "mesaj": "Ce face un hacker pe barcă? Piraterie!"}
    else:
        rasp = {"actiune": "vorbeste_normal", "parametru": "", "mesaj": f"Am recepționat în modul test: {text}"}

    if on_text_chunk:
        on_text_chunk(rasp["mesaj"])
    if on_propozitie:
        on_propozitie(rasp["mesaj"])
    return rasp