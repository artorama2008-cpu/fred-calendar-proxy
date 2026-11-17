import os
import re
import sys
import json
import html
import time
import datetime as dt
import requests

# ============================================================================
# Genera fred_dates.json con las fechas macro que lee la app:
#   - CPI y NFP  -> FRED (calendario real del BLS, release 10 y 50)
#   - FOMC       -> página oficial de la Reserva Federal (federalreserve.gov)
# La release 101 de FRED ("FOMC Press Release") NO es un calendario de reuniones:
# tiene una entrada cada día, así que ya no se usa.
# Si una fuente falla, se conservan las fechas anteriores de ese tipo; si no hay
# nada anterior para CPI o NFP, el script termina con error SIN sobrescribir el archivo.
# ============================================================================

# La clave se lee desde las variables de entorno (GitHub Secret)
API_KEY = os.environ.get("FRED_API_KEY")
OUTPUT = "fred_dates.json"

RELEASES = [
    {"id": 10, "type": "CPI", "name": "CPI (FRED)"},
    {"id": 50, "type": "NFP", "name": "Informe de empleo (NFP, FRED)"},
]

FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
UA = {"User-Agent": "Mozilla/5.0 (compatible; macro-calendar-bot/1.0)"}


def mask(msg):
    """Nunca imprimir la clave en los logs."""
    return str(msg).replace(API_KEY, "***") if API_KEY else str(msg)


def http_get(url, tries=3, **kw):
    last = None
    for n in range(tries):
        try:
            r = requests.get(url, timeout=30, **kw)
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(2 * (n + 1))
    raise RuntimeError(mask(last))


# ------------------------------- FRED (CPI, NFP) -----------------------------
def fetch_fred_release(rel):
    r = http_get(
        "https://api.stlouisfed.org/fred/release/dates",
        params={
            "release_id": rel["id"],
            "api_key": API_KEY,
            "file_type": "json",
            "include_release_dates_with_no_data": "true",
            "sort_order": "desc",
            "limit": 40,
        },
    )
    data = r.json()
    dates = data.get("release_dates")
    if not isinstance(dates, list):
        raise ValueError(data.get("error_message", "respuesta inesperada de FRED"))
    return [
        {"date": d["date"], "name": rel["name"], "type": rel["type"], "after": 0, "source": "FRED"}
        for d in dates if isinstance(d, dict) and d.get("date")
    ]


# --------------------------- Reserva Federal (FOMC) --------------------------
MONTH_NUM = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MON = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December"
       r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")
# "January 27-28", "March 17-18*", "Apr/May 30-1", "January 25-26, 2028"
RANGE_RE = re.compile(rf"\b({MON})(?:\s*/\s*({MON}))?\s+(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})\*?(?:\s*,\s*(\d{{4}}))?")
HEADING_RE = re.compile(r"(\d{4})\s+FOMC\s+Meetings")


def to_text(raw):
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw))


def parse_decision_dates(page):
    """Día de la decisión (2.º día de cada reunión) de todas las reuniones de la página."""
    text = to_text(page)
    heads = [(m.start(), int(m.group(1))) for m in HEADING_RE.finditer(text)]
    if not heads:
        raise ValueError('No se encontraron secciones "AAAA FOMC Meetings" en la página de la Fed.')
    found = set()
    for idx, (pos, year) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(text)
        for m in RANGE_RE.finditer(text, pos, end):
            m1, m2, d1, d2, explicit_year = m.group(1), m.group(2), int(m.group(3)), int(m.group(4)), m.group(5)
            y = int(explicit_year) if explicit_year else year
            first_month = MONTH_NUM[m1[:3].lower()]
            dec_month = MONTH_NUM[m2[:3].lower()] if m2 else first_month
            dec_year = y + 1 if dec_month < first_month else y          # p. ej. Dec/Jan
            if not m2 and d2 < d1:
                continue
            try:
                dt.date(y, first_month, d1)
                d = dt.date(dec_year, dec_month, d2)
            except ValueError:
                continue
            if d.weekday() < 5:                                          # una decisión nunca cae en fin de semana
                found.add(d)
    return sorted(found)


def validate_fomc(dates, today=None):
    today = today or dt.date.today()
    this_year = [d for d in dates if d.year == today.year]
    if not (6 <= len(this_year) <= 10):
        raise ValueError(f"El año {today.year} tiene {len(this_year)} reuniones (se esperaban entre 6 y 10): "
                         "probablemente la página de la Fed cambió de formato.")
    if not any(d >= today for d in dates):
        raise ValueError("No hay ninguna reunión futura en la página de la Fed.")


def fetch_fomc_events(today=None):
    today = today or dt.date.today()
    dates = parse_decision_dates(http_get(FED_URL, headers=UA).text)
    validate_fomc(dates, today)
    keep_from = dt.date(today.year - 1, 1, 1)
    return [{"date": d.isoformat(), "name": "FOMC (decisión, Fed)", "type": "FOMC", "after": 1, "source": "FED"}
            for d in sorted(dates, reverse=True) if d >= keep_from]


# ----------------------------------- main ------------------------------------
def load_previous():
    try:
        with open(OUTPUT, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, ValueError):
        return []


def main():
    if not API_KEY:
        print("❌ No se encontró la variable de entorno FRED_API_KEY")
        return 1
    previous = load_previous()
    events, missing = [], []

    for rel in RELEASES:
        try:
            ev = fetch_fred_release(rel)
            print(f"✅ {rel['type']}: {len(ev)} fechas obtenidas (FRED).")
        except Exception as e:
            old = [x for x in previous if isinstance(x, dict) and x.get("type") == rel["type"]]
            if old:
                ev = old
                print(f"⚠️ {rel['type']}: no se pudo consultar FRED ({mask(e)}). Se conservan las {len(old)} fechas anteriores.")
            else:
                ev = []
                missing.append(rel["type"])
                print(f"❌ {rel['type']}: no se pudo consultar FRED ({mask(e)}) y no hay datos anteriores.")
        events.extend(ev)

    try:
        fomc = fetch_fomc_events()
        print(f"✅ FOMC: {len(fomc)} fechas obtenidas (Reserva Federal).")
        upcoming = [x["date"] for x in reversed(fomc) if x["date"] >= dt.date.today().isoformat()][:6]
        print("   Próximas decisiones:", ", ".join(upcoming))
    except Exception as e:
        fomc = [x for x in previous if isinstance(x, dict) and x.get("type") == "FOMC" and x.get("source") == "FED"]
        print(f"⚠️ FOMC: no se pudo leer la página de la Fed ({mask(e)}). Se conservan {len(fomc)} fechas anteriores; "
              "la app usa además su lista de respaldo.")
    events.extend(fomc)

    if missing:
        print(f"❌ Faltan datos de {', '.join(missing)}: NO se sobrescribe {OUTPUT}.")
        return 1

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)
    print(f"✅ Archivo {OUTPUT} generado con {len(events)} eventos en total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
