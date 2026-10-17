import os
import json
import shutil
import subprocess
import urllib.parse
import urllib.request
from dotenv import load_dotenv

load_dotenv()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

_ULTIMELE_REZULTATE_YT = []
_PROCES_BROWSER_YT = None


def seteaza_volum_sistem(procent):
    """Atenuează muzica (Audio Ducking) când vorbești cu robotul și o readuce la 100% după."""
    if os.name != "nt" and shutil.which("amixer"):
        subprocess.run(
            ["amixer", "set", "PCM", f"{int(procent)}%"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )


def cauta_youtube_oficial(interogare, doar_muzica=False, max_rezultate=5):
    """
    Caută legal prin YouTube Data API v3 și returnează primele 5 rezultate numerotate
    (id, titlu, canal, miniatură).
    """
    global _ULTIMELE_REZULTATE_YT
    if not YOUTUBE_API_KEY:
        return []

    q_enc = urllib.parse.quote(interogare.strip())
    cat_param = "&videoCategoryId=10" if doar_muzica else ""
    url = (
        f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
        f"&maxResults={max_rezultate}&q={q_enc}{cat_param}&key={YOUTUBE_API_KEY}"
    )

    try:
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
                "canal": snip.get("channelTitle", ""),
                "miniatura": snip.get("thumbnails", {}).get("medium", {}).get("url", "")
            })

        _ULTIMELE_REZULTATE_YT = rezultate
        return rezultate
    except Exception as e:
        print(f"[EROARE YOUTUBE API]: {e}")
        return []


def deschide_overlay_youtube(video_id):
    """Deschide playerul oficial YouTube Embed în fereastră Kiosk peste aplicație."""
    global _PROCES_BROWSER_YT
    inchide_overlay_youtube()
    url_embed = f"https://www.youtube.com/embed/{video_id}?autoplay=1&rel=0"

    for cmd_browser in ("chromium-browser", "chromium"):
        if shutil.which(cmd_browser):
            _PROCES_BROWSER_YT = subprocess.Popen(
                [cmd_browser, f"--app={url_embed}", "--start-fullscreen"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
    return False


def inchide_overlay_youtube():
    global _PROCES_BROWSER_YT
    if _PROCES_BROWSER_YT and _PROCES_BROWSER_YT.poll() is None:
        _PROCES_BROWSER_YT.terminate()
        _PROCES_BROWSER_YT = None