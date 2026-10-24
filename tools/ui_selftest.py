import os
import sys
import tkinter as tk
import tkinter.font as tkfont

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import voice.speak
import ears.listen
import ears.wake_word
import brain.abilities.youtube_player

# Dezactivăm apelurile audio/rețea în timpul testului geometric de UI
voice.speak.vorbeste = lambda *a, **kw: None
ears.listen.preincalzeste_microfon = lambda *a, **kw: None
ears.wake_word.asteapta_wake_word = lambda *a, **kw: False
brain.abilities.youtube_player.deschide_overlay_youtube = lambda *a, **kw: True

from main import RobotCompanionUI


def _colecteaza_butoane(widget, nume_ecran, rezultate, sw, sh):
    for w in widget.winfo_children():
        if isinstance(w, tk.Button) and w.winfo_ismapped():
            w.update_idletasks()
            bx, by = w.winfo_rootx(), w.winfo_rooty()
            bw, bh = w.winfo_width(), w.winfo_height()
            txt = str(w.cget("text")).strip()
            cmd = str(w.cget("command")).strip()
            f_obj = tkfont.Font(font=w.cget("font"))
            tw = f_obj.measure(txt)

            probleme = []
            if not cmd:
                probleme.append("FARA_COMANDA")
            if tw > bw - 4:
                probleme.append(f"TEXT_DEPASIT({tw}>{bw})")
            if bx < 0 or by < 0 or (bx + bw) > sw + 2 or (by + bh) > sh + 2:
                probleme.append("IN_AFARA_ECRANULUI")
            if bw < 28 or bh < 24:
                probleme.append(f"PREA_MIC({bw}x{bh})")

            status = "OK" if not probleme else ",".join(probleme)
            rezultate.append((nume_ecran, txt[:18], f"{bw}x{bh}", f"{tw}px", status))
        elif isinstance(w, tk.Frame) and w.winfo_ismapped():
            _colecteaza_butoane(w, nume_ecran, rezultate, sw, sh)


def ruleaza_ui_selftest():
    root = tk.Tk()
    ui = RobotCompanionUI(root)
    ui.oprire_wake_event.set()
    root.update_idletasks()
    root.update()

    sw, sh = ui.screen_width, ui.screen_height
    raport = []

    # 1. Ecranul principal
    ui.adapteaza_toate_butoanele()
    root.update_idletasks()
    _colecteaza_butoane(root, "MainScreen", raport, sw, sh)

    # 2. Overlay Status
    ui.afiseaza_overlay_status()
    root.update_idletasks()
    _colecteaza_butoane(ui.frame_overlay, "Overlay:Status", raport, sw, sh)

    # 3. Overlay Wikipedia
    ui.afiseaza_overlay_wikipedia({"titlu": "Timișoara", "rezumat": "Test UI.", "partea_curenta": 1, "total_parti": 3})
    root.update_idletasks()
    _colecteaza_butoane(ui.frame_overlay, "Overlay:Wiki", raport, sw, sh)

    # 4. Overlay Lista YouTube
    rez_mock = [{"numar": i, "video_id": f"id{i}", "titlu": f"Videoclip Test {i}", "canal": "Test", "durata": "3:20"} for i in range(1, 6)]
    ui.afiseaza_overlay_youtube_lista(" muzică rock ", rez_mock)
    root.update_idletasks()
    _colecteaza_butoane(ui.frame_overlay, "Overlay:YTList", raport, sw, sh)

    # 5. Overlay Video Activ
    ui.afiseaza_overlay_video_activ(rez_mock[0], asteapta_tts=True)
    root.update_idletasks()
    _colecteaza_butoane(ui.frame_overlay, "Overlay:YTVideo", raport, sw, sh)

    # 6. Overlay YouTube Music
    ui.afiseaza_overlay_youtube_music(rez_mock[0])
    root.update_idletasks()
    _colecteaza_butoane(ui.frame_overlay, "Overlay:YTMusic", raport, sw, sh)

    ui.inchide_curat()

    print("=" * 78)
    print(f" RAPORT UI SELFTEST (Rezoluție detectată: {sw}x{sh} px)")
    print("=" * 78)
    print(f"{'ECRAN / OVERLAY':<18} | {'TEXT BUTON':<18} | {'DIM(px)':<9} | {'TEXT_W':<7} | {'STATUS'}")
    print("-" * 78)
    erori = 0
    for ecran, txt, dim, tw, st in raport:
        if st != "OK":
            erori += 1
        print(f"{ecran:<18} | {txt:<18} | {dim:<9} | {tw:<7} | {st}")
    print("=" * 78)
    print(f"TOTAL BUTOANE VERIFICATE: {len(raport)} | PROBLEME: {erori}")
    print("=" * 78)
    return 1 if erori else 0


if __name__ == "__main__":
    sys.exit(ruleaza_ui_selftest())