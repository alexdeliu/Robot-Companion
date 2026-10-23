import os
import re
import json
import time
import socket
import signal
import shutil
import threading
import subprocess
import urllib.parse
import urllib.request

from config import CFG, YOUTUBE_API_KEY, DEBUG
from system_health import logger

_ULTIMELE_REZULTATE_YT = []
_INDEX_CURENT_YT = 0
_MOD_CURENT_MUZICA = False
_PROCES_PLAYER_YT = None
_WINDOW_ID_CONTAINER = None
_VOLUM_NORMAL = int(CFG["audio_out"].get("volum_normal", 95))
_VOLUM_DUCKING = int(CFG["audio_out"].get("volum_ducking", 30))
_ESTE_IN_PAUZA = False

_CAUTARE_CACHE = {}
_STREAM_URL_CACHE = {}
_MPV_SOCKET_PATH = "/tmp/robot_mpv_ipc.sock"

HEADERS_WEB = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7"
}


def _trimite_comanda_mpv_ipc(lista_cmd):
    """Trimite o comandă JSON direct în socket-ul UNIX al lui mpv (0ms, fără a omorî procesul!)."""
    if os.name == "nt" or not os.path.exists(_MPV_SOCKET_PATH):
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            s.connect(_MPV_SOCKET_PATH)
            payload = json.dumps({"command": lista_cmd}) + "\n"
            s.sendall(payload.encode("utf-8"))
        return True
    except Exception:
        return False


def _aplica_volum_alsa(procent):
    val = max(15, min(100, int(procent)))
    # Reglăm atât în mpv IPC cât și în ALSA
    _trimite_comanda_mpv_ipc(["set_property", "volume", val])
    if os.name != "nt" and shutil.which("amixer"):
        for control in ("PCM", "Master", "Headphone", "Speaker"):
            subprocess.run(
                ["amixer", "-M", "set", control, f"{val}%", "unmute"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
    return val


def seteaza_volum_sistem(procent, salveaza_ca_normal=True):
    global _VOLUM_NORMAL
    val = _aplica_volum_alsa(procent)
    if salveaza_ca_normal:
        _VOLUM_NORMAL = val
    return val


def atenueaza_volum_temporar():
    if este_media_activa():
        _aplica_volum_alsa(_VOLUM_DUCKING)


def restabileste_volum_normal():
    return _aplica_volum_alsa(_VOLUM_NORMAL)


def schimba_volum_relativ(delta):
    global _VOLUM_NORMAL
    _VOLUM_NORMAL = max(20, min(100, _VOLUM_NORMAL + int(delta)))
    return _aplica_volum_alsa(_VOLUM_NORMAL)


def este_media_activa():
    return _PROCES_PLAYER_YT is not None and _PROCES_PLAYER_YT.poll() is None


def _extrage_stream_direct_ytdlp(video_id, doar_audio=True):
    """
    Extrage URL-ul direct cu cache (valabil 25 min) și retry, folosind rezoluție 360p
    optimizată pentru display-ul SPI și CPU-ul Raspberry Pi 3 B+.
    """
    cheie = f"{video_id}:{'audio' if doar_audio else 'video'}"
    acum = time.time()
    if cheie in _STREAM_URL_CACHE and (acum - _STREAM_URL_CACHE[cheie][0] < 1500):
        return _STREAM_URL_CACHE[cheie][1]

    url_yt = f"https://www.youtube.com/watch?v={video_id}"
    h_max = int(CFG["youtube"].get("max_video_height", 360))
    fps_max = int(CFG["youtube"].get("max_video_fps", 30))
    fmt = (
        "bestaudio[ext=m4a]/bestaudio/best"
        if doar_audio
        else f"best[height<={h_max}][fps<={fps_max}][ext=mp4]/best[height<={h_max}]/best"
    )
    timeout_s = str(int(CFG["youtube"].get("ytdlp_timeout_sec", 12)))

    # Rulăm yt-dlp în subproces izolat ca să elibereze 100% memoria RAM (70MB) imediat după extracție!
    cmd_bin = shutil.which("yt-dlp")
    if cmd_bin:
        for _ in range(2):
            try:
                out = subprocess.check_output(
                    [cmd_bin, "--no-warnings", "--no-playlist", "--socket-timeout", timeout_s, "-f", fmt, "-g", url_yt],
                    stderr=subprocess.DEVNULL,
                    timeout=float(timeout_s) + 3.0,
                    text=True
                ).strip()
                if out:
                    url_gasit = out.splitlines()[0].strip()
                    _STREAM_URL_CACHE[cheie] = (acum, url_gasit)
                    return url_gasit
            except Exception:
                time.sleep(0.2)

    try:
        import yt_dlp
        ydl_opts = {"format": fmt, "quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 6}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url_yt, download=False)
            url_gasit = info.get("url")
            if url_gasit:
                _STREAM_URL_CACHE[cheie] = (acum, url_gasit)
            return url_gasit
    except Exception as e:
        logger.warning(f"[YT-DLP]: Eșec extracție pentru {video_id}: {e}")
        return None


def _prefetch_piesa_urmatoare():
    """Pre-încarcă în fundal URL-ul piesei următoare pentru schimbare instantanee la NEXT."""
    if not CFG["youtube"].get("prefetch_next", True) or len(_ULTIMELE_REZULTATE_YT) < 2:
        return
    idx_urm = (_INDEX_CURENT_YT + 1) % len(_ULTIMELE_REZULTATE_YT)
    vid_urm = _ULTIMELE_REZULTATE_YT[idx_urm]["video_id"]
    threading.Thread(
        target=_extrage_stream_direct_ytdlp,
        args=(vid_urm, _MOD_CURENT_MUZICA),
        daemon=True
    ).start()


def _cauta_youtube_fara_cheie(interogare, max_rezultate=5):
    q_enc = urllib.parse.quote(interogare.strip())
    url = f"https://www.youtube.com/results?search_query={q_enc}&hl=ro"
    req = urllib.request.Request(url, headers=HEADERS_WEB)
    timeout_s = float(CFG["youtube"].get("search_timeout_sec", 6))
    with urllib.request.urlopen(req, timeout=timeout_s) as rasp:
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
    termen_baza = interogare.strip() or ("hituri românești" if doar_muzica else "documentare românia")
    termen = f"{termen_baza} official audio" if doar_muzica else termen_baza

    cheie_c = f"{termen.lower()}:{max_rezultate}"
    acum = time.time()
    ttl = int(CFG["youtube"].get("cache_ttl_sec", 1800))
    if cheie_c in _CAUTARE_CACHE and (acum - _CAUTARE_CACHE[cheie_c][0] < ttl):
        _ULTIMELE_REZULTATE_YT = _CAUTARE_CACHE[cheie_c][1]
        return _ULTIMELE_REZULTATE_YT

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
                _CAUTARE_CACHE[cheie_c] = (acum, rezultate)
                return rezultate
        except Exception as e:
            logger.warning(f"[YOUTUBE API]: {e}, folosesc căutarea directă...")

    try:
        rezultate = _cauta_youtube_fara_cheie(termen, max_rezultate=max_rezultate)
        _ULTIMELE_REZULTATE_YT = rezultate
        if rezultate:
            _CAUTARE_CACHE[cheie_c] = (acum, rezultate)
        return rezultate
    except Exception as e:
        logger.error(f"[EROARE CĂUTARE YOUTUBE]: {e}")
        return []


def deschide_overlay_youtube(video_id, mod_muzica=False, window_id=None):
    """
    Pornește mpv cu socket IPC (/tmp/robot_mpv_ipc.sock) și parametri optimizați pentru SPI display.
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
    if not url_direct:
        logger.error(f"[MEDIA]: Nu am putut extrage stream-ul pentru {video_id}.")
        return False

    if shutil.which("mpv"):
        try:
            if os.path.exists(_MPV_SOCKET_PATH):
                os.remove(_MPV_SOCKET_PATH)
        except Exception:
            pass

        args = [
            "mpv",
            "--no-terminal",
            "--really-quiet",
            "--keep-open=no",
            f"--input-ipc-server={_MPV_SOCKET_PATH}",
            f"--volume={_VOLUM_NORMAL}",
            "--cache=yes",
            "--demuxer-max-bytes=12M"
        ]
        if mod_muzica:
            args.append("--no-video")
        else:
            args.extend([
                "--vo=x11",
                "--profile=fast",
                "--hwdec=auto",
                "--vd-lavc-skiploopfilter=all",
                "--sws-scaler=fast-bilinear"
            ])
            if window_id:
                args.append(f"--wid={int(window_id)}")
            else:
                args.extend(["--geometry=640x360+40+60", "--ontop"])
        args.append(url_direct)

        _PROCES_PLAYER_YT = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        _prefetch_piesa_urmatoare()
        return True

    if shutil.which("ffplay"):
        args = ["ffplay", "-autoexit", "-loglevel", "quiet"]
        if mod_muzica:
            args.append("-nodisp")
        else:
            args.extend(["-x", "640", "-y", "360", "-alwaysontop"])
        args.append(url_direct)
        _PROCES_PLAYER_YT = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        return True

    if os.name == "nt":
        import webbrowser
        webbrowser.open(f"https://www.youtube.com/watch?v={video_id}")
        return True

    return False


def deruleaza_media(secunde_delta):
    """Derulează rapid ±10 secunde prin socket-ul IPC al lui mpv."""
    return _trimite_comanda_mpv_ipc(["seek", int(secunde_delta), "relative"])


def toggle_pauza_media():
    """Comută Play/Pauză instantaneu prin IPC socket (cu fallback pe SIGSTOP)."""
    global _ESTE_IN_PAUZA
    if not este_media_activa():
        return False

    if _trimite_comanda_mpv_ipc(["cycle", "pause"]):
        _ESTE_IN_PAUZA = not _ESTE_IN_PAUZA
        return _ESTE_IN_PAUZA

    if os.name != "nt":
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
            pass
    return False


def selecteaza_meta_dupa_numar(numar_1_5):
    """Returnează metadatele videoclipului 1..5 fără a porni mpv prematur înaintea cadrului UI."""
    global _INDEX_CURENT_YT
    if not _ULTIMELE_REZULTATE_YT:
        return None
    idx = max(0, min(len(_ULTIMELE_REZULTATE_YT) - 1, int(numar_1_5) - 1))
    _INDEX_CURENT_YT = idx
    return _ULTIMELE_REZULTATE_YT[idx]


def reda_rezultat_dupa_numar(numar_1_5, window_id=None):
    ales = selecteaza_meta_dupa_numar(numar_1_5)
    if not ales:
        return None
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
    """Închide curat mpv prin IPC quit (evită XError BadWindow în Tkinter), apoi curăță procesul."""
    global _PROCES_PLAYER_YT, _ESTE_IN_PAUZA
    _ESTE_IN_PAUZA = False
    proc = _PROCES_PLAYER_YT
    _PROCES_PLAYER_YT = None

    if proc and proc.poll() is None:
        _trimite_comanda_mpv_ipc(["quit"])
        try:
            proc.wait(timeout=0.4)
        except Exception:
            try:
                if os.name != "nt":
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGCONT)
                    os.killpg(pgid, signal.SIGTERM)
                else:
                    proc.terminate()
                proc.wait(timeout=0.4)
            except Exception:
                pass