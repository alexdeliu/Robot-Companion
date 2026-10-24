import os
import sys
import json
import shutil
import platform
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import CFG
from brain.abilities.youtube_player import cauta_youtube_oficial, _extrage_stream_direct_ytdlp


def _cmd_out(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def ruleaza_diag_youtube():
    url_test = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    print("=" * 68)
    print("   DIAGNOSTIC COMPLET YOUTUBE VIDEO & AUDIO - ROBOT COMPANION")
    print("=" * 68)

    # 1. Mediu și versiuni
    sesiune = os.environ.get("XDG_SESSION_TYPE", "necunoscut")
    disp = os.environ.get("DISPLAY", "nesetat")
    wayland = os.environ.get("WAYLAND_DISPLAY", "nesetat")
    _, ytdlp_v, _ = _cmd_out(["yt-dlp", "--version"])
    _, mpv_v, _ = _cmd_out(["mpv", "--version"])
    _, ff_v, _ = _cmd_out(["ffmpeg", "-version"])
    fb_devs = [f for f in os.listdir("/dev") if f.startswith("fb") or f.startswith("spidev")] if os.path.isdir("/dev") else []

    print(f"[1] Mediu & Versiuni:")
    print(f"    - OS / Arhitectură : {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"    - Sesiune Grafică  : XDG_SESSION_TYPE={sesiune} | DISPLAY={disp} | WAYLAND={wayland}")
    print(f"    - Framebuffer/SPI  : {fb_devs}")
    print(f"    - yt-dlp           : {ytdlp_v or 'LIPSĂ'}")
    print(f"    - mpv              : {(mpv_v.splitlines()[0] if mpv_v else 'LIPSĂ')}")
    print(f"    - ffmpeg           : {(ff_v.splitlines()[0] if ff_v else 'LIPSĂ')}")

    # 2. Test Căutare
    print("\n[2] Test Căutare YouTube ('documentar natura'):")
    rez = cauta_youtube_oficial("documentar natura", doar_muzica=False, max_rezultate=3)
    if rez:
        print(f"    [OK] S-au găsit {len(rez)} rezultate. Primul: {rez[0]['titlu']} (id={rez[0]['video_id']})")
        if len(sys.argv) <= 1:
            url_test = f"https://www.youtube.com/watch?v={rez[0]['video_id']}"
    else:
        print("    [EROARE] Căutarea YouTube nu a returnat rezultate!")

    vid_id = url_test.split("v=")[-1].split("&")[0]

    # 3. Listare formate disponibile cu stderr vizibil
    print(f"\n[3] Extracție URL-uri pentru {url_test}:")
    rc_f, out_f, err_f = _cmd_out(["yt-dlp", "--no-warnings", "--no-playlist", "-F", url_test], timeout=18)
    if rc_f == 0:
        linii_mp4 = [l for l in out_f.splitlines() if "mp4" in l or "m4a" in l][-6:]
        print("    [OK] Formate MP4/M4A disponibile (ultimele 6):")
        for l in linii_mp4:
            print(f"         {l[:76]}")
    else:
        print(f"    [EROARE yt-dlp -F]: rc={rc_f} | stderr={err_f[:300]}")

    stream_info = _extrage_stream_direct_ytdlp(vid_id, doar_audio=False)
    print(f"    - Rezultat _extrage_stream_direct_ytdlp: {bool(stream_info)}")
    if not stream_info:
        print("    [STOP] Extracția stream-ului a eșuat. Actualizează yt-dlp: pip install -U yt-dlp")
        return

    v_url = stream_info["video_url"]
    a_url = stream_info.get("audio_url") or v_url
    print(f"    - URL Video și Audio sunt identice (progresiv)? {v_url == a_url}")

    # 4. Test MPV în 3 trepte
    if shutil.which("mpv"):
        print("\n[4] Test MPV în 3 trepte (câte 3 secunde fiecare):")
        # Treapta A: Doar Audio
        rc_a, _, err_a = _cmd_out(["mpv", "--no-terminal", "--no-video", "--length=3", a_url], timeout=10)
        print(f"    - Treapta 4A (Doar Audio în boxe)   : {'OK' if rc_a == 0 else f'EȘEC (rc={rc_a}: {err_a[:160]})'}")

        # Treapta B: Video cu --vo=null
        rc_b, _, err_b = _cmd_out(["mpv", "--no-terminal", "--vo=null", "--ao=null", "--length=2", v_url], timeout=10)
        print(f"    - Treapta 4B (Decodare Video --vo=null): {'OK' if rc_b == 0 else f'EȘEC (rc={rc_b}: {err_b[:160]})'}")

        # Treapta C: Decodare FFMPEG SPI RGB24 (1 cadru)
        rc_c, _, err_c = _cmd_out(
            ["ffmpeg", "-loglevel", "error", "-i", v_url, "-frames:v", "1", "-vf", "scale=320:180", "-f", "null", "-"],
            timeout=10
        )
        print(f"    - Treapta 4C (FFMPEG SPI Frame 320x180): {'OK' if rc_c == 0 else f'EȘEC (rc={rc_c}: {err_c[:160]})'}")

    print("\n" + "=" * 68)
    print("RAPORT SCURT DE COPIAT:")
    print(json.dumps({
        "session": sesiune,
        "display": disp,
        "fb": fb_devs,
        "ytdlp": ytdlp_v,
        "search_ok": bool(rez),
        "extract_ok": bool(stream_info),
        "progressive": v_url == a_url
    }))
    print("=" * 68)


if __name__ == "__main__":
    ruleaza_diag_youtube()