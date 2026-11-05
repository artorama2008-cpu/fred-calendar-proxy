import os
import json
import requests

# La clave se lee desde las variables de entorno (GitHub Secret)
API_KEY = os.environ.get("FRED_API_KEY")
if not API_KEY:
    raise ValueError("No se encontró la variable de entorno FRED_API_KEY")

# Endpoint de la API v1 de FRED para fechas de publicación (release/dates)
RELEASES = [
    {"id": 10, "type": "CPI", "name": "CPI (FRED)"},
    {"id": 50, "type": "NFP", "name": "Informe de empleo (NFP, FRED)"},
    {"id": 101, "type": "FOMC", "name": "FOMC (decisión, FRED)"} # <-- Añadido el ID 101
]

all_events = []

for rel in RELEASES:
    # URL de la API v1: sin /v2/ y con api_key como parámetro de consulta
    url = (
        f"https://api.stlouisfed.org/fred/release/dates?"
        f"release_id={rel['id']}&"
        f"api_key={API_KEY}&"
        f"file_type=json&"
        f"include_release_dates_with_no_data=true&"
        f"sort_order=desc&"
        f"limit=40"
    )
    
    try:
        # La autenticación v1 va en la URL, no en las cabeceras
        response = requests.get(url)
        response.raise_for_status()
        
        data = response.json()
        dates = data.get("release_dates", [])
        
        for d in dates:
            all_events.append({
                "date": d["date"],
                "name": rel["name"],
                "type": rel["type"],
                "after": 0,
                "source": "FRED"
            })
        print(f"✅ {rel['type']}: {len(dates)} fechas obtenidas.")
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al consultar {rel['type']}: {e}")

# Guardar los eventos en un archivo JSON
with open("fred_dates.json", "w", encoding="utf-8") as f:
    json.dump(all_events, f, indent=2, ensure_ascii=False)

print(f"✅ Archivo fred_dates.json generado con {len(all_events)} eventos en total.")
