import urllib.request
import urllib.parse
import json

# Traducem codurile satelitului în cuvinte clare pentru AI
WMO_CODES = {
    0: "Senin", 1: "Mai mult senin", 2: "Parțial înnorat", 3: "Înnorat",
    45: "Ceață", 48: "Ceață înghețată", 51: "Burniță ușoară", 53: "Burniță", 55: "Burniță densă",
    61: "Ploaie ușoară", 63: "Ploaie moderată", 65: "Ploaie torențială",
    71: "Ninsoare ușoară", 73: "Ninsoare moderată", 75: "Ninsoare abundentă",
    95: "Furtună cu descărcări", 96: "Furtună cu grindină"
}

def get_weather(city="Timișoara"):
    city_url = urllib.parse.quote(city)
    geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city_url}&count=1&language=ro&format=json"
    
    try:
        geo_response = urllib.request.urlopen(geo_url)
        geo_data = json.loads(geo_response.read())
        
        if not geo_data.get('results'):
            return f"Eroare sistem: Nu am găsit coordonatele pentru {city}."
            
        lat = geo_data['results'][0]['latitude']
        lon = geo_data['results'][0]['longitude']
        real_name = geo_data['results'][0]['name']
        
        # ACUM CEREM PROGNOZA PE 5 ZILE! (Max, Min, Ploaie, Vreme)
        meteo_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto"
        meteo_response = urllib.request.urlopen(meteo_url)
        meteo_data = json.loads(meteo_response.read())
        
        # Construim "Raportul Brut" pentru AI
        current_temp = meteo_data['current_weather']['temperature']
        current_wmo = meteo_data['current_weather']['weathercode']
        conditie_acum = WMO_CODES.get(current_wmo, "Necunoscut")
        
        raport = f"Locație reală: {real_name}\n"
        raport += f"Vremea Acum: {current_temp}°C, Condiție: {conditie_acum}\n\n"
        raport += "Prognoza pe zile (Ziua 0 = azi, Ziua 1 = mâine, etc):\n"
        
        daily = meteo_data['daily']
        for i in range(5):
            data_zi = daily['time'][i]
            max_t = daily['temperature_2m_max'][i]
            min_t = daily['temperature_2m_min'][i]
            ploaie = daily['precipitation_probability_max'][i]
            wmo_zi = daily['weathercode'][i]
            conditie_zi = WMO_CODES.get(wmo_zi, "Necunoscut")
            
            raport += f"- Data: {data_zi} | Max: {max_t}°C | Min: {min_t}°C | Șanse ploaie: {ploaie}% | Vreme: {conditie_zi}\n"
            
        return raport
        
    except Exception as e:
        return f"Eroare senzor pentru {city}: {e}"