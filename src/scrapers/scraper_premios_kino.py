"""
scraper_premios_kino.py
Captura el desglose de GANADORES POR CATEGORÍA de cada sorteo de Kino desde
rckino.loteria.cl. Esta info NO está en loteria_historial.csv (que solo guarda
los números sorteados) y NO es backfilleable: kinohistorico.cl solo expone el
winners_count de la categoría máxima (14 aciertos ≈ siempre 0).

Solo la API de loteria.cl entrega las categorías bajas (10-13 aciertos, miles de
ganadores), y solo para los últimos ~26 sorteos. Por eso este scraper acumula la
data de aquí en adelante: cada corrida agrega los sorteos nuevos al CSV.

Sirve para estimar cuántos cartones se jugaron (ver src/analytics/estimar_cartones.py).

Uso:
    python src/scrapers/scraper_premios_kino.py
"""

import csv
import json
import logging
import time
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR  = REPO_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CSV_OUT = DATA_DIR / "kino_premios_historial.csv"

logger = logging.getLogger("scraper_premios_kino")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)

API_BASE = "https://rckino.loteria.cl/api/sorteos"
API_HEADERS = {
    "User-Agent":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":     "https://rckino.loteria.cl/resultados",
    "Accept":      "application/json, text/plain, */*",
    "Accept-Language": "es-CL,es;q=0.9",
}

# Solo los 3 juegos "Kino" core (las variantes promocionales 3,4,5,98,99 se ignoran).
VARIANT_MAP = {0: "KINO", 1: "REKINO", 2: "REQUETEKINO"}

COLUMNS = ["sorteo", "fecha", "game_code", "codigo_categoria",
           "aciertos", "ganadores", "premio_total", "premio_individual"]

DELAY_SECONDS = 0.6


def _fetch_api(sorteo: int | None = None) -> dict:
    url = API_BASE + (f"?sorteo={sorteo}" if sorteo is not None else "")
    req = urllib.request.Request(url, headers=API_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        # La API responde en ISO-8859-1, no UTF-8.
        return json.loads(r.read().decode("latin-1"))


def _money(s: str) -> int:
    """'$5.293.396.883' -> 5293396883 ; '-' / '' -> 0"""
    s = (s or "").replace("$", "").replace(".", "").strip()
    return int(s) if s.isdigit() else 0


def _qty(s: str) -> int:
    """'27.767' -> 27767"""
    s = (s or "").replace(".", "").strip()
    return int(s) if s.isdigit() else 0


def _aciertos(nombre: str) -> int | None:
    """'14 Aciertos' -> 14 ; categorías que no son por aciertos -> None"""
    first = (nombre or "").split()[:1]
    return int(first[0]) if first and first[0].isdigit() else None


def _rows_for_sorteo(sorteo_num: int) -> list[dict]:
    data = _fetch_api(sorteo_num)
    info = data.get("info", {})
    resumen = info.get("resumen", {})
    fecha_str = resumen.get("fechaSorteo", "")
    try:
        fecha_iso = datetime.strptime(fecha_str, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        fecha_iso = ""

    rows: list[dict] = []
    for sec in info.get("secciones", []):
        game = VARIANT_MAP.get(sec.get("codigoVariante"))
        if not game:
            continue
        for cat in sec.get("categorias", []):
            ac = _aciertos(cat.get("nombreCategoria", ""))
            if ac is None:
                continue
            rows.append({
                "sorteo":            sorteo_num,
                "fecha":             fecha_iso,
                "game_code":         game,
                "codigo_categoria":  cat.get("codigoCategoria", ""),
                "aciertos":          ac,
                "ganadores":         _qty(cat.get("ganadores", {}).get("cantidad", "")),
                "premio_total":      _money(cat.get("premioTotal", "")),
                "premio_individual": _money(cat.get("premioIndividual", "")),
            })
    return rows


def _existing_sorteos() -> set[int]:
    if not CSV_OUT.exists():
        return set()
    seen: set[int] = set()
    with open(CSV_OUT, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("sorteo", "").isdigit():
                seen.add(int(row["sorteo"]))
    return seen


def _append_rows(rows: list[dict]):
    file_exists = CSV_OUT.exists() and CSV_OUT.stat().st_size > 10
    with open(CSV_OUT, "a", encoding="utf-8", newline="\n") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def scrape_premios() -> int:
    logger.info("Capturando premios/ganadores por categoría desde loteria.cl...")
    try:
        window = _fetch_api().get("info", {}).get("sorteosDisponibles", [])
    except Exception as e:
        logger.error(f"No se pudo conectar con la API: {e}")
        return 0
    if not window:
        logger.warning("Ventana vacía.")
        return 0

    existing = _existing_sorteos()
    nuevos = sorted(s for s in window if s not in existing)
    if not nuevos:
        logger.info(f"Sin sorteos nuevos. CSV al día ({len(existing)} sorteos).")
        return 0

    logger.info(f"Ventana {min(window)}..{max(window)} | nuevos a capturar: {nuevos}")
    saved = 0
    for s in nuevos:
        try:
            rows = _rows_for_sorteo(s)
            if rows:
                _append_rows(rows)
                kino_cats = sum(1 for r in rows if r["game_code"] == "KINO")
                logger.info(f"#{s} guardado: {len(rows)} categorías ({kino_cats} de KINO)")
                saved += 1
            else:
                logger.warning(f"#{s}: sin categorías por aciertos, omitido.")
            time.sleep(DELAY_SECONDS)
        except Exception as e:
            logger.error(f"#{s}: {e}")
    logger.info(f"✓ {saved} sorteos nuevos capturados.")
    return saved


if __name__ == "__main__":
    scrape_premios()
