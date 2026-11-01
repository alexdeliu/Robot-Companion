import re
import time
import threading

_TIMERE_ACTIVE = []
_CALLBACK_EXPIRARE = None
_LOCK_TIMERE = threading.Lock()

# Google STT scrie des numerele în litere și fără cratimă; textul se compară fără diacritice
_FARA_DIACRITICE = str.maketrans("ăâîșşțţ", "aaisstt")

_NUMERE_RO = {
    "o": 1, "un": 1, "una": 1, "unu": 1, "doi": 2, "doua": 2, "trei": 3, "patru": 4, "cinci": 5,
    "sase": 6, "sapte": 7, "opt": 8, "noua": 9, "zece": 10, "unsprezece": 11, "doisprezece": 12,
    "douasprezece": 12, "treisprezece": 13, "paisprezece": 14, "cincisprezece": 15, "saisprezece": 16,
    "saptesprezece": 17, "optsprezece": 18, "nouasprezece": 19, "douazeci": 20, "treizeci": 30,
    "patruzeci": 40, "cincizeci": 50, "saizeci": 60
}
_ZECI_RO = "douazeci|treizeci|patruzeci|cincizeci"
_UNITATI_RO = "unu|una|doi|doua|trei|patru|cinci|sase|sapte|opt|noua"
_NUMERE_LITERE = "|".join(sorted(_NUMERE_RO, key=len, reverse=True))

_REGEX_DURATA = re.compile(
    rf"\b(\d+|(?:{_ZECI_RO})\s+si\s+(?:{_UNITATI_RO})|{_NUMERE_LITERE})"
    r"(?:\s+de)?\s*(secund\w*|minut\w*|ora\b|ore\b)"
)


def seteaza_callback_alarma(cb):
    global _CALLBACK_EXPIRARE
    _CALLBACK_EXPIRARE = cb


def _valoare_numar(text_numar):
    if text_numar.isdigit():
        return int(text_numar)
    return sum(_NUMERE_RO[parte] for parte in re.split(r"\s+si\s+", text_numar))


def _eticheta_durata(val, singular, plural):
    if val == 1:
        return singular
    de = "de " if val >= 20 and not 1 <= val % 100 <= 19 else ""
    return f"{val} {de}{plural}"


def _extrage_durata(t):
    """Primește textul fără diacritice și returnează (secunde, eticheta) sau None dacă nu există o durată."""
    if re.search(r"\btrei sferturi de ora\b", t):
        return 2700, "trei sferturi de oră"
    if re.search(r"\bsfert de ora\b", t):
        return 900, "un sfert de oră"
    if re.search(r"\bjumatate de ora\b", t):
        return 1800, "o jumătate de oră"

    m = _REGEX_DURATA.search(t)
    if not m:
        return None

    val = _valoare_numar(m.group(1))
    unit = m.group(2)
    if unit.startswith("or"):
        secunde = val * 3600
        eticheta = _eticheta_durata(val, "o oră", "ore")
        if re.match(r"\s+si\s+jumatate\b", t[m.end():]):
            secunde += 1800
            eticheta += " și jumătate"
    elif unit.startswith("minut"):
        secunde = val * 60
        eticheta = _eticheta_durata(val, "un minut", "minute")
    else:
        secunde = val
        eticheta = _eticheta_durata(val, "o secundă", "secunde")
    return secunde, eticheta


def extrage_si_porneste_timer(text):
    """
    Parsează comenzi de tipul: 'pune un timer de 5 minute', 'alarma peste 30 secunde',
    'pune un timer de cinci minute', 'cronometru de jumătate de oră'.
    Returnează mesajul de confirmare sau None dacă textul nu e o comandă de timer.
    """
    t = text.lower().translate(_FARA_DIACRITICE)
    if not any(k in t for k in ("timer", "cronometru", "alarma", "aminteste-mi peste", "aminteste mi peste")):
        return None

    durata = _extrage_durata(t)
    if not durata:
        return None

    secunde, eticheta = durata
    secunde = max(3, min(86400, secunde))
    tinta = time.time() + secunde
    info_t = {"eticheta": eticheta, "tinta": tinta, "activ": True}
    with _LOCK_TIMERE:
        _TIMERE_ACTIVE.append(info_t)

    def _worker_timer():
        time.sleep(secunde)
        if info_t["activ"]:
            info_t["activ"] = False
            if _CALLBACK_EXPIRARE:
                _CALLBACK_EXPIRARE(f"Atenție! A expirat timpul de {eticheta}!")

    threading.Thread(target=_worker_timer, name=f"Timer-{eticheta}", daemon=True).start()
    return f"Am pornit un cronometru pentru {eticheta}."


def opreste_toate_timerele():
    with _LOCK_TIMERE:
        for t in _TIMERE_ACTIVE:
            t["activ"] = False
        _TIMERE_ACTIVE.clear()