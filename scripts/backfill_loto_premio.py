"""
backfill_loto_premio.py  (one-off)
Re-pide UN sorteo de Loto por drawId a polla.cl y rellena, IN-PLACE, las columnas
de premio (LOTO_GANADORES/MONTO/POZO_REAL/POZO_ACUMULADO) en la fila ya existente
de data/polla_historial.csv.

Necesario solo para la transición: el último sorteo se guardó antes de que el
scraper persistiera el premio mayor. polla.cl solo expone los sorteos recientes,
así que esto NO sirve para backfillear el histórico antiguo (ver CLAUDE.md).

Uso (local, IP residencial):
    python scripts/backfill_loto_premio.py 5441
"""

import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "scrapers"))
sys.path.insert(0, str(REPO_ROOT / "src" / "parsers"))

from scraper_polla import (  # noqa: E402
    API_URL, BASE_URL, USER_AGENT, GAME_CONFIG, COLUMNS_POLLA,
    obtener_token_csrf,
)
from loto_parser_v3 import parse_loto_rich  # noqa: E402

CSV_PATH = REPO_ROOT / "data" / "polla_historial.csv"
PREMIO_COLS = ["LOTO_GANADORES", "LOTO_MONTO", "LOTO_POZO_REAL", "LOTO_POZO_ACUMULADO"]


async def fetch_draw(draw_id: int) -> dict:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT, ignore_https_errors=True)
        page = await context.new_page()
        page.set_default_timeout(30_000)
        try:
            token = await obtener_token_csrf(page)
            resp = await page.request.post(
                API_URL,
                data={"gameId": GAME_CONFIG["id"], "drawId": draw_id, "csrfToken": token},
                headers={
                    "x-requested-with": "XMLHttpRequest",
                    "Origin":  "https://www.polla.cl",
                    "Referer": BASE_URL,
                },
            )
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            data = await resp.json()
        finally:
            await browser.close()
    if not data or not data.get("results"):
        raise RuntimeError("La respuesta no trae 'results' (¿sorteo inexistente o futuro?)")
    return parse_loto_rich(data)


def actualizar_fila(draw_id: int, raw_row: dict) -> dict:
    if str(raw_row.get("sorteo")) != str(draw_id):
        raise RuntimeError(f"El parser devolvió sorteo {raw_row.get('sorteo')}, esperaba {draw_id}")

    with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))

    objetivo = next((r for r in filas if str(r.get("sorteo")) == str(draw_id)), None)
    if objetivo is None:
        raise RuntimeError(f"No existe la fila del sorteo {draw_id} en el CSV (no se hace append).")

    capturado = {c: raw_row.get(c, "") for c in PREMIO_COLS}
    objetivo.update(capturado)

    # Reescritura completa con el header COLUMNS_POLLA (añade las columnas nuevas;
    # las filas viejas quedan con celdas vacías en esas columnas).
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS_POLLA, extrasaction="ignore")
        w.writeheader()
        for r in filas:
            w.writerow({c: r.get(c, "") for c in COLUMNS_POLLA})
    return capturado


def main():
    draw_id = int(sys.argv[1]) if len(sys.argv) > 1 else 5441
    print(f"[{datetime.now():%H:%M:%S}] Pidiendo sorteo #{draw_id} a polla.cl...")
    raw_row = asyncio.run(fetch_draw(draw_id))
    cap = actualizar_fila(draw_id, raw_row)
    print(f"  Fila #{draw_id} actualizada con premio mayor real:")
    for c in PREMIO_COLS:
        print(f"    {c:<22} = {cap[c]}")


if __name__ == "__main__":
    main()
