import os
import re
import json
import shutil
import subprocess
import urllib.parse
import urllib.request
from dotenv import load_dotenv

load_dotenv()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

_ULTIMELE_REZULTATE_YT = []
_INDEX_CURENT_YT = 0
_MOD_CURENT_MUZICA = False
_PROCES_BROWSER_YT = None
_VOLUM_CURENT = 95

HEADERS_WEB = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7"
}


def seteaza_volum_sistem(procent):
    """Reglează volumul în ALSA pe Raspberry Pi."""
    global _VOLUM_CURENT
    _VOLUM_CURENT = max(10, min(100, int(procent)))
    if os.name != "nt" and shutil.which("amixer"):
        for control in ("PCM", "Master", "Headphone"):
            subprocess.run(
                ["amixer", "set", control, f"{_VOLUM_CURENT}%"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
    return _VOLUM_CURENT


def schimba_volum_relativ(delta):
    return seteaza_volum_sistem(_VOLUM_CURENT + delta)


def _cauta_youtube_fara_cheie(interogare, max_rezultate=5):
    """Caută direct pe YouTube fără a necesita YOUTUBE_API_KEY."""
    q_enc = urllib.parse.quote(interogare.strip())
    url = f"https://www.youtube.com/results?search_query={q_enc}&hl=ro"
    req = urllib.request.Request(url, headers=HEADERS_WEB)
    with urllib.request.urlopen(req, timeout=5) as rasp:
        html = rasp.read().decode("utf-8", errors="ignore")

    m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});</script>", html)
    if not m:
        return []

    date = json.loads(m.group(1))
    sectiuni = (
        date.get("contents", {})
        .get("twoColumnSearchResultsRenderer", {})
        .get("primaryContents", {})
        .get("sectionListRenderer", {})
        .get("contents", [])
    )

    rezultate = []
    for sectiune in sectiuni:
        items = sectiune.get("itemSectionRenderer", {}).get("contents", [])
        for item in items:
            v = item.get("videoRenderer")
            if not v:
                continue
            vid_id = v.get("videoId", "")
            if not vid_id:
                continue
            runs_titlu = v.get("title", {}).get("runs", [])
            titlu = runs_titlu[0].get("text", "Fără titlu") if runs_titlu else "Fără titlu"
            runs_canal = v.get("ownerText", {}).get("runs", [])
            canal = runs_canal[0].get("text", "YouTube") if runs_canal else "YouTube"
            durata = v.get("lengthText", {}).get("simpleText", "Video")
            thumbs = v.get("thumbnail", {}).get("thumbnails", [])
            miniatura = thumbs[-1].get("url", "") if thumbs else f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"

            rezultate.append({
                "numar": len(rezultate) + 1,
                "video_id": vid_id,
                "titlu": titlu,
                "canal": canal,
                "durata": durata,
                "miniatura": miniatura
            })
            if len(rezultate) >= max_rezultate:
                return rezultate
    return rezultate


def cauta_youtube_oficial(interogare, doar_muzica=False, max_rezultate=5):
    global _ULTIMELE_REZULTATE_YT, _MOD_CURENT_MUZICA
    _MOD_CURENT_MUZICA = doar_muzica
    termen = f"{interogare.strip()} official audio" if doar_muzica else interogare.strip()

    if YOUTUBE_API_KEY:
        try:
            q_enc = urllib.parse.quote(termen)
            cat_param = "&videoCategoryId=10" if doar_muzica else ""
            url = (
                f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
                f"&maxResults={max_rezultate}&q={q_enc}{cat_param}&key={YOUTUBE_API_KEY}"
            )
            with urllib.request.urlopen(url, timeout=4) as rasp:
                date = json.loads(rasp.read().decode("utf-8"))

            rezultate = []
            for idx, item in enumerate(date.get("items", []), start=1):
                vid_id = item.get("id", {}).get("videoId", "")
                snip = item.get("snippet", {})
                if not vid_id:
                    continue
                rezultate.append({
                    "numar": idx,
                    "video_id": vid_id,
                    "titlu": snip.get("title", "Fără titlu"),
                    "canal": snip.get("channelTitle", "YouTube"),
                    "durata": "Video",
                    "miniatura": snip.get("thumbnails", {}).get("medium", {}).get("url", "")
                })
            if rezultate:
                _ULTIMELE_REZULTATE_YT = rezultate
                return rezultate
        except Exception as e:
            print(f"[AVERTISMENT YOUTUBE API]: {e}, folosesc căutarea directă...")

    try:
        rezultate = _cauta_youtube_fara_cheie(termen, max_rezultate=max_rezultate)
        _ULTIMELE_REZULTATE_YT = rezultate
        return rezultate
    except Exception as e:
        print(f"[EROARE CĂUTARE YOUTUBE]: {e}")
        return []


def deschide_overlay_youtube(video_id, mod_muzica=False):
    global _PROCES_BROWSER_YT, _INDEX_CURENT_YT
    inchide_overlay_youtube()
    url_watch = f"https://www.youtube.com/embed/{video_id}?autoplay=1&rel=0"

    for idx, item in enumerate(_ULTIMELE_REZULTATE_YT):
        if item["video_id"] == video_id:
            _INDEX_CURENT_YT = idx
            break

    if os.name == "nt":
        import webbrowser
        webbrowser.open(url_watch)
        return True

    for cmd_browser in ("chromium-browser", "chromium"):
        if shutil.which(cmd_browser):
            args = [cmd_browser, f"--app={url_watch}", "--autoplay-policy=no-user-gesture-required"]
            if mod_muzica:
                args.append("--window-size=200,120")
                args.append("--window-position=2000,2000")
            else:
                args.append("--start-fullscreen")
            _PROCES_BROWSER_YT = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
    return False


def reda_rezultat_dupa_numar(numar_1_5):
    if not _ULTIMELE_REZULTATE_YT:
        return None
    idx = max(0, min(len(_ULTIMELE_REZULTATE_YT) - 1, int(numar_1_5) - 1))
    ales = _ULTIMELE_REZULTATE_YT[idx]
    deschide_overlay_youtube(ales["video_id"], mod_muzica=_MOD_CURENT_MUZICA)
    return ales


def piesa_urmatoare():
    global _INDEX_CURENT_YT
    if not _ULTIMELE_REZULTATE_YT:
        return None
    _INDEX_CURENT_YT = (_INDEX_CURENT_YT + 1) % len(_ULTIMELE_REZULTATE_YT)
    ales = _ULTIMELE_REZULTATE_YT[_INDEX_CURENT_YT]
    deschide_overlay_youtube(ales["video_id"], mod_muzica=_MOD_CURENT_MUZICA)
    return ales


def piesa_anterioara():
    global _INDEX_CURENT_YT
    if not _ULTIMELE_REZULTATE_YT:
        return None
    _INDEX_CURENT_YT = (_INDEX_CURENT_YT - 1) % len(_ULTIMELE_REZULTATE_YT)
    ales = _ULTIMELE_REZULTATE_YT[_INDEX_CURENT_YT]
    deschide_overlay_youtube(ales["video_id"], mod_muzica=_MOD_CURENT_MUZICA)
    return ales


def inchide_overlay_youtube():
    global _PROCES_BROWSER_YT
    if _PROCES_BROWSER_YT and _PROCES_BROWSER_YT.poll() is None:
        try:
            _PROCES_BROWSER_YT.terminate()
        except Exception:
            pass
        _PROCES_BROWSER_YT = None