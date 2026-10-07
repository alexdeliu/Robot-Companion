def proceseaza_comanda(text, limba):
    text = text.lower()
    
    if "vreme" in text or "weather" in text:
        if limba == "ro":
            return {"actiune": "arata_vreme", "mesaj": "Afară plouă."}
        else:
            return {"actiune": "arata_vreme", "mesaj": "It is raining outside."}
            
    elif "gluma" in text or "joke" in text:
        if limba == "ro":
            return {"actiune": "spune_gluma", "mesaj": "Ce face un hacker pe barcă? Piraterie!"}
        else:
            return {"actiune": "spune_gluma", "mesaj": "Why do programmers prefer dark mode? Because light attracts bugs!"}
            
    else:
        if limba == "ro":
            return {"actiune": "vorbeste_normal", "mesaj": "Te ascult."}
        else:
            return {"actiune": "vorbeste_normal", "mesaj": "I am listening."}

if __name__ == "__main__":
    # Aici setăm limba manual pentru test: "ro" sau "en"
    limba_selectata = "ro" 
    print(f"Robotul a pornit în limba: {limba_selectata.upper()}")
    
    while True:
        intrare = input("Tu: ")
        if intrare.lower() == "exit":
            break
            
        # Acum funcția primește și textul, și limba!
        raspuns_robot = proceseaza_comanda(intrare, limba_selectata)
        print(f"Robotul: {raspuns_robot}\n")