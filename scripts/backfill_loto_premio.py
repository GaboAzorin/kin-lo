"""
backfill_loto_premio.py
Re-pide sorteos de Loto por `drawId` a polla.cl y rellena, IN-PLACE, las columnas de
premio y el comodín en las filas ya existentes de data/polla_historial.csv.

La API responde a cualquier `drawId` del histórico, no solo a los recientes: se
verificó hasta el sorteo 4000 con el desglose de premios completo. Los sorteos
guardados antes de que el scraper persistiera estas columnas se pueden recuperar.

Uso (local, IP residencial — polla.cl bloquea las IPs de GitHub Actions):
    python scripts/backfill_loto_premio.py 5441            # un sorteo
    python scripts/backfill_loto_premio.py 5430 5455       # un rango, inclusivo
    python scripts/backfill_loto_premio.py 5430 5455 --forzar   # reescribe lo ya lleno

Por omisión salta las filas que ya tienen los premios cargados, así que se puede
re-correr sobre un rango grande sin repetir trabajo. Reusa una sola sesión de
navegador y revalida el token CSRF cada 20 minutos.
"""

import argparse
import asyncio
import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "scrapers"))
sys.path.insert(0, str(REPO_ROOT / "src" / "parsers"))

from scraper_polla import (  # noqa: E402
    API_URL, BASE_URL, USER_AGENT, GAME_CONFIG, COLUMNS_POLLA,
    CATEGORIAS_LOTO, CATEGORIAS_SUBJUEGOS, _SUFIJOS_PREMIO,
    obtener_token_csrf,
)
from loto_parser_v3 import parse_loto_rich  # noqa: E402

CSV_PATH = REPO_ROOT / "data" / "polla_historial.csv"

# Todo lo que el scraper guarda y no son los números de los cuatro juegos.
PREMIO_COLS = (
    ["LOTO_comodin"]
    + [f"{c}{s}" for c in CATEGORIAS_LOTO for s in _SUFIJOS_PREMIO]
    + [f"{c}{s}" for c in CATEGORIAS_SUBJUEGOS for s in _SUFIJOS_PREMIO]
    + ["LOTO_POZO_ACUMULADO"]
)

# Si esta columna ya tiene valor, la fila se considera backfilleada.
COL_TESTIGO = "TERNA_3_ACIERTOS_MONTO"

DELAY_SEGUNDOS = 0.5
TOKEN_REFRESH_MINUTES = 20


def _leer_csv() -> list[dict]:
    with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _escribir_csv(filas: list[dict]):
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS_POLLA, extrasaction="ignore")
        w.writeheader()
        for r in filas:
            w.writerow({c: r.get(c, "") for c in COLUMNS_POLLA})


async def backfill(desde: int, hasta: int, forzar: bool) -> int:
    filas = _leer_csv()
    por_sorteo = {str(r.get("sorteo")): r for r in filas}

    objetivo = []
    for n in range(desde, hasta + 1):
        fila = por_sorteo.get(str(n))
        if fila is None:
            continue  # no se hace append: solo se rellenan filas existentes
        if not forzar and str(fila.get(COL_TESTIGO, "")).strip():
            continue
        objetivo.append(n)

    if not objetivo:
        print("Nada que hacer: todas las filas del rango ya tienen premios.")
        return 0

    print(f"{len(objetivo)} sorteo(s) por rellenar entre #{desde} y #{hasta}.")
    actualizados = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT,
                                            ignore_https_errors=True)
        page = await context.new_page()
        page.set_default_timeout(45_000)
        try:
            token = await obtener_token_csrf(page)
            token_ts = datetime.now()

            for n in objetivo:
                if datetime.now() - token_ts > timedelta(minutes=TOKEN_REFRESH_MINUTES):
                    token = await obtener_token_csrf(page)
                    token_ts = datetime.now()

                await asyncio.sleep(DELAY_SEGUNDOS)
                try:
                    resp = await page.request.post(
                        API_URL,
                        data={"gameId": GAME_CONFIG["id"], "drawId": n,
                              "csrfToken": token},
                        headers={"x-requested-with": "XMLHttpRequest",
                                 "Origin": "https://www.polla.cl",
                                 "Referer": BASE_URL},
                    )
                    if resp.status != 200:
                        print(f"  #{n}: HTTP {resp.status} — omitido")
                        continue
                    data = await resp.json()
                    if not data or not data.get("results"):
                        print(f"  #{n}: sin 'results' — omitido")
                        continue
                    row = parse_loto_rich(data)
                except Exception as e:
                    print(f"  #{n}: error {e} — omitido")
                    continue

                if str(row.get("sorteo")) != str(n):
                    print(f"  #{n}: la API devolvió el sorteo {row.get('sorteo')} — omitido")
                    continue

                por_sorteo[str(n)].update({c: row.get(c, "") for c in PREMIO_COLS})
                actualizados += 1
                print(f"  #{n}: comodín={row.get('LOTO_comodin')} "
                      f"terna={row.get('TERNA_3_ACIERTOS_MONTO')} "
                      f"pozo_6={row.get('LOTO_POZO_REAL')}")
        finally:
            await browser.close()

    if actualizados:
        _escribir_csv(filas)
        print(f"\n{actualizados} fila(s) actualizadas en {CSV_PATH.name}.")
    return actualizados


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("desde", type=int, help="primer sorteo (inclusive)")
    ap.add_argument("hasta", type=int, nargs="?",
                    help="último sorteo (inclusive). Por omisión, igual a `desde`.")
    ap.add_argument("--forzar", action="store_true",
                    help="reescribe también las filas que ya tienen premios")
    args = ap.parse_args()

    hasta = args.hasta if args.hasta is not None else args.desde
    if hasta < args.desde:
        print("ERROR: `hasta` es menor que `desde`.", file=sys.stderr)
        return 1

    print(f"[{datetime.now():%H:%M:%S}] Backfill de premios Loto #{args.desde}..#{hasta}")
    asyncio.run(backfill(args.desde, hasta, args.forzar))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
