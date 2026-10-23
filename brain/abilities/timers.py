import re
import time
import threading

_TIMERE_ACTIVE = []
_CALLBACK_EXPIRARE = None
_LOCK_TIMERE = threading.Lock()


def seteaza_callback_alarma(cb):
    global _CALLBACK_EXPIRARE
    _CALLBACK_EXPIRARE = cb


def extrage_si_porneste_timer(text):
    """
    Parsează comenzi de tipul: 'pune un timer de 5 minute', 'alarma peste 30 secunde'.
    Returnează mesajul de confirmare sau None dacă textul nu e o comandă de timer.
    """
    t = text.lower()
    if not any(k in t for k in ("timer", "cronometru", "alarmă", "alarma", "amintește-mi peste", "aminteste-mi peste")):
        return None

    m = re.search(r"(\d+)\s*(secund\w*|minut\w*|or\w*)", t)
    if not m:
        return None

    val = int(m.group(1))
    unit = m.group(2)
    if unit.startswith("or"):
        secunde = val * 3600
        eticheta = f"{val} ore" if val > 1 else "o oră"
    elif unit.startswith("minut"):
        secunde = val * 60
        eticheta = f"{val} minute" if val > 1 else "un minut"
    else:
        secunde = val
        eticheta = f"{val} secunde"

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