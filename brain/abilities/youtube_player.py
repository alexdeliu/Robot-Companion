import os
import re
import json
import signal
import shutil
import subprocess
import urllib.parse
import urllib.request
from dotenv import load_dotenv

load_dotenv()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
DEBUG = os.getenv("DEBUG", "1") == "1"

_ULTIMELE_REZULTATE_YT = []
_INDEX_CURENT_YT = 0
_MOD_CURENT_MUZICA = False
_PROCES_PLAYER_YT = None
_WINDOW_ID_CONTAINER = None
_VOLUM_NORMAL = 95
_ESTE_IN_PAUZA = False

HEADERS_WEB = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7"
}


def _aplica_volum_alsa(procent):
    """
    Setează volumul în ALSA folosind flag-ul '-M' (scara logaritmică naturală a urechii umane,
    identică cu cea din alsamixer, astfel încât sunetul să fie mereu puternic și clar!).
    """
    val = max(15, min(100, int(procent)))
    if os.name != "nt" and shutil.which("amixer"):
        for control in ("PCM", "Master", "Headphone", "Speaker"):
            subprocess.run(
                ["amixer", "-M", "set", control, f"{val}%", "unmute"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
    return val


def seteaza_volum_sistem(procent, salveaza_ca_normal=True):
    """Setează volumul sistemului. Dacă salveaza_ca_normal=False, face doar atenuare temporară (ducking)."""
    global _VOLUM_NORMAL
    val = _aplica_volum_alsa(procent)
    if salveaza_ca_normal:
        _VOLUM_NORMAL = val
    return val


def atenueaza_volum_temporar():
    """Scade volumul doar în timp ce microfonul înregistrează, fără a pierde nivelul normal (95%)."""
    if este_media_activa():
        _aplica_volum_alsa(35)


def restabileste_volum_normal():
    """Readuce garantat volumul la nivelul puternic (_VOLUM_NORMAL = 95%) înainte ca robotul să vorbească."""
    return _aplica_volum_alsa(_VOLUM_NORMAL)


def schimba_volum_relativ(delta):
    global _VOLUM_NORMAL
    _VOLUM_NORMAL = max(20, min(100, _VOLUM_NORMAL + int(delta)))
    return _aplica_volum_alsa(_VOLUM_NORMAL)


def este_media_activa():
    return _PROCES_PLAYER_YT is not None and _PROCES_PLAYER_YT.poll() is None


def _extrage_stream_direct_ytdlp(video_id, doar_audio=True):
    """
    Folosește yt-dlp pentru a extrage URL-ul direct al fluxului audio/video de pe YouTube.
    Astfel ocolim 100% eroarea 150/153 din YouTube Embed și nu mai avem nevoie de Chromium!
    """
    url_yt = f"https://www.youtube.com/watch?v={video_id}"
    try:
        import yt_dlp
        fmt = "bestaudio/best" if doar_audio else "best[height<=480][ext=mp4]/best[height<=480]/best"
        ydl_opts = {
            "format": fmt,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 5,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url_yt, download=False)
            return info.get("url")
    except Exception as e:
        if DEBUG:
            print(f"[AVERTISMENT YT-DLP]: {e}")
        return None


def _cauta_youtube_fara_cheie(interogare, max_rezultate=5):
    """Caută direct pe YouTube și returnează 5 rezultate reale (fără a necesita cheie API)."""
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
            miniatura = f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"

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
    termen_baza = interogare.strip() or ("muzică populară hituri" if doar_muzica else "documentare românia")
    termen = f"{termen_baza} official audio" if doar_muzica else termen_baza

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
                    "miniatura": f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"
                })
            if rezultate:
                _ULTIMELE_REZULTATE_YT = rezultate
                return rezultate
        except Exception as e:
            if DEBUG:
                print(f"[AVERTISMENT YOUTUBE API]: {e}, folosesc căutarea directă...")

    try:
        rezultate = _cauta_youtube_fara_cheie(termen, max_rezultate=max_rezultate)
        _ULTIMELE_REZULTATE_YT = rezultate
        return rezultate
    except Exception as e:
        print(f"[EROARE CĂUTARE YOUTUBE]: {e}")
        return []


def deschide_overlay_youtube(video_id, mod_muzica=False, window_id=None):
    """
    Redă melodia sau videoclipul rapid și sigur, FĂRĂ Chromium fullscreen blocat:
    - Extrage stream-ul direct prin yt-dlp (funcționează pe 100% din melodii, fără Eroarea 150!).
    - Redă cu mpv / ffplay / cvlc.
    - Dacă mod_muzica=False și avem window_id (cadrul din Tkinter), mpv randează videoclipul
      DIRECT în interiorul ferestrei Robot Companion (--wid), astfel încât butoanele OPREȘTE / ÎNCHIDE
      rămân mereu deasupra și funcționale!
    """
    global _PROCES_PLAYER_YT, _INDEX_CURENT_YT, _MOD_CURENT_MUZICA, _WINDOW_ID_CONTAINER, _ESTE_IN_PAUZA
    inchide_overlay_youtube()

    _MOD_CURENT_MUZICA = mod_muzica
    _WINDOW_ID_CONTAINER = window_id
    _ESTE_IN_PAUZA = False
    restabileste_volum_normal()

    for idx, item in enumerate(_ULTIMELE_REZULTATE_YT):
        if item["video_id"] == video_id:
            _INDEX_CURENT_YT = idx
            break

    url_direct = _extrage_stream_direct_ytdlp(video_id, doar_audio=mod_muzica)
    tinta_redare = url_direct or f"https://www.youtube.com/watch?v={video_id}"

    # 1. Varianta optimă pe Raspberry Pi și Linux: MPV (doar 15MB RAM, încorporat direct în Tkinter!)
    if shutil.which("mpv"):
        args = ["mpv", "--no-terminal", "--really-quiet", "-- keep-open=no"]
        args = ["mpv", "--no-terminal", "--really-quiet", "--keep-open=no"]
        if mod_muzica:
            args.append("--no-video")
        else:
            args.extend(["--vo=x11", "--profile=fast", "--hwdec=auto"])
            if window_id:
                args.append(f"--wid={int(window_id)}")
            else:
                args.extend(["--geometry=720x400+40+60", "--ontop"])
        args.append(tinta_redare)
        _PROCES_PLAYER_YT = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        return True

    # 2. Fallback pe FFPLAY (vine cu ffmpeg)
    if shutil.which("ffplay") and url_direct:
        args = ["ffplay", "-autoexit", "-loglevel", "quiet"]
        if mod_muzica:
            args.append("-nodisp")
        else:
            args.extend(["-x", "680", "-y", "360", "-left", "60", "-top", "75", "-alwaysontop"])
        args.append(url_direct)
        _PROCES_PLAYER_YT = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        return True

    # 3. Fallback pe VLC (cvlc)
    if shutil.which("cvlc") and url_direct:
        args = ["cvlc", "--play-and-exit", "--quiet"]
        if mod_muzica:
            args.append("--no-video")
        elif window_id:
            args.extend(["--drawable-xid", str(int(window_id))])
        args.append(url_direct)
        _PROCES_PLAYER_YT = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        return True

    # 4. Fallback pe Windows sau dacă doar ffmpeg + mpg123 există pe sistem
    if os.name != "nt" and shutil.which("ffmpeg") and shutil.which("mpg123") and url_direct:
        cmd_sh = f'ffmpeg -loglevel quiet -i "{url_direct}" -f mp3 - | mpg123 -q -'
        _PROCES_PLAYER_YT = subprocess.Popen(
            cmd_sh,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        return True

    if os.name == "nt":
        import webbrowser
        webbrowser.open(f"https://www.youtube.com/watch?v={video_id}")
        return True

    print("[EROARE MEDIA]: Instalează mpv pe Raspberry Pi: sudo apt-get install -y mpv ffmpeg")
    return False


def toggle_pauza_media():
    """Pune pe pauză sau reia melodia/videoclipul curent fără a-l închide (SIGSTOP / SIGCONT pe Linux)."""
    global _ESTE_IN_PAUZA
    if not este_media_activa() or os.name == "nt":
        return False
    try:
        pgid = os.getpgid(_PROCES_PLAYER_YT.pid)
        if not _ESTE_IN_PAUZA:
            os.killpg(pgid, signal.SIGSTOP)
            _ESTE_IN_PAUZA = True
        else:
            os.killpg(pgid, signal.SIGCONT)
            _ESTE_IN_PAUZA = False
        return _ESTE_IN_PAUZA
    except Exception:
        return False


def reda_rezultat_dupa_numar(numar_1_5, window_id=None):
    if not _ULTIMELE_REZULTATE_YT:
        return None
    idx = max(0, min(len(_ULTIMELE_REZULTATE_YT) - 1, int(numar_1_5) - 1))
    ales = _ULTIMELE_REZULTATE_YT[idx]
    wid = window_id if window_id is not None else _WINDOW_ID_CONTAINER
    deschide_overlay_youtube(ales["video_id"], mod_muzica=_MOD_CURENT_MUZICA, window_id=wid)
    return ales


def piesa_urmatoare(window_id=None):
    global _INDEX_CURENT_YT
    if not _ULTIMELE_REZULTATE_YT:
        return None
    _INDEX_CURENT_YT = (_INDEX_CURENT_YT + 1) % len(_ULTIMELE_REZULTATE_YT)
    ales = _ULTIMELE_REZULTATE_YT[_INDEX_CURENT_YT]
    wid = window_id if window_id is not None else _WINDOW_ID_CONTAINER
    deschide_overlay_youtube(ales["video_id"], mod_muzica=_MOD_CURENT_MUZICA, window_id=wid)
    return ales


def piesa_anterioara(window_id=None):
    global _INDEX_CURENT_YT
    if not _ULTIMELE_REZULTATE_YT:
        return None
    _INDEX_CURENT_YT = (_INDEX_CURENT_YT - 1) % len(_ULTIMELE_REZULTATE_YT)
    ales = _ULTIMELE_REZULTATE_YT[_INDEX_CURENT_YT]
    wid = window_id if window_id is not None else _WINDOW_ID_CONTAINER
    deschide_overlay_youtube(ales["video_id"], mod_muzica=_MOD_CURENT_MUZICA, window_id=wid)
    return ales


def inchide_overlay_youtube():
    """Închide garantat și instantaneu orice proces audio/video pornit."""
    global _PROCES_PLAYER_YT, _ESTE_IN_PAUZA
    _ESTE_IN_PAUZA = False
    if _PROCES_PLAYER_YT:
        try:
            if os.name != "nt":
                pgid = os.getpgid(_PROCES_PLAYER_YT.pid)
                os.killpg(pgid, signal.SIGCONT)
                os.killpg(pgid, signal.SIGTERM)
            else:
                _PROCES_PLAYER_YT.terminate()
        except Exception:
            pass
        _PROCES_PLAYER_YT = None

    if os.name != "nt":
        for proc_name in ("mpv", "ffplay", "vlc"):
            subprocess.run(
                ["pkill", "-9", "-f", proc_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )