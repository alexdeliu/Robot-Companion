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

from config import CFG, YOUTUBE_API_KEY, DEBUG, salveaza_config_local
from system_health import logger

_ULTIMELE_REZULTATE_YT = []
_INDEX_CURENT_YT = 0
_MOD_CURENT_MUZICA = False
_PROCES_PLAYER_YT = None
_PROCES_FFMPEG_VIDEO = None
_WINDOW_ID_CONTAINER = None
_VOLUM_NORMAL = int(CFG["audio_out"].get("volum_normal", 95))
_VOLUM_DUCKING = int(CFG["audio_out"].get("volum_ducking", 30))
_ESTE_IN_PAUZA = False
_SESIUNE_MEDIA_ID = 0
_MEDIA_LOCK = threading.RLock()
_CONTROALE_ALSA_VALID = None

_CAUTARE_CACHE = {}
_STREAM_URL_CACHE = {}
_MPV_SOCKET_PATH = "/tmp/robot_mpv_ipc.sock"
_MPV_LOG_PATH = "/tmp/robot_mpv.log"

HEADERS_WEB = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7"
}


def verifica_versiune_ytdlp():
    """Verifică la pornire versiunea yt-dlp și runtime-ul JS fără a bloca aplicația."""
    cmd_bin = shutil.which("yt-dlp")
    if not cmd_bin:
        logger.warning("[YOUTUBE CHECK]: Utilitarul 'yt-dlp' nu a fost găsit în PATH! Rulează: pip install -U yt-dlp")
        return "lipsă"
    try:
        ver = subprocess.check_output([cmd_bin, "--version"], stderr=subprocess.STDOUT, timeout=5, text=True).strip()
        js_rt = "nodejs" if shutil.which("node") else ("deno" if shutil.which("deno") else "intern")
        logger.info(f"[YOUTUBE CHECK]: yt-dlp versiunea {ver} | JS runtime={js_rt}")
        if ver < "2024.11":
            logger.warning(
                f"[YOUTUBE CHECK]: Versiunea yt-dlp ({ver}) este veche și YouTube poate bloca video! "
                "Actualizează cu: pip install -U yt-dlp"
            )
        return ver
    except Exception as e:
        logger.warning(f"[YOUTUBE CHECK]: Nu am putut verifica yt-dlp: {e}")
        return "eroare"


threading.Thread(target=verifica_versiune_ytdlp, name="YtdlpCheck", daemon=True).start()


def _detecteaza_controale_alsa():
    """Descoperă o singură dată controalele ALSA reale existente pe Raspberry Pi (fără apeluri oarbe)."""
    global _CONTROALE_ALSA_VALID
    if _CONTROALE_ALSA_VALID is not None:
        return _CONTROALE_ALSA_VALID
    _CONTROALE_ALSA_VALID = []
    if os.name == "nt" or not shutil.which("amixer"):
        return _CONTROALE_ALSA_VALID
    try:
        out = subprocess.check_output(["amixer", "scontrols"], stderr=subprocess.DEVNULL, timeout=2, text=True)
        for candidat in ("PCM", "Master", "Headphone", "Speaker", "Digital"):
            if f"'{candidat}'" in out:
                _CONTROALE_ALSA_VALID.append(candidat)
    except Exception as e:
        logger.debug(f"[ALSA]: Eroare citire scontrols: {e}")
    if not _CONTROALE_ALSA_VALID:
        _CONTROALE_ALSA_VALID = ["PCM", "Master"]
    return _CONTROALE_ALSA_VALID


def _trimite_comanda_mpv_ipc(lista_cmd):
    if os.name == "nt" or not os.path.exists(_MPV_SOCKET_PATH):
        return False
    for incercare in range(3):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.25)
                s.connect(_MPV_SOCKET_PATH)
                payload = json.dumps({"command": lista_cmd}) + "\n"
                s.sendall(payload.encode("utf-8"))
            return True
        except Exception:
            if incercare < 2:
                time.sleep(0.06)
    return False


def _aplica_volum_alsa(procent):
    val = max(15, min(100, int(procent)))
    _trimite_comanda_mpv_ipc(["set_property", "volume", val])
    if os.name != "nt" and shutil.which("amixer"):
        for control in _detecteaza_controale_alsa():
            try:
                subprocess.run(
                    ["amixer", "-M", "set", control, f"{val}%", "unmute"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.5
                )
            except Exception as e:
                logger.debug(f"[ALSA VOL]: {control}: {e}")
    return val


def seteaza_volum_sistem(procent, salveaza_ca_normal=True):
    global _VOLUM_NORMAL
    val = _aplica_volum_alsa(procent)
    if salveaza_ca_normal:
        _VOLUM_NORMAL = val
        salveaza_config_local("audio_out", "volum_normal", val)
    return val


def atenueaza_volum_temporar():
    if este_media_activa():
        _aplica_volum_alsa(_VOLUM_DUCKING)


def restabileste_volum_normal():
    return _aplica_volum_alsa(_VOLUM_NORMAL)


def schimba_volum_relativ(delta):
    global _VOLUM_NORMAL
    _VOLUM_NORMAL = max(20, min(100, _VOLUM_NORMAL + int(delta)))
    salveaza_config_local("audio_out", "volum_normal", _VOLUM_NORMAL)
    return _aplica_volum_alsa(_VOLUM_NORMAL)


def este_media_activa():
    return _PROCES_PLAYER_YT is not None and _PROCES_PLAYER_YT.poll() is None


def obtine_lista_curenta():
    return list(_ULTIMELE_REZULTATE_YT), _INDEX_CURENT_YT


def _extrage_stream_direct_ytdlp(video_id, doar_audio=True):
    """
    Returnează un dicționar {'video_url': ..., 'audio_url': ...}.
    Tratează atât fluxurile progresive (1 linie: video+audio combinat, ex. itag 18),
    cât și fluxurile DASH separate (2 linii: linia 1 = video, linia 2 = audio),
    și loghează explicit stderr dacă apare o eroare!
    """
    cheie = f"{video_id}:{'audio' if doar_audio else 'video'}"
    acum = time.time()
    if cheie in _STREAM_URL_CACHE and (acum - _STREAM_URL_CACHE[cheie][0] < 1200):
        return _STREAM_URL_CACHE[cheie][1]

    url_yt = f"https://www.youtube.com/watch?v={video_id}"
    h_max = int(CFG["youtube"].get("max_video_height", 360))
    # Pentru video cerem progresiv mp4 <=360p (itag 18 are 30fps!), cu fallback pe bestvideo+bestaudio separat
    fmt = (
        "bestaudio[ext=m4a]/bestaudio/best"
        if doar_audio
        else f"best[height<={h_max}][ext=mp4]/bestvideo[height<={h_max}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h_max}]/best"
    )
    timeout_s = str(int(CFG["youtube"].get("ytdlp_timeout_sec", 14)))
    log_err = bool(CFG["youtube"].get("log_errors", True))

    cmd_bin = shutil.which("yt-dlp")
    if cmd_bin:
        for incercare in range(2):
            try:
                proc = subprocess.run(
                    [cmd_bin, "--no-warnings", "--no-playlist", "--socket-timeout", timeout_s, "-f", fmt, "-g", url_yt],
                    capture_output=True,
                    timeout=float(timeout_s) + 4.0,
                    text=True
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    linii = [l.strip() for l in proc.stdout.strip().splitlines() if l.strip()]
                    rez = {
                        "video_url": linii[0],
                        "audio_url": linii[1] if len(linii) > 1 else linii[0]
                    }
                    _STREAM_URL_CACHE[cheie] = (acum, rez)
                    return rez
                elif log_err and proc.stderr:
                    logger.warning(f"[YT-DLP STDERR încercarea {incercare+1} ({video_id})]: {proc.stderr.strip()[:300]}")
            except Exception as e:
                if log_err:
                    logger.warning(f"[YT-DLP SUBPROCESS ({video_id})]: {e}")
                time.sleep(0.25)

    try:
        import yt_dlp
        ydl_opts = {"format": fmt, "quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 8}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url_yt, download=False)
            if "requested_formats" in info and len(info["requested_formats"]) >= 2:
                v_u = info["requested_formats"][0].get("url")
                a_u = info["requested_formats"][1].get("url")
                rez = {"video_url": v_u, "audio_url": a_u or v_u}
            else:
                u = info.get("url")
                rez = {"video_url": u, "audio_url": u} if u else None
            if rez and rez.get("video_url"):
                _STREAM_URL_CACHE[cheie] = (acum, rez)
                return rez
    except Exception as e:
        logger.error(f"[YT-DLP PYTHON FALLBACK EȘEC ({video_id})]: {e}")

    # Dacă a eșuat formatul video, încercăm măcar audio ca utilizatorul să audă garantat sunetul!
    if not doar_audio:
        logger.warning(f"[YOUTUBE]: Formatul video a eșuat pentru {video_id}, încerc fallback doar-audio...")
        return _extrage_stream_direct_ytdlp(video_id, doar_audio=True)
    return None


def _prefetch_piesa_urmatoare():
    if not CFG["youtube"].get("prefetch_next", True) or len(_ULTIMELE_REZULTATE_YT) < 2:
        return
    if len(_STREAM_URL_CACHE) > 30:
        _STREAM_URL_CACHE.clear()
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

    if len(_CAUTARE_CACHE) > 25:
        _CAUTARE_CACHE.clear()

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


def _ruleaza_decodare_video_in_canvas(video_url, sesiune_id, on_frame_rgb, latime=320, inaltime=180):
    """
    Decodare video ultra-ușoară cu ffmpeg direct în Canvas-ul Tkinter de pe ecranul SPI!
    Nu depinde de X11 --wid sau Wayland și nu acoperă niciodată butoanele Tkinter.
    """
    global _PROCES_FFMPEG_VIDEO
    if not shutil.which("ffmpeg") or not on_frame_rgb:
        return
    fps = int(CFG["youtube"].get("spi_canvas_fps", 12))
    w = max(160, (int(latime) // 2) * 2)
    h = max(120, (int(inaltime) // 2) * 2)
    frame_bytes = w * h * 3

    args = [
        "ffmpeg",
        "-loglevel", "error",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "4",
        "-i", video_url,
        "-vf", f"scale={w}:{h}:flags=fast_bilinear,fps={fps}",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-an",
        "-"
    ]
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=frame_bytes * 2,
            start_new_session=True
        )
        _PROCES_FFMPEG_VIDEO = proc
        while proc.poll() is None and sesiune_id == _SESIUNE_MEDIA_ID:
            if _ESTE_IN_PAUZA:
                time.sleep(0.1)
                continue
            raw = proc.stdout.read(frame_bytes)
            if not raw or len(raw) < frame_bytes:
                break
            on_frame_rgb(raw, w, h)
    except Exception as e:
        logger.warning(f"[FFMPEG SPI CANVAS]: {e}")
    finally:
        try:
            if _PROCES_FFMPEG_VIDEO and _PROCES_FFMPEG_VIDEO.poll() is None:
                _PROCES_FFMPEG_VIDEO.terminate()
        except Exception:
            pass


def deschide_overlay_youtube(video_id, mod_muzica=False, window_id=None, on_frame_rgb=None, on_status_ui=None, dim_video=(320, 180)):
    """
    Pornește redarea YouTube garantând că sunetul funcționează MEREU și că imaginea
    se afișează pe display-ul SPI (fie prin Canvas-ul Tkinter, fie prin mpv --wid cu fallback).
    """
    global _PROCES_PLAYER_YT, _INDEX_CURENT_YT, _MOD_CURENT_MUZICA, _WINDOW_ID_CONTAINER, _ESTE_IN_PAUZA, _SESIUNE_MEDIA_ID

    with _MEDIA_LOCK:
        _SESIUNE_MEDIA_ID += 1
        sesiune_curenta = _SESIUNE_MEDIA_ID

    inchide_overlay_youtube(pastreaza_sesiune=True)
    if on_status_ui:
        on_status_ui("Se extrage stream-ul YouTube...")

    _MOD_CURENT_MUZICA = mod_muzica
    _WINDOW_ID_CONTAINER = window_id
    _ESTE_IN_PAUZA = False
    restabileste_volum_normal()

    for idx, item in enumerate(_ULTIMELE_REZULTATE_YT):
        if item["video_id"] == video_id:
            _INDEX_CURENT_YT = idx
            break

    stream_info = _extrage_stream_direct_ytdlp(video_id, doar_audio=mod_muzica)
    if sesiune_curenta != _SESIUNE_MEDIA_ID:
        return False

    if not stream_info or not stream_info.get("video_url"):
        msg_err = "Nu am putut extrage stream-ul YouTube (verifică internetul sau actualizează yt-dlp)."
        logger.error(f"[MEDIA]: {msg_err} (id={video_id})")
        if on_status_ui:
            on_status_ui(msg_err)
        return False

    video_url = stream_info["video_url"]
    audio_url = stream_info.get("audio_url") or video_url
    mod_video_cfg = CFG["youtube"].get("video_mode", "auto")
    foloseste_tk_canvas = (not mod_muzica) and (on_frame_rgb is not None) and (mod_video_cfg in ("auto", "tk_canvas"))

    if shutil.which("mpv"):
        try:
            if os.path.exists(_MPV_SOCKET_PATH):
                os.remove(_MPV_SOCKET_PATH)
        except Exception as e:
            logger.debug(f"[MPV SOCKET]: {e}")

        args = [
            "mpv",
            "--no-terminal",
            "--keep-open=no",
            f"--input-ipc-server={_MPV_SOCKET_PATH}",
            f"--log-file={_MPV_LOG_PATH}",
            "--msg-level=all=warn,vo=info,ao=info",
            f"--volume={_VOLUM_NORMAL}",
            "--cache=yes",
            "--demuxer-max-bytes=10M"
        ]

        if mod_muzica or foloseste_tk_canvas:
            # Sunetul este redat curat de mpv, iar dacă foloseste_tk_canvas=True,
            # imaginea este desenată în paralel de ffmpeg direct în Canvas-ul Tkinter!
            args.append("--no-video")
            args.append(audio_url)
        else:
            args.extend([
                "--vo=x11,xv,wlshm,sdl",
                "--profile=fast",
                "--hwdec=auto",
                "--vd-lavc-skiploopfilter=all",
                "--sws-scaler=fast-bilinear"
            ])
            if window_id:
                args.append(f"--wid={int(window_id)}")
            if audio_url and audio_url != video_url:
                args.append(f"--audio-file={audio_url}")
            args.append(video_url)

        _PROCES_PLAYER_YT = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        if foloseste_tk_canvas:
            if on_status_ui:
                on_status_ui("Redare video SPI + audio activă")
            threading.Thread(
                target=_ruleaza_decodare_video_in_canvas,
                args=(video_url, sesiune_curenta, on_frame_rgb, dim_video[0], dim_video[1]),
                name="SpiVideoDecoder",
                daemon=True
            ).start()
        elif not mod_muzica:
            # Watchdog: verificăm după 1.2s dacă mpv --wid a murit din cauza X11/Wayland
            time.sleep(1.1)
            if _PROCES_PLAYER_YT and _PROCES_PLAYER_YT.poll() is not None and sesiune_curenta == _SESIUNE_MEDIA_ID:
                rc = _PROCES_PLAYER_YT.returncode
                detalii_log = ""
                if os.path.exists(_MPV_LOG_PATH):
                    with open(_MPV_LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
                        detalii_log = f.read()[-300:].strip()
                logger.warning(f"[MPV WID FALLBACK]: mpv --wid a ieșit cu codul {rc} ({detalii_log}). Trec pe tk_canvas!")
                if on_frame_rgb:
                    CFG["youtube"]["video_mode"] = "tk_canvas"
                    return deschide_overlay_youtube(video_id, False, window_id, on_frame_rgb, on_status_ui, dim_video)

        _prefetch_piesa_urmatoare()
        return True

    if os.name == "nt":
        import webbrowser
        webbrowser.open(f"https://www.youtube.com/watch?v={video_id}")
        return True

    if on_status_ui:
        on_status_ui("Eroare: instalează mpv și ffmpeg pe Raspberry Pi!")
    return False


def deruleaza_media(secunde_delta):
    return _trimite_comanda_mpv_ipc(["seek", int(secunde_delta), "relative"])


def toggle_pauza_media():
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
        except Exception as e:
            logger.debug(f"[PAUZA MEDIA]: {e}")
    return False


def selecteaza_meta_dupa_numar(numar_1_5):
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
    threading.Thread(
        target=deschide_overlay_youtube,
        args=(ales["video_id"], _MOD_CURENT_MUZICA, wid),
        daemon=True
    ).start()
    return ales


def piesa_urmatoare(window_id=None, on_frame_rgb=None, on_status_ui=None, dim_video=(320, 180)):
    global _INDEX_CURENT_YT
    if not _ULTIMELE_REZULTATE_YT:
        return None
    _INDEX_CURENT_YT = (_INDEX_CURENT_YT + 1) % len(_ULTIMELE_REZULTATE_YT)
    ales = _ULTIMELE_REZULTATE_YT[_INDEX_CURENT_YT]
    wid = window_id if window_id is not None else _WINDOW_ID_CONTAINER
    deschide_overlay_youtube(ales["video_id"], _MOD_CURENT_MUZICA, wid, on_frame_rgb, on_status_ui, dim_video)
    return ales


def piesa_anterioara(window_id=None, on_frame_rgb=None, on_status_ui=None, dim_video=(320, 180)):
    global _INDEX_CURENT_YT
    if not _ULTIMELE_REZULTATE_YT:
        return None
    _INDEX_CURENT_YT = (_INDEX_CURENT_YT - 1) % len(_ULTIMELE_REZULTATE_YT)
    ales = _ULTIMELE_REZULTATE_YT[_INDEX_CURENT_YT]
    wid = window_id if window_id is not None else _WINDOW_ID_CONTAINER
    deschide_overlay_youtube(ales["video_id"], _MOD_CURENT_MUZICA, wid, on_frame_rgb, on_status_ui, dim_video)
    return ales


def inchide_overlay_youtube(pastreaza_sesiune=False):
    global _PROCES_PLAYER_YT, _PROCES_FFMPEG_VIDEO, _ESTE_IN_PAUZA, _SESIUNE_MEDIA_ID
    if not pastreaza_sesiune:
        with _MEDIA_LOCK:
            _SESIUNE_MEDIA_ID += 1
    _ESTE_IN_PAUZA = False

    for proc_ref, este_mpv in ((_PROCES_FFMPEG_VIDEO, False), (_PROCES_PLAYER_YT, True)):
        if proc_ref and proc_ref.poll() is None:
            if este_mpv:
                _trimite_comanda_mpv_ipc(["quit"])
            try:
                proc_ref.wait(timeout=0.35)
            except Exception:
                try:
                    if os.name != "nt":
                        pgid = os.getpgid(proc_ref.pid)
                        os.killpg(pgid, signal.SIGCONT)
                        os.killpg(pgid, signal.SIGTERM)
                    else:
                        proc_ref.terminate()
                    proc_ref.wait(timeout=0.35)
                except Exception as e:
                    logger.debug(f"[CLEANUP MEDIA]: {e}")
    _PROCES_FFMPEG_VIDEO = None
    _PROCES_PLAYER_YT = None