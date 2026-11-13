import os
import sys
import time
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


def _pompeaza(root, secunde=0.3):
    """Lasă Tk să proceseze evenimentele și temporizările, ca într-o rulare reală."""
    final = time.monotonic() + secunde
    while time.monotonic() < final:
        root.update()
        time.sleep(0.01)


def ruleaza_test_fata():
    """Ecranul cu fața animată (face.enabled): moduri, overlay-uri, stări și revenirea la interfața clasică."""
    import main as modul_main
    import face.controller as modul_fata
    from config import CFG

    # Fără Gemini și fără rețea: salutul și răspunsurile sunt înlocuite cu răspunsuri goale
    modul_main.genereaza_salut_pornire = lambda *a, **kw: {"mesaj": ""}
    modul_main.proceseaza_comanda_ai = lambda *a, **kw: {"actiune": "vorbeste_normal", "mesaj": ""}
    # Salutul pornește fire care cheamă Tk; testul nu rulează mainloop, deci îl sărim
    modul_main.RobotCompanionUI.porneste_salut_initial = lambda self: None
    CFG.setdefault("face", {})["enabled"] = True

    probleme = []
    raport = []

    def verifica(nume, conditie):
        print(f"  [{'OK' if conditie else 'PROBLEMA'}] {nume}")
        if not conditie:
            probleme.append(nume)

    print("=" * 78)
    print(" TEST ECRAN CU FAȚA (face.enabled = true)")
    print("=" * 78)
    root = tk.Tk()
    ui = RobotCompanionUI(root)
    try:
        _pompeaza(root, 0.8)
        ui.oprire_wake_event.set()
        fata = ui.fata
        verifica("fața a pornit", fata is not None)
        if fata is None:
            return 1
        sw, sh = ui.screen_width, ui.screen_height

        def deasupra(a, b):
            copii = root.winfo_children()
            return copii.index(a) > copii.index(b)

        def atinge():
            fata._t_comutare = 0.0
            fata._t_apasare = time.monotonic()
            fata._mangaiat = False
            fata._elibereaza(None)
            _pompeaza(root, 0.15)

        verifica("mod față: fața acoperă barele", fata.mod == "fata" and deasupra(fata.canvas, ui.bara_top)
                 and deasupra(fata.canvas, ui.bara_jos))
        atinge()
        verifica("o atingere aduce barele peste față", fata.mod == "controale" and deasupra(ui.bara_top, fata.canvas)
                 and deasupra(ui.bara_jos, fata.canvas))
        ui.adapteaza_toate_butoanele()
        root.update_idletasks()
        _colecteaza_butoane(ui.bara_top, "Fata:Controale", raport, sw, sh)
        _colecteaza_butoane(ui.bara_jos, "Fata:Controale", raport, sw, sh)
        verifica("MIC, STOP, WAKE, DND și ✕ sunt pe ecran după o atingere",
                 len(raport) >= 9 and all(r[4] == "OK" for r in raport))
        atinge()
        verifica("a doua atingere arată chatul, cu mini-fața în bara de sus",
                 fata.mod == "chat" and not fata.canvas.winfo_ismapped()
                 and str(ui.btn_status.cget("image")) != "")
        fata.arata_fata()
        _pompeaza(root, 0.1)
        verifica("revenirea la față scoate mini-fața", fata.mod == "fata" and fata.canvas.winfo_ismapped()
                 and str(ui.btn_status.cget("image")) == "")

        ui.afiseaza_overlay_status()
        _pompeaza(root, 0.3)
        verifica("un overlay retrage fața", fata.mod == "chat" and not fata.canvas.winfo_ismapped())
        ui.ascunde_overlay()
        _pompeaza(root, 0.3)
        verifica("închiderea overlay-ului readuce fața", fata.mod == "fata")
        ui.toggle_tastatura()
        _pompeaza(root, 0.3)
        verifica("tastatura retrage fața", fata.mod == "chat")
        ui.toggle_tastatura()
        _pompeaza(root, 0.3)
        verifica("închiderea tastaturii readuce fața", fata.mod == "fata")

        def stare(nume):
            ui._seteaza_stare_ui(nume)
            _pompeaza(root, 0.12)
            return fata.motor.expresie_curenta

        verifica("LISTENING -> atent", stare("LISTENING") == "atent")
        verifica("THINKING -> gânditor", stare("THINKING") == "ganditor")
        ui._fata_eveniment("actiune", actiune="spune_gluma")
        verifica("glumă: vorbește ironic", stare("SPEAKING") == "ironic")
        verifica("glumă: râde la final", stare("IDLE") == "ras")
        stare("VIDEO")
        verifica("VIDEO oprește complet fața", fata.motor.oprit)
        stare("IDLE")
        verifica("după VIDEO fața repornește", not fata.motor.oprit)
        ui._fata_eveniment("dnd", activ=True)
        verifica("DND adoarme fața", fata.motor.stadiu_somn == 3)
        ui._fata_eveniment("dnd", activ=False)
        verifica("ieșirea din DND o trezește", fata.motor.stadiu_somn == 0)
        ui.afiseaza_mesaj("Tu", "salut robot")
        verifica("ce spui apare ca subtitrare", "salut robot" in fata.canvas.itemcget(fata._txt_sub, "text"))

        # Gura după voce: un ton de 0,6 s încărcat direct, apoi notificările pe care le trimite voice.speak
        from array import array
        import math
        ton = array("h", (int(9000 * math.sin(2 * math.pi * 220 * i / 16000.0)) for i in range(9600))).tobytes()
        fata.lipsync.offset_s = 0.0
        fata.lipsync.incarca_pcm(ton)
        ui._la_redare_voce("pornit", t=time.monotonic())
        deschidere = 0.0
        final = time.monotonic() + 0.45
        while time.monotonic() < final:
            root.update()
            deschidere = max(deschidere, fata.motor._gura_afisata)
            time.sleep(0.01)
        verifica("când pornește vocea, gura se deschide după sunet", fata.motor._vorbire and deschidere > 0.5)
        ui._la_redare_voce("oprit")
        _pompeaza(root, 0.1)
        verifica("când se oprește vocea, gura se închide", not fata.motor._vorbire and fata.motor._gura_afisata == 0.0)

        def _strica(*a, **kw):
            raise RuntimeError("eroare simulată de test")

        fata.motor.tick = _strica
        fata.arata_fata()
        _pompeaza(root, 0.3)
        verifica("o eroare în față o dezactivează și lasă interfața clasică",
                 ui.fata is None and not fata.canvas.winfo_ismapped())
        ui.afiseaza_mesaj("Sistem", "Interfața clasică merge în continuare.")
        ui._seteaza_stare_ui("IDLE")
        _pompeaza(root, 0.1)
        verifica("interfața clasică rămâne funcțională", ui.text_display.winfo_ismapped())
        original = modul_fata.ControllerFata
        modul_fata.ControllerFata = _strica
        try:
            ui._porneste_fata()
        finally:
            modul_fata.ControllerFata = original
        verifica("dacă fața nu pornește, aplicația merge mai departe", ui.fata is None)
    finally:
        CFG["face"]["enabled"] = False
        ui.inchide_curat()

    print("-" * 78)
    for ecran, txt, dim, tw, st in raport:
        print(f"{ecran:<18} | {txt:<18} | {dim:<9} | {tw:<7} | {st}")
    print("=" * 78)
    print(f"TEST FAȚĂ: {len(probleme)} PROBLEME")
    print("=" * 78)
    return 1 if probleme else 0


if __name__ == "__main__":
    cod = ruleaza_ui_selftest()
    cod_fata = ruleaza_test_fata()
    sys.exit(1 if (cod or cod_fata) else 0)