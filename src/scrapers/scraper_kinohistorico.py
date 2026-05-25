"""
scraper_kinohistorico.py
Descarga resultados históricos de Kino desde la API REST de kinohistorico.cl.

Endpoint: https://kinohistorico.cl/kino-api/draws?page=N&limit=50
Cobertura: ~2433 sorteos desde 2006 hasta los más recientes.

Uso:
    python src/scrapers/scraper_kinohistorico.py [--desde N]

    --desde N  Solo descargar sorteos con número >= N (útil para actualizaciones incrementales)
               Por defecto descarga TODO lo que no esté ya en el CSV.
"""

import sys
import argparse
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH  = REPO_ROOT / "data" / "loteria_historial.csv"

API_BASE  = "https://kinohistorico.cl/kino-api"
PAGE_SIZE = 50
DELAY     = 0.3   # segundos entre requests
SAVE_EVERY = 200  # guardar en disco cada N filas nuevas

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
    "Accept": "application/json",
    "Referer": "https://kinohistorico.cl/",
}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def fetch_page(page: int) -> dict | None:
    url = f"{API_BASE}/draws?page={page}&limit={PAGE_SIZE}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"  Error en página {page}: {e}")
        return None


def fetch_single(sorteo_id: int) -> dict | None:
    """Obtiene un sorteo individual por número."""
    url = f"{API_BASE}/draws/{sorteo_id}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8", errors="replace"))
            if d.get("code") == 200:
                return d["data"]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Conversión de registro de API → fila CSV
# ---------------------------------------------------------------------------

def build_row(draw_data: dict) -> dict | None:
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

    # Verificar que KINO tiene datos
    if "KINO_n1" not in row:
        return None

    # Rellenar juegos faltantes con None (sorteos muy antiguos no tienen ReKino)
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


def merge_and_save(df: pd.DataFrame, new_rows: list[dict]) -> pd.DataFrame:
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
    parser = argparse.ArgumentParser(description="Descarga historial Kino desde kinohistorico.cl API")
    parser.add_argument("--desde", type=int, default=0,
                        help="Solo bajar sorteos con número >= N (0 = todo)")
    args = parser.parse_args()

    df, existing = load_csv()

    # Obtener total de páginas disponibles
    print("\nConsultando metadata de la API...")
    first = fetch_page(1)
    if not first or first.get("code") != 200:
        print("ERROR: No se pudo conectar con la API")
        sys.exit(1)

    meta = first.get("meta", {})
    total_draws  = meta.get("total", 0)
    total_pages  = meta.get("total_pages", 0)
    print(f"  Total sorteos disponibles: {total_draws}")
    print(f"  Total páginas (limit={PAGE_SIZE}): {total_pages}")

    new_rows   = []
    total_new  = 0
    skip_count = 0

    # Recorrer desde la última página (más antiguos) a la primera (más recientes)
    # Para evitar duplicados con el CSV existente, saltamos los que ya tenemos.
    print(f"\nDescargando {total_pages} páginas de más antigua a más reciente...\n")

    for page in range(total_pages, 0, -1):
        resp = fetch_page(page)
        if not resp or resp.get("code") != 200:
            print(f"  Página {page}: ERROR")
            time.sleep(1)
            continue

        draws = resp.get("data", [])

        for draw in draws:
            sid = draw.get("draw_number", 0)

            # Filtro --desde
            if args.desde > 0 and sid < args.desde:
                skip_count += 1
                continue

            if sid in existing:
                skip_count += 1
                continue

            row = build_row(draw)
            if row:
                new_rows.append(row)
                existing.add(sid)
                total_new += 1

        # Progreso cada 10 páginas
        if (total_pages - page + 1) % 10 == 0 or page == 1:
            page_done = total_pages - page + 1
            oldest = draws[-1]['draw_number'] if draws else '?'
            newest = draws[0]['draw_number'] if draws else '?'
            print(f"  Página {page_done}/{total_pages} | "
                  f"sorteos {oldest}–{newest} | "
                  f"nuevos acumulados: {total_new}")

        # Guardar periódicamente
        if total_new > 0 and total_new % SAVE_EVERY == 0 and new_rows:
            df = merge_and_save(df, new_rows)
            new_rows = []
            print(f"  --- Guardado parcial: {len(df)} filas ---")

        time.sleep(DELAY)

    # Guardado final
    df = merge_and_save(df, new_rows)
    print(f"\nFIN.")
    print(f"  Nuevos sorteos guardados: {total_new}")
    print(f"  Sorteos ya existentes (saltados): {skip_count}")
    print(f"  CSV final: {len(df)} filas | "
          f"sorteos {int(df['sorteo'].min())}–{int(df['sorteo'].max())}")


if __name__ == "__main__":
    main()
