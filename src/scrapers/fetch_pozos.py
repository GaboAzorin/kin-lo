"""
fetch_pozos.py
Obtiene los pozos estimados del próximo sorteo de Kino y Loto.

Fuentes:
  - Kino:  rckino.loteria.cl/api/sorteos  → pozoEstimado por variante (sin restricciones IP)
  - Loto:  polla.cl homepage HTML         → JackpotBanner con prizeAmount
           NOTA: polla.cl bloquea IPs de GitHub Actions → este paso falla en CI.
           El workflow usa continue-on-error: true para que no sea fatal.

Output: docs/data/pozos.json
"""

import json
import logging
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DATA = REPO_ROOT / "docs" / "data"
DOCS_DATA.mkdir(parents=True, exist_ok=True)

OUT_PATH  = DOCS_DATA / "pozos.json"

logger = logging.getLogger("fetch_pozos")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    ch  = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

# ─────────────────────────────────────────────
KINO_VARIANTS = {0: "Kino", 1: "ReKino", 2: "RequeteKino"}

LOTO_GAMES = [
    {"key": "loto",       "label": "Loto"},
    {"key": "recargado",  "label": "Recargado"},
    {"key": "revancha",   "label": "Revancha"},
    {"key": "desquite",   "label": "Desquite"},
]


def _get(url: str, headers: dict) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


# ─────────────────────────────────────────────
def fetch_kino() -> dict:
    """Obtiene pozos de Kino/ReKino/RequeteKino desde rckino.loteria.cl."""
    data = json.loads(_get(
        "https://rckino.loteria.cl/api/sorteos",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept":     "application/json",
            "Referer":    "https://rckino.loteria.cl/resultados",
        }
    ))

    info    = data.get("info", {})
    resumen = info.get("resumen", {})

    result = {
        "proximo_sorteo": resumen.get("fechaProximoSorteo", ""),
        "pozo_total":     resumen.get("pozoTotal", ""),
        "variantes": [],
    }

    for sec in info.get("secciones", []):
        cv = sec.get("codigoVariante")
        if cv not in KINO_VARIANTS:
            continue
        pozo_str = sec.get("pozoEstimado", "") or ""
        # El API devuelve "4.460" → convertir a entero (puntos como separador de miles)
        try:
            millones = int(pozo_str.replace(".", ""))
        except (ValueError, AttributeError):
            millones = 0
        result["variantes"].append({
            "nombre":   KINO_VARIANTS[cv],
            "pozo_str": pozo_str,   # "4.460"
            "millones": millones,   # 4460
        })

    # Ordenar: Kino, ReKino, RequeteKino
    result["variantes"].sort(key=lambda x: list(KINO_VARIANTS.values()).index(x["nombre"]))
    return result


def fetch_loto() -> dict:
    """Obtiene pozos de Loto/Recargado/Revancha/Desquite desde polla.cl homepage."""
    html = _get(
        "https://www.polla.cl/es/",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept":     "text/html",
        }
    ).decode("utf-8", errors="replace")

    # Extraer el bloque JackpotBanner del HTML
    # La estructura es: {"game":{...,"totalPrize":N}} → necesitamos los 2 cierres
    m = re.search(r'"JackpotBanner"\s*:\s*(\{.*?"totalPrize"\s*:\s*\d+\}\s*\})', html, re.DOTALL)
    if not m:
        logger.warning("No se encontró JackpotBanner en polla.cl")
        return {"variantes": [], "advertencia": "No disponible"}

    banner = json.loads(m.group(1))
    game   = banner.get("game", {})

    variantes = []

    # Loto principal
    loto_prize = game.get("prize", 0)
    variantes.append({
        "nombre":   "Loto",
        "millones": round(loto_prize / 1_000_000),
    })

    # Juegos adicionales (Recargado=0, Revancha=1, Desquite=2)
    ADICIONALES = {0: "Recargado", 1: "Revancha", 2: "Desquite"}
    for ag in game.get("additionalGames", []):
        idx = ag.get("additionalGameIndex")
        if idx not in ADICIONALES:
            continue
        prize_raw = ag.get("prize", 0)
        if isinstance(prize_raw, list):
            prize_raw = prize_raw[0] if prize_raw else 0
        variantes.append({
            "nombre":   ADICIONALES[idx],
            "millones": round(prize_raw / 1_000_000),
        })

    return {
        "total_millones": round(game.get("totalPrize", 0) / 1_000_000),
        "variantes": variantes,
    }


# ─────────────────────────────────────────────
def fetch_pozos() -> dict:
    # Cargar datos existentes para preservarlos en caso de error
    existing: dict = {}
    if OUT_PATH.exists():
        try:
            with open(OUT_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    pozos = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M")}

    logger.info("Obteniendo pozos Kino...")
    try:
        pozos["kino"] = fetch_kino()
        logger.info(f"  Kino OK: {pozos['kino']['variantes']}")
    except Exception as e:
        logger.error(f"  Kino error: {e}")
        prev = existing.get("kino", {})
        if prev and "error" not in prev:
            logger.info("  Conservando datos Kino anteriores.")
            pozos["kino"] = prev
        else:
            pozos["kino"] = {"error": str(e), "variantes": []}

    logger.info("Obteniendo pozos Loto...")
    try:
        pozos["loto"] = fetch_loto()
        logger.info(f"  Loto OK: {pozos['loto']['variantes']}")
    except Exception as e:
        logger.error(f"  Loto error: {e}")
        prev = existing.get("loto", {})
        if prev and "error" not in prev:
            logger.info("  Conservando datos Loto anteriores.")
            pozos["loto"] = prev
        else:
            pozos["loto"] = {"error": str(e), "variantes": []}

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(pozos, f, ensure_ascii=False, indent=2)
    logger.info(f"Guardado en {OUT_PATH}")
    return pozos


if __name__ == "__main__":
    fetch_pozos()
