"""
scraper_kinohistorico.py
Descarga resultados históricos de Kino desde kinohistorico.cl
Recorre desde el sorteo indicado hacia atrás hasta el sorteo 1 (o hasta 10 fallos consecutivos).

Uso:
    python src/scrapers/scraper_kinohistorico.py [--desde N]
"""

import sys
import argparse
import json
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH  = REPO_ROOT / "data" / "loteria_historial.csv"

COLUMNS = [
    "sorteo", "fecha", "dia_semana",
    "KINO_n1",  "KINO_n2",  "KINO_n3",  "KINO_n4",  "KINO_n5",
    "KINO_n6",  "KINO_n7",  "KINO_n8",  "KINO_n9",  "KINO_n10",
    "KINO_n11", "KINO_n12", "KINO_n13", "KINO_n14",
    "REKINO_n1",  "REKINO_n2",  "REKINO_n3",  "REKINO_n4",  "REKINO_n5",
    "REKINO_n6",  "REKINO_n7",  "REKINO_n8",  "REKINO_n9",  "REKINO_n10",
    "REKINO_n11", "REKINO_n12", "REKINO_n13", "REKINO_n14",
    "REQUETEKINO_n1",  "REQUETEKINO_n2",  "REQUETEKINO_n3",  "REQUETEKINO_n4",
    "REQUETEKINO_n5",  "REQUETEKINO_n6",  "REQUETEKINO_n7",  "REQUETEKINO_n8",
    "REQUETEKINO_n9",  "REQUETEKINO_n10", "REQUETEKINO_n11", "REQUETEKINO_n12",
    "REQUETEKINO_n13", "REQUETEKINO_n14",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html",
    "Accept-Language": "es-CL,es;q=0.9",
}

DELAY_OK   = 0.4   # segundos entre requests exitosos
DELAY_FAIL = 1.0   # segundos tras un fallo
MAX_CONSEC = 10    # fallos consecutivos antes de detener
SAVE_EVERY = 100   # guardar en disco cada N filas nuevas


# ---------------------------------------------------------------------------
# Fetch + Parse
# ---------------------------------------------------------------------------

def fetch_html(sorteo_id: int) -> str | None:
    url = f"https://kinohistorico.cl/draw/{sorteo_id}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  HTTP error: {e}")
        return None


def parse_html(html: str, sorteo_id: int) -> dict | None:
    """
    Extrae el bloque de datos Angular TransferState de los scripts del HTML.
    Devuelve el objeto `data` del sorteo o None si no se encuentra.
    """
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    for s in scripts:
        if '"draw_number"' not in s and '"draw_date"' not in s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        # Angular TransferState: {"<hash>": {"b": {"data": {...}}}}
        for val in obj.values():
            if not isinstance(val, dict):
                continue
            inner = val.get("b", {})
            if not isinstance(inner, dict):
                continue
            draw_data = inner.get("data", {})
            if isinstance(draw_data, dict) and draw_data.get("draw_number") == sorteo_id:
                return draw_data
    return None


def build_row(draw_data: dict) -> dict | None:
    """Convierte el dict de datos del sorteo en una fila de CSV."""
    draw_number = draw_data.get("draw_number")
    date_str    = draw_data.get("draw_date", "")

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None

    row: dict = {
        "sorteo":     draw_number,
        "fecha":      dt.strftime("%Y-%m-%d"),
        "dia_semana": dt.strftime("%A"),
    }

    games = draw_data.get("games", [])
    for game in games:
        code    = game.get("game_code", "")
        numbers = game.get("numbers", [])
        if code in ("KINO", "REKINO", "REQUETEKINO") and len(numbers) == 14:
            for i, n in enumerate(numbers, 1):
                row[f"{code}_n{i}"] = n

    # Verificar que al menos KINO tenga datos
    if "KINO_n1" not in row:
        return None

    # Rellenar juegos faltantes (ReKino/RequeteKino no siempre existen en sorteos antiguos)
    for prefix in ("REKINO", "REQUETEKINO"):
        if f"{prefix}_n1" not in row:
            for i in range(1, 15):
                row[f"{prefix}_n{i}"] = None

    return row


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def load_csv() -> tuple[pd.DataFrame, set[int]]:
    if CSV_PATH.exists():
        df = pd.read_csv(CSV_PATH)
        existing = set(df["sorteo"].dropna().astype(int).tolist())
        print(f"CSV cargado: {len(df)} filas | "
              f"sorteos {int(df['sorteo'].min())}–{int(df['sorteo'].max())}")
        return df, existing
    else:
        print("CSV no encontrado. Creando desde cero.")
        return pd.DataFrame(columns=COLUMNS), set()


def save_csv(df: pd.DataFrame, new_rows: list[dict]) -> pd.DataFrame:
    if not new_rows:
        return df
    new_df   = pd.DataFrame(new_rows, columns=COLUMNS)
    combined = pd.concat([df, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset="sorteo")
    combined = combined.sort_values("sorteo").reset_index(drop=True)
    combined.to_csv(CSV_PATH, index=False)
    return combined


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scraper histórico kinohistorico.cl")
    parser.add_argument("--desde", type=int, default=3205,
                        help="Sorteo desde el que comenzar (hacia atrás)")
    args = parser.parse_args()

    df, existing = load_csv()

    start      = args.desde
    new_rows   = []
    consec_fail = 0
    total_new   = 0

    print(f"\nIniciando barrido desde sorteo {start} hacia atras...\n")

    for sorteo_id in range(start, 0, -1):
        if sorteo_id in existing:
            consec_fail = 0  # resetear porque no es un fallo, solo un skip
            continue

        print(f"  [{sorteo_id}] ", end="", flush=True)
        html = fetch_html(sorteo_id)

        if html is None:
            consec_fail += 1
            print(f"HTTP FAIL  ({consec_fail}/{MAX_CONSEC})")
            if consec_fail >= MAX_CONSEC:
                print("  Demasiados fallos consecutivos. Deteniendo.")
                break
            time.sleep(DELAY_FAIL)
            continue

        # Página "vacía" = sin datos (Angular shell sin TransferState de este sorteo)
        # El tamaño de la página sin datos ronda los 133 KB
        if len(html) < 140_000:
            consec_fail += 1
            print(f"sin datos  ({consec_fail}/{MAX_CONSEC})")
            if consec_fail >= MAX_CONSEC:
                print("  Demasiados fallos consecutivos. Deteniendo.")
                break
            time.sleep(DELAY_FAIL)
            continue

        draw_data = parse_html(html, sorteo_id)
        if draw_data is None:
            consec_fail += 1
            print(f"parse fail ({consec_fail}/{MAX_CONSEC})")
            if consec_fail >= MAX_CONSEC:
                print("  Demasiados fallos consecutivos. Deteniendo.")
                break
            time.sleep(DELAY_FAIL)
            continue

        row = build_row(draw_data)
        if row is None:
            consec_fail += 1
            print(f"row fail   ({consec_fail}/{MAX_CONSEC})")
            if consec_fail >= MAX_CONSEC:
                break
            time.sleep(DELAY_FAIL)
            continue

        consec_fail = 0
        print(f"OK  {row['fecha']}  KINO={row.get('KINO_n1','?')}..{row.get('KINO_n14','?')}")
        new_rows.append(row)
        existing.add(sorteo_id)
        total_new += 1

        # Guardar periódicamente
        if total_new % SAVE_EVERY == 0:
            df = save_csv(df, new_rows)
            new_rows = []
            print(f"\n  --- Guardado parcial: {len(df)} filas en CSV ---\n")

        time.sleep(DELAY_OK)

    # Guardado final
    df = save_csv(df, new_rows)
    print(f"\nFIN. Total nuevos sorteos guardados: {total_new}")
    print(f"CSV final: {len(df)} filas | sorteos {int(df['sorteo'].min())}–{int(df['sorteo'].max())}")


if __name__ == "__main__":
    main()
