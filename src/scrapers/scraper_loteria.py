"""
scraper_loteria.py
Descarga resultados de Kino, ReKino y RequeteKino desde rckino.loteria.cl.

API descubierta: https://rckino.loteria.cl/api/sorteos
  - Sin parámetros → últimos 26 sorteos
  - ?sorteo=N → datos del sorteo N (solo válido si N está en los últimos 26)

Limitación conocida: el API solo expone los últimos 26 sorteos por ventana.
El scraper captura los nuevos en cada ejecución y los acumula en el CSV.
"""

import csv
import json
import logging
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# ==============================================================================
# RUTAS
# ==============================================================================
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR  = REPO_ROOT / "data"
LOGS_DIR  = REPO_ROOT / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

CSV_OUT = DATA_DIR / "loteria_historial.csv"

# ==============================================================================
# LOGGING
# ==============================================================================
logger = logging.getLogger("scraper_loteria")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    fh = logging.FileHandler(
        LOGS_DIR / f"scraper_loteria_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
        encoding="utf-8"
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

# ==============================================================================
# CONSTANTES
# ==============================================================================
API_BASE = "https://rckino.loteria.cl/api/sorteos"

API_HEADERS = {
    "User-Agent":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":     "https://rckino.loteria.cl/resultados",
    "Accept":      "application/json, text/plain, */*",
    "Accept-Language": "es-CL,es;q=0.9",
}

# Mapeo de codigoVariante → prefijo de columnas en el CSV
VARIANT_MAP = {
    0: "KINO",
    1: "REKINO",
    2: "REQUETEKINO",
}

NUMBERS_PER_DRAW = 14  # El sorteo saca 14 números

COLUMNS_LOTERIA = (
    ["sorteo", "fecha", "dia_semana"]
    + [f"KINO_n{i}"         for i in range(1, NUMBERS_PER_DRAW + 1)]
    + [f"REKINO_n{i}"       for i in range(1, NUMBERS_PER_DRAW + 1)]
    + [f"REQUETEKINO_n{i}"  for i in range(1, NUMBERS_PER_DRAW + 1)]
)

DELAY_SECONDS = 0.6

# ==============================================================================
# HELPERS
# ==============================================================================

def _fetch_api(sorteo: int | None = None) -> dict:
    url = API_BASE + (f"?sorteo={sorteo}" if sorteo is not None else "")
    req = urllib.request.Request(url, headers=API_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _parse_bolitas(bolitas_str: str, prefix: str) -> dict:
    """
    Convierte '01,02,03,...,24' en {KINO_n1: 1, KINO_n2: 2, ..., KINO_n14: 24}.
    Los números se ordenan numéricamente antes de asignar las columnas.
    """
    if not bolitas_str:
        return {}
    nums = sorted(int(x) for x in bolitas_str.split(",") if x.strip().isdigit())
    return {f"{prefix}_n{i+1}": nums[i] for i in range(min(NUMBERS_PER_DRAW, len(nums)))}


def _get_draw_data(sorteo_num: int) -> dict | None:
    """
    Obtiene los datos completos de un sorteo específico.
    Retorna None si no hay datos disponibles.
    """
    data   = _fetch_api(sorteo_num)
    info   = data.get("info", {})
    secciones = info.get("secciones", [])
    resumen   = info.get("resumen", {})

    # Fecha: "24/05/2026" → "2026-05-24"
    fecha_str = resumen.get("fechaSorteo", "")
    try:
        dt = datetime.strptime(fecha_str, "%d/%m/%Y")
        fecha_iso  = dt.strftime("%Y-%m-%d")
        dia_semana = dt.strftime("%A")
    except ValueError:
        fecha_iso  = ""
        dia_semana = ""

    row: dict = {
        "sorteo":     sorteo_num,
        "fecha":      fecha_iso,
        "dia_semana": dia_semana,
    }

    # Números por variante
    for sec in secciones:
        variant_code = sec.get("codigoVariante")
        prefix = VARIANT_MAP.get(variant_code)
        if prefix and sec.get("bolitas"):
            row.update(_parse_bolitas(sec["bolitas"], prefix))

    # Solo guardar si tenemos al menos los 14 números del Kino principal
    return row if f"KINO_n{NUMBERS_PER_DRAW}" in row else None


def _get_existing_sorteos() -> set[int]:
    """Lee el CSV y devuelve el set de sorteos ya guardados."""
    if not CSV_OUT.exists():
        return set()
    existing: set[int] = set()
    try:
        with open(CSV_OUT, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("sorteo", "").isdigit():
                    existing.add(int(row["sorteo"]))
    except (IOError, csv.Error) as e:
        logger.warning(f"Error leyendo CSV: {e}")
    return existing


def _guardar_fila(row: dict):
    """Escribe una fila al CSV (append). Crea el header si no existe."""
    file_exists = CSV_OUT.exists() and CSV_OUT.stat().st_size > 10
    with open(CSV_OUT, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS_LOTERIA)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in COLUMNS_LOTERIA})


# ==============================================================================
# SCRAPER PRINCIPAL
# ==============================================================================

def scrape_loteria() -> int:
    """
    Descarga todos los sorteos nuevos disponibles en la API y los guarda.
    Retorna el número de sorteos nuevos guardados.
    """
    logger.info("Iniciando scraping loteria.cl (Kino)...")

    # 1. Obtener la ventana actual de sorteos disponibles
    try:
        data   = _fetch_api()
        window = data.get("info", {}).get("sorteosDisponibles", [])
    except Exception as e:
        logger.error(f"No se pudo conectar con la API: {e}")
        return 0

    if not window:
        logger.warning("La API devolvió una ventana vacía.")
        return 0

    logger.info(f"API window: {min(window)}..{max(window)} ({len(window)} sorteos disponibles)")

    # 2. Filtrar solo los sorteos que no están en el CSV
    existing    = _get_existing_sorteos()
    new_sorteos = sorted([s for s in window if s not in existing])

    if not new_sorteos:
        logger.info("Sin sorteos nuevos. CSV ya está al día.")
        return 0

    logger.info(f"Sorteos nuevos a descargar: {new_sorteos}")

    # 3. Descargar y guardar
    saved = 0
    for sorteo_num in new_sorteos:
        try:
            row = _get_draw_data(sorteo_num)
            if row:
                _guardar_fila(row)
                logger.info(
                    f"#{sorteo_num} guardado — {row.get('fecha','')} ({row.get('dia_semana','')})"
                    f" | KINO: {','.join(str(row.get(f'KINO_n{i}','?')) for i in range(1,15))}"
                )
                saved += 1
            else:
                logger.warning(f"#{sorteo_num}: datos incompletos, omitido.")
            time.sleep(DELAY_SECONDS)
        except Exception as e:
            logger.error(f"#{sorteo_num}: {e}")

    logger.info(f"✓ Scraping completado: {saved} sorteos nuevos guardados.")
    return saved


# ==============================================================================
# ENTRADA PRINCIPAL
# ==============================================================================

if __name__ == "__main__":
    scrape_loteria()
