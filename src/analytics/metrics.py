"""
metrics.py
Lee los CSVs históricos y genera docs/data/{loto,kino}_metrics.json.
También llama a suggestions.py para incluir 5 combinaciones sugeridas.

Uso:
    python src/analytics/metrics.py --game loto
    python src/analytics/metrics.py --game kino
"""

import argparse
import json
import sys
from itertools import combinations as iter_combinations
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "analytics"))

from suggestions import generar_sugerencias

DATA_DIR  = REPO_ROOT / "data"
DOCS_DATA = REPO_ROOT / "docs" / "data"
DOCS_DATA.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frecuencias(df: pd.DataFrame, cols: list[str], num_range: int) -> dict:
    """Calcula frecuencias absolutas y relativas para cada número del rango."""
    total = len(df)
    nums  = df[cols].values.flatten()
    nums  = nums[~pd.isnull(nums)].astype(int)

    result = {}
    for n in range(1, num_range + 1):
        count = int((nums == n).sum())
        result[str(n)] = {
            "count": count,
            "pct":   round(count / total * 100, 2) if total else 0,
        }
    return result


def _gaps(df: pd.DataFrame, cols: list[str], num_range: int) -> dict:
    """Cuenta cuántos sorteos han pasado desde la última aparición de cada número."""
    result = {}
    rows_rev = df.iloc[::-1]
    for n in range(1, num_range + 1):
        gap = 0
        for _, row in rows_rev.iterrows():
            nums_row = []
            for c in cols:
                try:
                    nums_row.append(int(row[c]))
                except (TypeError, ValueError):
                    pass
            if n in nums_row:
                break
            gap += 1
        result[str(n)] = gap
    return result


def _sum_stats(df: pd.DataFrame, cols: list[str]) -> dict:
    """Estadísticas de la suma de los números de cada sorteo."""
    sumas = df[cols].apply(pd.to_numeric, errors="coerce").sum(axis=1).dropna()
    return {
        "min":  int(sumas.min()),
        "max":  int(sumas.max()),
        "mean": round(float(sumas.mean()), 1),
        "p10":  int(sumas.quantile(0.10)),
        "p25":  int(sumas.quantile(0.25)),
        "p75":  int(sumas.quantile(0.75)),
        "p90":  int(sumas.quantile(0.90)),
    }


def _top_pairs(df: pd.DataFrame, cols: list[str], top_n: int = 10) -> list[dict]:
    """Calcula los pares de números que co-ocurren con mayor frecuencia."""
    pair_count: dict[str, int] = {}
    for _, row in df.iterrows():
        nums = []
        for c in cols:
            try:
                nums.append(int(row[c]))
            except (TypeError, ValueError):
                pass
        for a, b in iter_combinations(sorted(nums), 2):
            key = f"{a}-{b}"
            pair_count[key] = pair_count.get(key, 0) + 1
    top = sorted(pair_count.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [{"pair": k, "count": v} for k, v in top]


def _ultimo_sorteo(df: pd.DataFrame, cols: list[str], comodin_col: str | None) -> dict:
    """Extrae los datos del último sorteo del DataFrame."""
    last = df.iloc[-1]
    nums = []
    for c in cols:
        try:
            nums.append(int(last[c]))
        except (TypeError, ValueError):
            pass
    result = {
        "sorteo": int(last.get("sorteo", 0)) if pd.notna(last.get("sorteo")) else 0,
        "fecha":  str(last.get("fecha", "")),
        "dia":    str(last.get("dia_semana", "")),
        "numeros": nums,
    }
    if comodin_col and comodin_col in last and pd.notna(last[comodin_col]):
        try:
            result["comodin"] = int(last[comodin_col])
        except (TypeError, ValueError):
            pass
    return result


# ---------------------------------------------------------------------------
# Calculadores por juego
# ---------------------------------------------------------------------------

def _metricas_juego(df: pd.DataFrame, prefix: str, num_range: int,
                    pick: int, comodin: bool) -> dict:
    """
    Calcula todas las métricas para un juego dado por su prefijo de columnas.
    Funciona para Loto, Recargado, Revancha, Desquite, Kino, ReKino y RequeteKino.
    """
    num_cols = [f"{prefix}_n{i}" for i in range(1, pick + 1)]
    comodin_col = f"{prefix}_comodin" if comodin else None

    # Filtrar filas que tienen al menos los 6 números del juego
    mask = df[num_cols].apply(pd.to_numeric, errors="coerce").notna().all(axis=1)
    df_clean = df[mask].copy()

    if df_clean.empty:
        return {"total_sorteos": 0, "advertencia": f"Sin datos para {prefix}"}

    total = len(df_clean)
    freq  = _frecuencias(df_clean, num_cols, num_range)
    gs    = _gaps(df_clean, num_cols, num_range)
    ss    = _sum_stats(df_clean, num_cols)
    pairs = _top_pairs(df_clean, num_cols)
    ult   = _ultimo_sorteo(df_clean, num_cols, comodin_col)

    nums_flat = df_clean[num_cols].apply(pd.to_numeric, errors="coerce").values.flatten()
    nums_flat = nums_flat[~pd.isnull(nums_flat)].astype(int)
    pares_pct = round(float((nums_flat % 2 == 0).mean()) * 100, 1)

    return {
        "total_sorteos": total,
        "frequencies":   freq,
        "gaps":          gs,
        "sum_stats":     ss,
        "pares_pct":     pares_pct,
        "top_pairs":     pairs,
        "ultimo_sorteo": ult,
    }


# ---------------------------------------------------------------------------
# Entrada pública
# ---------------------------------------------------------------------------

def generar_loto(df: pd.DataFrame) -> dict:
    """Genera el JSON completo de métricas para Loto (incluye Recargado/Revancha/Desquite)."""
    print("  Calculando Loto principal...")
    base = _metricas_juego(df, "LOTO", num_range=41, pick=6, comodin=True)

    print("  Generando sugerencias Loto...")
    base["suggestions"] = generar_sugerencias(
        df, base, num_range=41, pick=6, num_col_prefix="LOTO"
    )

    print("  Calculando Recargado...")
    base["recargado"] = _metricas_juego(df, "RECARGADO", 41, 6, True)

    print("  Calculando Revancha...")
    base["revancha"]  = _metricas_juego(df, "REVANCHA",  41, 6, True)

    print("  Calculando Desquite...")
    base["desquite"]  = _metricas_juego(df, "DESQUITE",  41, 6, True)

    return base


def generar_kino(df: pd.DataFrame) -> dict:
    """Genera el JSON completo de métricas para Kino (incluye ReKino/RequeteKino).

    Para Kino: la lotería saca 14 números de 41; el apostador elige 6.
    - Las frecuencias, gaps y último sorteo se calculan sobre los 14 sorteados.
    - Las sugerencias son combos de 6 (la elección del apostador).
    """
    print("  Calculando Kino principal...")
    # pick=14 para que las frecuencias, gaps y sum_stats usen todos los 14 números
    base = _metricas_juego(df, "KINO", num_range=41, pick=14, comodin=False)

    print("  Generando sugerencias Kino...")
    # pick=6 para generar combos del apostador (elige 6 de 41)
    base["suggestions"] = generar_sugerencias(
        df, base, num_range=41, pick=6, num_col_prefix="KINO"
    )

    print("  Calculando ReKino...")
    base["rekino"]       = _metricas_juego(df, "REKINO",       41, 14, False)

    print("  Calculando RequeteKino...")
    base["requetekino"]  = _metricas_juego(df, "REQUETEKINO",  41, 14, False)

    return base


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Genera métricas JSON para el frontend.")
    parser.add_argument("--game", required=True, choices=["loto", "kino"],
                        help="Juego a procesar: loto o kino")
    args = parser.parse_args()

    if args.game == "loto":
        csv_path = DATA_DIR / "polla_historial.csv"
        out_path = DOCS_DATA / "loto_metrics.json"
        if not csv_path.exists():
            print(f"ERROR: No se encontró {csv_path}")
            sys.exit(1)
        print(f"Leyendo {csv_path}...")
        df = pd.read_csv(csv_path)
        print(f"  {len(df)} sorteos cargados.")
        data = generar_loto(df)

    else:  # kino
        csv_path = DATA_DIR / "loteria_historial.csv"
        out_path = DOCS_DATA / "kino_metrics.json"
        if not csv_path.exists():
            print(f"ERROR: No se encontró {csv_path}")
            sys.exit(1)
        print(f"Leyendo {csv_path}...")
        df = pd.read_csv(csv_path)
        print(f"  {len(df)} sorteos cargados.")
        data = generar_kino(df)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"OK Guardado en {out_path}")


if __name__ == "__main__":
    main()
