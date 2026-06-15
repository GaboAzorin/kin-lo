"""
agregar_sorteo_manual.py
Agrega un sorteo de Kino ingresado manualmente (en vivo) al CSV histórico.

Guarda una fila PROVISIONAL: solo los 14 números del Kino; ReKino y RequeteKino
quedan vacíos. El scraper programado (scraper_loteria.py) los completa después.

Entrada: variable de entorno PAYLOAD con un JSON {sorteo, fecha, numeros[]},
tal como llega en client_payload de un evento repository_dispatch.
Alternativa local: --sorteo N --fecha YYYY-MM-DD --numeros "1,2,...".
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Reutiliza columnas / rutas / writer del scraper para no duplicar el esquema.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_loteria import (  # noqa: E402
    COLUMNS_LOTERIA,
    CSV_OUT,
    NUMBERS_PER_DRAW,
    _get_existing_sorteos,
    _guardar_fila,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("agregar_manual")


def _cargar_payload() -> dict:
    """Lee el sorteo desde --args o, si no, desde la env PAYLOAD (repository_dispatch)."""
    parser = argparse.ArgumentParser(description="Agrega un sorteo Kino manual al CSV.")
    parser.add_argument("--sorteo", type=int)
    parser.add_argument("--fecha", type=str, help="YYYY-MM-DD")
    parser.add_argument("--numeros", type=str, help="coma-separados, ej: 1,2,5,...")
    args = parser.parse_args()

    if args.sorteo is not None:
        return {
            "sorteo": args.sorteo,
            "fecha": args.fecha or "",
            "numeros": [int(x) for x in (args.numeros or "").split(",") if x.strip()],
        }

    raw = os.environ.get("PAYLOAD", "").strip()
    if not raw:
        sys.exit("ERROR: sin --sorteo ni variable de entorno PAYLOAD.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: PAYLOAD no es JSON válido: {e}")


def _validar(payload: dict) -> tuple[int, str, list[int]]:
    try:
        sorteo = int(payload["sorteo"])
    except (KeyError, TypeError, ValueError):
        sys.exit("ERROR: 'sorteo' inválido o ausente.")
    if sorteo < 1:
        sys.exit("ERROR: 'sorteo' debe ser >= 1.")

    fecha = (payload.get("fecha") or "").strip() or datetime.now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(fecha, "%Y-%m-%d")
    except ValueError:
        sys.exit(f"ERROR: fecha '{fecha}' no es YYYY-MM-DD.")

    try:
        numeros = sorted({int(n) for n in payload.get("numeros", [])})
    except (TypeError, ValueError):
        sys.exit("ERROR: 'numeros' contiene valores no numéricos.")
    if len(numeros) != NUMBERS_PER_DRAW:
        sys.exit(f"ERROR: se requieren {NUMBERS_PER_DRAW} números únicos, llegaron {len(numeros)}.")
    if any(n < 1 or n > 25 for n in numeros):
        sys.exit("ERROR: los números deben estar entre 1 y 25.")

    return sorteo, fecha, numeros


def main() -> None:
    sorteo, fecha, numeros = _validar(_cargar_payload())

    if sorteo in _get_existing_sorteos():
        logger.info(f"#{sorteo} ya existe en el CSV — no se hace nada.")
        return

    dia_semana = datetime.strptime(fecha, "%Y-%m-%d").strftime("%A")
    row = {"sorteo": sorteo, "fecha": fecha, "dia_semana": dia_semana}
    for i, n in enumerate(numeros, start=1):
        row[f"KINO_n{i}"] = n
    # REKINO_* / REQUETEKINO_* quedan vacíos → fila provisional.

    _guardar_fila({k: row.get(k, "") for k in COLUMNS_LOTERIA})
    logger.info(
        f"✓ #{sorteo} provisional guardado — {fecha} ({dia_semana}) | "
        f"KINO: {','.join(map(str, numeros))}"
    )


if __name__ == "__main__":
    main()
