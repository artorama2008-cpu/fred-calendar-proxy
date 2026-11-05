import os
import json
import requests

# La clave se lee desde las variables de entorno (GitHub Secret)
API_KEY = os.environ.get("FRED_API_KEY")
if not API_KEY:
    raise ValueError("No se encontró la variable de entorno FRED_API_KEY")

# Endpoint de la API v2 de FRED para fechas de publicación
# Release IDs: 10 = CPI, 50 = Empleo (NFP)
RELEASES = [
    {"id": 10, "type": "CPI", "name": "CPI (FRED)"},
    {"id": 50, "type": "NFP", "name": "Informe de empleo (NFP, FRED)"}
]

all_events = []

for rel in RELEASES:
    url = f"https://api.stlouisfed.org/fred/v2/release/dates?release_id={rel['id']}&file_type=json&include_release_dates_with_no_data=true&sort_order=desc&limit=40"
    
    # La autenticación en v2 se hace con el header Authorization
    headers = {
        "Authorization": f"Bearer {API_KEY}"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Lanza una excepción si el código de estado es 4xx/5xx
        
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
