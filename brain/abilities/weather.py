import time
import urllib.request
import urllib.parse
import json

WMO_CODES = {
    0: "Senin", 1: "Mai mult senin", 2: "Parțial înnorat", 3: "Înnorat",
    45: "Ceață", 48: "Ceață cu îngheț", 51: "Burniță ușoară", 53: "Burniță", 55: "Burniță densă",
    61: "Ploaie ușoară", 63: "Ploaie moderată", 65: "Ploaie torențială",
    71: "Ninsoare ușoară", 73: "Ninsoare moderată", 75: "Ninsoare abundentă",
    95: "Furtună cu descărcări electrice", 96: "Furtună cu grindină"
}

# Coordonate pre-salvate pentru a elimina primul apel HTTP (Geocoding) pentru orașele frecvente
_COORDONATE_CACHE = {
    "timișoara": (45.7537, 21.2257, "Timișoara"),
    "timisoara": (45.7537, 21.2257, "Timișoara"),
    "bucurești": (44.4323, 26.1063, "București"),
    "bucuresti": (44.4323, 26.1063, "București"),
    "cluj": (46.7667, 23.6000, "Cluj-Napoca"),
    "cluj-napoca": (46.7667, 23.6000, "Cluj-Napoca"),
    "iași": (47.1622, 27.5889, "Iași"),
    "iasi": (47.1622, 27.5889, "Iași"),
    "brașov": (45.6486, 25.6061, "Brașov"),
    "brasov": (45.6486, 25.6061, "Brașov"),
    "constanța": (44.1807, 28.6343, "Constanța"),
    "constanta": (44.1807, 28.6343, "Constanța"),
    "arad": (46.1833, 21.3167, "Arad"),
    "oradea": (47.0667, 21.9333, "Oradea"),
    "sibiu": (45.8000, 24.1500, "Sibiu"),
    "craiova": (44.3167, 23.8000, "Craiova"),
}

# Cache pentru prognoză (valabil 10 minute = 600 secunde)
_METEO_CACHE = {}
_DURATA_CACHE_SEC = 600

def _obtine_coordonate(city):
    cheie = city.strip().lower()
    if cheie in _COORDONATE_CACHE:
        return _COORDONATE_CACHE[cheie]

    city_url = urllib.parse.quote(city)
    geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city_url}&count=1&language=ro&format=json"
    with urllib.request.urlopen(geo_url, timeout=4) as geo_response:
        geo_data = json.loads(geo_response.read())

    if not geo_data.get('results'):
        return None

    rezultat = geo_data['results'][0]
    date_oras = (rezultat['latitude'], rezultat['longitude'], rezultat['name'])
    _COORDONATE_CACHE[cheie] = date_oras
    return date_oras

def get_weather(city="Timișoara"):
    oras_cautat = city.strip() if city and city.strip() else "Timișoara"
    cheie_cache = oras_cautat.lower()
    acum = time.time()

    # Dacă avem deja vremea descărcată în ultimele 10 minute, o returnăm în 0.0001 secunde!
    if cheie_cache in _METEO_CACHE:
        timp_salvare, raport_salvat = _METEO_CACHE[cheie_cache]
        if acum - timp_salvare < _DURATA_CACHE_SEC:
            return raport_salvat

    try:
        coordonate = _obtine_coordonate(oras_cautat)
        if not coordonate:
            return f"Eroare sistem: Nu am găsit coordonatele pentru {oras_cautat}."

        lat, lon, real_name = coordonate

        meteo_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&current_weather=true&daily=weathercode,temperature_2m_max,temperature_2m_min,"
            f"precipitation_probability_max&timezone=auto"
        )
        with urllib.request.urlopen(meteo_url, timeout=4) as meteo_response:
            meteo_data = json.loads(meteo_response.read())

        current_temp = meteo_data['current_weather']['temperature']
        current_wmo = meteo_data['current_weather']['weathercode']
        conditie_acum = WMO_CODES.get(current_wmo, "Necunoscut")

        raport = f"Locație reală: {real_name}\n"
        raport += f"Vremea Acum: {current_temp}°C, Condiție: {conditie_acum}\n\n"
        raport += "Prognoza pe zile (Ziua 0 = azi, Ziua 1 = mâine, etc):\n"

        daily = meteo_data['daily']
        for i in range(min(5, len(daily['time']))):
            data_zi = daily['time'][i]
            max_t = daily['temperature_2m_max'][i]
            min_t = daily['temperature_2m_min'][i]
            ploaie = daily['precipitation_probability_max'][i]
            wmo_zi = daily['weathercode'][i]
            conditie_zi = WMO_CODES.get(wmo_zi, "Necunoscut")

            raport += f"- Data: {data_zi} | Max: {max_t}°C | Min: {min_t}°C | Șanse ploaie: {ploaie}% | Vreme: {conditie_zi}\n"

        _METEO_CACHE[cheie_cache] = (acum, raport)
        return raport

    except Exception as e:
        return f"Eroare senzor pentru {oras_cautat}: {e}"