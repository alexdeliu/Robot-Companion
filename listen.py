import speech_recognition as sr

recognizer = sr.Recognizer()
recognizer.dynamic_energy_threshold = False
# Dacă e prea puțin sensibil, poți schimba 300 în 200 sau 150
recognizer.energy_threshold = 300 
recognizer.pause_threshold = 1.5  

mic_index = None
print("\n[SISTEM]: Scanez porturile audio pentru camera web...")
for index, name in enumerate(sr.Microphone.list_microphone_names()):
    if "USB" in name or "Camera" in name or "Audio" in name:
        mic_index = index
        print(f"[SISTEM]: Microfon detectat pe portul {mic_index}: {name}")
        break

try:
    with sr.Microphone(device_index=mic_index, sample_rate=8000) as source:
        # AM ȘTERS AUTO-CALIBRAREA! 
        print("\n[ROBOT]: Te ascult! (Așteaptă 1 secundă și începe să vorbești...)")
        audio = recognizer.listen(source, timeout=5)

    print("\n[SISTEM]: Procesez vocea...")
    
    with open("debug.wav", "wb") as f:
        f.write(audio.get_wav_data())

    text = recognizer.recognize_google(audio, language="ro-RO")
    
    print(f"\n======================================")
    print(f" 🗣️  [TU AI SPUS]: {text} ")
    print(f"======================================\n")

except sr.UnknownValueError:
    print("\n[EROARE]: Nu am înțeles cuvintele. (Ascultă debug.wav pe Windows)")
except Exception as e:
    print(f"\n[EROARE]: {e}")
