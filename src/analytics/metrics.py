"""
metrics.py
Lee los CSVs históricos y genera docs/data/{loto,kino}_metrics.json.
Registra sugerencias pendientes y las compara contra resultados reales
para acumular un historial de aciertos por rango en suggestions_history.csv.

Uso:
    python src/analytics/metrics.py --game loto
    python src/analytics/metrics.py --game kino
"""

import argparse
import csv
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

PENDING_LOTO = DATA_DIR / "loto_suggestions_pending.json"
PENDING_KINO = DATA_DIR / "kino_suggestions_pending.json"
HISTORY_PATH = DATA_DIR / "suggestions_history.csv"
HISTORY_COLS = ["juego", "sorteo_predicho", "fecha_sorteo", "rango", "combo", "aciertos"]

# ---------------------------------------------------------------------------
# Rangos para sugerencias
# ---------------------------------------------------------------------------
SUGGESTION_RANGES = [50, 100, 250, 500, 1000]  # "all" siempre se añade al final

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
# Tracking: pending → evaluación → historial
# ---------------------------------------------------------------------------

def _cargar_pending(path: Path) -> dict | None:
    """Lee el archivo de sugerencias pendientes. Devuelve None si no existe."""
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _guardar_pending(path: Path, tras_sorteo: int, sugerencias: dict):
    """Guarda las sugerencias actuales para comparar en el próximo run."""
    obj = {"generado_tras_sorteo": tras_sorteo, "sugerencias": sugerencias}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"  Pending guardado: sugerencias para sorteo posterior a #{tras_sorteo}.")


def _evaluar_y_registrar(df: pd.DataFrame, juego: str,
                          num_cols: list[str], pending: dict) -> int:
    """
    Compara las sugerencias pendientes contra el primer resultado real
    posterior al sorteo en que fueron generadas.
    Appends filas a suggestions_history.csv y retorna cuántas se agregaron.
    """
    tras_sorteo = pending.get("generado_tras_sorteo")
    if tras_sorteo is None:
        return 0

    # Primer sorteo > tras_sorteo disponible en el CSV
    df_num = df.copy()
    df_num["_s"] = pd.to_numeric(df_num["sorteo"], errors="coerce")
    siguientes = df_num[df_num["_s"] > tras_sorteo].sort_values("_s")

    if siguientes.empty:
        print(f"  Sin resultado posterior a sorteo #{tras_sorteo} todavía.")
        return 0

    fila     = siguientes.iloc[0]
    sorteo_n = int(fila["_s"])
    fecha    = str(fila.get("fecha", ""))

    resultado = []
    for c in num_cols:
        try:
            resultado.append(int(fila[c]))
        except (TypeError, ValueError):
            pass
    if not resultado:
        return 0

    # Evitar duplicados
    if HISTORY_PATH.exists() and HISTORY_PATH.stat().st_size > 10:
        df_h = pd.read_csv(HISTORY_PATH)
        if ((df_h["juego"] == juego) &
                (pd.to_numeric(df_h["sorteo_predicho"], errors="coerce") == sorteo_n)).any():
            print(f"  Sorteo #{sorteo_n} ya estaba en el historial. Omitido.")
            return 0

    resultado_set = set(resultado)
    filas_nuevas  = []
    for rango, combos in pending.get("sugerencias", {}).items():
        for s in combos:
            combo    = s["combo"]
            aciertos = len(set(combo) & resultado_set)
            filas_nuevas.append({
                "juego":           juego,
                "sorteo_predicho": sorteo_n,
                "fecha_sorteo":    fecha,
                "rango":           rango,
                "combo":           ",".join(str(n) for n in combo),
                "aciertos":        aciertos,
            })

    if not filas_nuevas:
        return 0

    file_exists = HISTORY_PATH.exists() and HISTORY_PATH.stat().st_size > 10
    with open(HISTORY_PATH, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(filas_nuevas)

    print(f"  Evaluado sorteo #{sorteo_n} ({fecha}) | resultado: {sorted(resultado_set)}")
    for rango in pending.get("sugerencias", {}).keys():
        rf    = [r for r in filas_nuevas if r["rango"] == rango]
        max_a = max(r["aciertos"] for r in rf)
        avg_a = sum(r["aciertos"] for r in rf) / len(rf)
        print(f"    [{rango:>4}] max={max_a}  avg={avg_a:.2f}")

    return len(filas_nuevas)


def _range_scores(juego: str) -> dict:
    """
    Lee suggestions_history.csv y calcula el rendimiento promedio por rango.
    Devuelve {} si no hay historial todavía.
    """
    if not HISTORY_PATH.exists():
        return {}
    df_h = pd.read_csv(HISTORY_PATH)
    df_h = df_h[df_h["juego"] == juego]
    if df_h.empty:
        return {}

    result = {}
    for rango, grp in df_h.groupby("rango"):
        result[str(rango)] = {
            "sorteos_evaluados": int(grp["sorteo_predicho"].nunique()),
            "aciertos_avg":      round(float(grp["aciertos"].mean()), 2),
            "aciertos_max":      int(grp["aciertos"].max()),
        }
    return result


# ---------------------------------------------------------------------------
# Sugerencias por rango
# ---------------------------------------------------------------------------

def _stats_ligeros(df: pd.DataFrame, cols: list[str], num_range: int) -> dict:
    """
    Stats mínimos para generar sugerencias (frequencies + sum_stats).
    Más rápido que _metricas_juego(): omite gaps, top_pairs y ultimo_sorteo.
    """
    mask  = df[cols].apply(pd.to_numeric, errors="coerce").notna().all(axis=1)
    df_c  = df[mask].copy()
    if df_c.empty:
        return {"total_sorteos": 0}
    return {
        "total_sorteos": len(df_c),
        "frequencies":   _frecuencias(df_c, cols, num_range),
        "sum_stats":     _sum_stats(df_c, cols),
    }


def _sugerencias_por_rango(df_full: pd.DataFrame, prefix: str,
                            num_range: int, pick: int) -> dict:
    """
    Genera 3 sugerencias por cada rango válido (últimos N sorteos + todos).

    - Estadísticas calculadas sobre el slice del rango.
    - Unicidad verificada contra df_full (historial completo).

    Devuelve un dict con claves "50", "100", "250", "500", "1000", "all"
    (solo incluye los rangos donde N < total de sorteos disponibles).
    """
    cols  = [f"{prefix}_n{i}" for i in range(1, pick + 1)]
    total = len(df_full)
    rangos = [n for n in SUGGESTION_RANGES if n < total] + [None]  # None → "all"

    result: dict = {}
    for n in rangos:
        label    = str(n) if n is not None else "all"
        df_rango = df_full.tail(n) if n is not None else df_full
        stats    = _stats_ligeros(df_rango, cols, num_range)
        if stats.get("total_sorteos", 0) == 0:
            continue
        result[label] = generar_sugerencias(
            df_rango, stats,
            num_range=num_range, pick=pick,
            n_sugerencias=3, num_col_prefix=prefix,
            df_history=df_full,
        )
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

    print("  Generando sugerencias Loto (por rango)...")
    base["suggestions"] = _sugerencias_por_rango(df, "LOTO", num_range=41, pick=6)

    print("  Calculando Recargado...")
    base["recargado"] = _metricas_juego(df, "RECARGADO", 41, 6, True)

    print("  Calculando Revancha...")
    base["revancha"]  = _metricas_juego(df, "REVANCHA",  41, 6, True)

    print("  Calculando Desquite...")
    base["desquite"]  = _metricas_juego(df, "DESQUITE",  41, 6, True)

    return base


def generar_kino(df: pd.DataFrame) -> dict:
    """Genera el JSON completo de métricas para Kino (incluye ReKino/RequeteKino).

    Kino real: el apostador elige 14 números de 1 a 25.
    La lotería también saca 14 números de 1 a 25.
    C(25,14) = 4.457.400 combinaciones posibles.
    """
    print("  Calculando Kino principal...")
    base = _metricas_juego(df, "KINO", num_range=25, pick=14, comodin=False)

    print("  Generando sugerencias Kino (por rango)...")
    base["suggestions"] = _sugerencias_por_rango(df, "KINO", num_range=25, pick=14)

    print("  Calculando ReKino...")
    base["rekino"]       = _metricas_juego(df, "REKINO",       25, 14, False)

    print("  Calculando RequeteKino...")
    base["requetekino"]  = _metricas_juego(df, "REQUETEKINO",  25, 14, False)

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
        csv_path     = DATA_DIR / "polla_historial.csv"
        out_path     = DOCS_DATA / "loto_metrics.json"
        pending_path = PENDING_LOTO
        num_cols     = [f"LOTO_n{i}" for i in range(1, 7)]
        juego_key    = "loto"
    else:
        csv_path     = DATA_DIR / "loteria_historial.csv"
        out_path     = DOCS_DATA / "kino_metrics.json"
        pending_path = PENDING_KINO
        num_cols     = [f"KINO_n{i}" for i in range(1, 15)]
        juego_key    = "kino"

    if not csv_path.exists():
        print(f"ERROR: No se encontró {csv_path}")
        sys.exit(1)

    print(f"Leyendo {csv_path}...")
    df = pd.read_csv(csv_path)
    print(f"  {len(df)} sorteos cargados.")

    # 1. Evaluar sugerencias del sorteo anterior (si existen)
    pending = _cargar_pending(pending_path)
    if pending:
        print("  Evaluando sugerencias del sorteo anterior...")
        _evaluar_y_registrar(df, juego_key, num_cols, pending)

    # 2. Calcular métricas y sugerencias nuevas
    data = generar_loto(df) if args.game == "loto" else generar_kino(df)

    # 3. Añadir scores históricos de rangos al JSON
    data["range_scores"] = _range_scores(juego_key)

    # 4. Guardar pending para el próximo sorteo
    ultimo = int(pd.to_numeric(df["sorteo"], errors="coerce").max())
    _guardar_pending(pending_path, ultimo, data["suggestions"])

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"OK Guardado en {out_path}")


if __name__ == "__main__":
    main()
