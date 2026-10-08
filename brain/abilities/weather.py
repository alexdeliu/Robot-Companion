import urllib.request
import urllib.parse
import json

def get_weather(city="Timișoara"):
    # 1. Transformăm numele orașului pentru internet (ex: "New York" -> "New%20York")
    city_url = urllib.parse.quote(city)
    
    # 2. Căutăm coordonatele pe tot globul pentru orașul cerut
    geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city_url}&count=1&language=ro&format=json"
    
    try:
        geo_response = urllib.request.urlopen(geo_url)
        geo_data = json.loads(geo_response.read())
        
        # Dacă ai zis un oraș inventat (ex: "Atlantida"), îi spunem robotului că nu există
        if not geo_data.get('results'):
            return f"Nu am reușit să găsesc orașul {city} pe harta satelitului."
            
        # Extragem coordonatele reale găsite
        lat = geo_data['results'][0]['latitude']
        lon = geo_data['results'][0]['longitude']
        real_name = geo_data['results'][0]['name']
        
        # 3. Cerem vremea exactă pentru acele coordonate
        meteo_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        meteo_response = urllib.request.urlopen(meteo_url)
        meteo_data = json.loads(meteo_response.read())
        
        temperature = meteo_data['current_weather']['temperature']
        
        return f"În {real_name} sunt momentan {temperature} grade Celsius."
        
    except Exception as e:
        return f"Eroare de conexiune la satelit pentru {city}."