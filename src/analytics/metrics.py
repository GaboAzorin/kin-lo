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
sys.path.insert(0, str(REPO_ROOT / "src" / "notifications"))

from suggestions import generar_sugerencias, combo_rank
from tg_notify   import send as tg_send

DATA_DIR  = REPO_ROOT / "data"
DOCS_DATA = REPO_ROOT / "docs" / "data"
DOCS_DATA.mkdir(parents=True, exist_ok=True)

PENDING_LOTO = DATA_DIR / "loto_suggestions_pending.json"
PENDING_KINO = DATA_DIR / "kino_suggestions_pending.json"
HISTORY_PATH = DATA_DIR / "suggestions_history.csv"
HISTORY_COLS = ["juego", "sorteo_predicho", "fecha_sorteo", "rango", "combo", "aciertos"]
JUGADAS_PATH = DATA_DIR / "jugadas.json"

VARIANTE_COLS = {
    "loto": {
        "loto":      [f"LOTO_n{i}"      for i in range(1, 7)],
        "recargado": [f"RECARGADO_n{i}" for i in range(1, 7)],
        "revancha":  [f"REVANCHA_n{i}"  for i in range(1, 7)],
        "desquite":  [f"DESQUITE_n{i}"  for i in range(1, 7)],
    },
    "kino": {
        "kino":        [f"KINO_n{i}"        for i in range(1, 15)],
        "rekino":      [f"REKINO_n{i}"      for i in range(1, 15)],
        "requetekino": [f"REQUETEKINO_n{i}" for i in range(1, 15)],
    },
}
LABEL_MAP = {
    "loto": "Loto", "recargado": "Recargado", "revancha": "Revancha", "desquite": "Desquite",
    "kino": "Kino", "rekino": "ReKino", "requetekino": "RequeteKino",
}

# Notificaciones Telegram
_DIA_ES = {
    "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles",
    "Thursday": "jueves", "Friday": "viernes", "Saturday": "sábado", "Sunday": "domingo",
}
_RANGOS_ORDEN  = ["50", "100", "250", "500", "1000", "all"]
_UMBRAL_ALERTA = {"kino": 12, "loto": 5}   # aciertos mínimos para alerta destacada

# ---------------------------------------------------------------------------
# Rangos para sugerencias
# ---------------------------------------------------------------------------
SUGGESTION_RANGES = [50, 100, 250, 500, 1000]  # "all" siempre se añade al final

# Cuántas combinaciones se generan y evalúan por rango (set masivo) vs. cuántas
# se muestran al usuario / se exportan al detalle (las top por aciertos).
N_EVAL    = 500   # combos generados + evaluados por rango → mejor grupo robusto
N_DISPLAY = 3     # combos mostrados en Home y top-3 por aciertos en /sugerencias/

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
        return None

    # Primer sorteo > tras_sorteo disponible en el CSV
    df_num = df.copy()
    df_num["_s"] = pd.to_numeric(df_num["sorteo"], errors="coerce")
    siguientes = df_num[df_num["_s"] > tras_sorteo].sort_values("_s")

    if siguientes.empty:
        print(f"  Sin resultado posterior a sorteo #{tras_sorteo} todavía.")
        return None

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
        return None

    # Evitar duplicados
    if HISTORY_PATH.exists() and HISTORY_PATH.stat().st_size > 10:
        df_h = pd.read_csv(HISTORY_PATH)
        if ((df_h["juego"] == juego) &
                (pd.to_numeric(df_h["sorteo_predicho"], errors="coerce") == sorteo_n)).any():
            print(f"  Sorteo #{sorteo_n} ya estaba en el historial. Omitido.")
            return None

    resultado_set = set(resultado)
    filas_nuevas  = []
    per_rango_raw: dict[str, list] = {}   # rango → lista de {combo, aciertos}

    for rango, combos in pending.get("sugerencias", {}).items():
        per_rango_raw[rango] = []
        for s in combos:
            combo    = s["combo"]          # list[int]
            aciertos = len(set(combo) & resultado_set)
            filas_nuevas.append({
                "juego":           juego,
                "sorteo_predicho": sorteo_n,
                "fecha_sorteo":    fecha,
                "rango":           rango,
                "combo":           ",".join(str(n) for n in combo),
                "aciertos":        aciertos,
            })
            per_rango_raw[rango].append({"combo": combo, "aciertos": aciertos})

    if not filas_nuevas:
        return None

    file_exists = HISTORY_PATH.exists() and HISTORY_PATH.stat().st_size > 10
    with open(HISTORY_PATH, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(filas_nuevas)

    print(f"  Evaluado sorteo #{sorteo_n} ({fecha}) | resultado: {sorted(resultado_set)}")
    per_rango: dict[str, dict] = {}
    for rango, cs in per_rango_raw.items():
        max_a = max(c["aciertos"] for c in cs)
        avg_a = round(sum(c["aciertos"] for c in cs) / len(cs), 2)
        print(f"    [{rango:>4}] max={max_a}  avg={avg_a:.2f}")
        per_rango[rango] = {"max": max_a, "avg": avg_a, "combos": cs}

    return {
        "sorteo_n":  sorteo_n,
        "fecha":     fecha,
        "resultado": sorted(resultado_set),
        "per_rango": per_rango,
        "pick":      len(num_cols),
    }


def _evaluar_jugadas(df: pd.DataFrame, juego: str, num_cols: list[str]) -> list[dict]:
    """
    Lee data/jugadas.json, calcula aciertos por variante para jugadas pendientes del juego dado
    que ya tienen resultado en el CSV. Actualiza el archivo en disco.
    Retorna la lista de jugadas recién evaluadas.
    """
    if not JUGADAS_PATH.exists():
        return []

    with open(JUGADAS_PATH, encoding="utf-8") as f:
        jugadas = json.load(f)

    df_num = df.copy()
    df_num["_s"] = pd.to_numeric(df_num["sorteo"], errors="coerce")
    sorteos_disponibles = set(df_num["_s"].dropna().astype(int))

    vcols = VARIANTE_COLS[juego]
    evaluadas = []
    modificado = False

    for j in jugadas:
        if j.get("juego") != juego:
            continue
        # Saltar solo si ya está evaluado en el nuevo formato (dict).
        # Entradas con aciertos numérico (formato viejo) se re-evalúan.
        if isinstance(j.get("aciertos"), dict):
            continue
        sorteo_n = j.get("sorteo")
        if sorteo_n not in sorteos_disponibles:
            continue

        fila = df_num[df_num["_s"] == sorteo_n].iloc[0]
        variantes_jugadas = j.get("variantes") or [juego]

        aciertos_dict   = {}
        resultado_dict  = {}
        for variante in variantes_jugadas:
            cols = vcols.get(variante)
            if not cols:
                continue
            resultado = []
            for c in cols:
                try:
                    resultado.append(int(fila[c]))
                except (TypeError, ValueError, KeyError):
                    pass
            if resultado:
                aciertos_dict[variante]  = len(set(j["numeros"]) & set(resultado))
                resultado_dict[variante] = sorted(resultado)

        if not aciertos_dict:
            continue

        j["aciertos"]        = aciertos_dict
        j["resultado_sorteo"] = resultado_dict
        modificado = True
        evaluadas.append(dict(j))

        rango  = j.get("rango_sugerencia") or "manual"
        nums_j = "  ".join(str(n).rjust(2) for n in j["numeros"])
        pick   = len(num_cols)
        print(f"  [Mi jugada] Sorteo #{sorteo_n}  rango={rango}")
        print(f"    Jugué:     [ {nums_j} ]")
        for v, res in resultado_dict.items():
            nums_r = "  ".join(str(n).rjust(2) for n in res)
            print(f"    {LABEL_MAP.get(v, v)}: [ {nums_r} ] = {aciertos_dict[v]} de {pick}")

    if modificado:
        with open(JUGADAS_PATH, "w", encoding="utf-8") as f:
            json.dump(jugadas, f, ensure_ascii=False, indent=2)

    return evaluadas


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
    Genera N_EVAL (500) sugerencias por cada rango válido (últimos N sorteos + todos).

    - Estadísticas calculadas sobre el slice del rango.
    - Unicidad verificada contra df_full (historial completo).
    - Las primeras N_DISPLAY van por diversidad MMR (lo que se muestra); el resto
      por score, para evaluar el "mejor grupo" sobre una muestra grande.

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
            n_sugerencias=N_EVAL, num_col_prefix=prefix,
            df_history=df_full, n_display=N_DISPLAY,
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

def _exportar_historial_json():
    """
    Lee suggestions_history.csv y genera docs/data/suggestions_history.json
    con estructura procesada lista para el frontend.
    """
    out_path = DOCS_DATA / "suggestions_history.json"

    estructura_vacia = {j: {"por_rango": {}, "historial": []} for j in ["loto", "kino"]}

    if not HISTORY_PATH.exists() or HISTORY_PATH.stat().st_size < 10:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(estructura_vacia, f, ensure_ascii=False, indent=2)
        return

    df_h   = pd.read_csv(HISTORY_PATH)
    result = {}

    for juego in ["loto", "kino"]:
        pick = 14 if juego == "kino" else 6
        dj   = df_h[df_h["juego"] == juego].copy()

        # Resumen acumulado por rango
        por_rango: dict = {}
        for r in _RANGOS_ORDEN:
            dr = dj[dj["rango"] == r]
            if dr.empty:
                continue
            por_rango[r] = {
                "sorteos": int(dr["sorteo_predicho"].nunique()),
                "avg":     round(float(dr["aciertos"].mean()), 2),
                "max":     int(dr["aciertos"].max()),
                "pick":    pick,
            }

        # Historial por sorteo (para el gráfico de evolución)
        historial: list = []
        for sorteo_n, gs in dj.groupby("sorteo_predicho"):
            fecha  = str(gs["fecha_sorteo"].iloc[0])
            rangos = {}
            for r in _RANGOS_ORDEN:
                gr = gs[gs["rango"] == r]
                if gr.empty:
                    continue
                rangos[r] = {
                    "max": int(gr["aciertos"].max()),
                    "avg": round(float(gr["aciertos"].mean()), 2),
                }
            historial.append({"sorteo": int(sorteo_n), "fecha": fecha, "rangos": rangos})

        historial.sort(key=lambda x: x["sorteo"])
        result[juego] = {"por_rango": por_rango, "historial": historial, "pick": pick}

    # Rellenar juegos sin datos
    for j in ["loto", "kino"]:
        result.setdefault(j, estructura_vacia[j])

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  Historial exportado: {out_path.name}")


def _exportar_detalle_json():
    """
    Genera docs/data/suggestions_detail.json con datos por combinación incluyendo
    el rango lexicográfico de cada sugerencia y del resultado real.
    """
    out_path = DOCS_DATA / "suggestions_detail.json"

    juego_config = {
        "loto": {
            "csv":      DATA_DIR / "polla_historial.csv",
            "num_cols": [f"LOTO_n{i}" for i in range(1, 7)],
            "n": 41, "k": 6, "total_combos": 4_496_388,
        },
        "kino": {
            "csv":      DATA_DIR / "loteria_historial.csv",
            "num_cols": [f"KINO_n{i}" for i in range(1, 15)],
            "n": 25, "k": 14, "total_combos": 4_457_400,
        },
    }

    empty = {j: {"sorteos": [], "n": cfg["n"], "k": cfg["k"],
                 "total_combos": cfg["total_combos"]}
             for j, cfg in juego_config.items()}

    if not HISTORY_PATH.exists() or HISTORY_PATH.stat().st_size < 10:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(empty, f, ensure_ascii=False, indent=2)
        return

    df_h = pd.read_csv(HISTORY_PATH)
    result = {}

    for juego, cfg in juego_config.items():
        n, k     = cfg["n"], cfg["k"]
        num_cols = cfg["num_cols"]
        dj       = df_h[df_h["juego"] == juego].copy()

        df_loto = None
        if cfg["csv"].exists():
            df_loto = pd.read_csv(cfg["csv"])
            df_loto["_s"] = pd.to_numeric(df_loto["sorteo"], errors="coerce")

        sorteos = []
        for sorteo_n, grp in dj.groupby("sorteo_predicho"):
            sorteo_n = int(sorteo_n)
            fecha    = str(grp["fecha_sorteo"].iloc[0])

            resultado    = None
            rank_res     = None
            if df_loto is not None:
                fila = df_loto[df_loto["_s"] == sorteo_n]
                if not fila.empty:
                    nums = []
                    for c in num_cols:
                        try:
                            nums.append(int(fila.iloc[0][c]))
                        except (TypeError, ValueError):
                            pass
                    if len(nums) == k:
                        resultado = sorted(nums)
                        rank_res  = combo_rank(resultado, n, k)

            # Agrupar las N_EVAL combos por rango y quedarnos con las top-N por
            # aciertos (las que más acertaron en este sorteo). El rango léxico
            # se calcula solo para esas, no para las 500.
            por_rango_rows: dict[str, list] = {}
            for _, row in grp.iterrows():
                try:
                    combo = [int(x) for x in str(row["combo"]).split(",")]
                except Exception:
                    continue
                if len(combo) != k:
                    continue
                por_rango_rows.setdefault(str(row["rango"]), []).append(
                    (sorted(combo), int(row["aciertos"]))
                )

            rangos: dict[str, list] = {}
            for r, combos in por_rango_rows.items():
                combos.sort(key=lambda x: x[1], reverse=True)
                for combo_s, aciertos in combos[:N_DISPLAY]:
                    rank_c = combo_rank(combo_s, n, k)
                    diff   = (rank_res - rank_c) if rank_res is not None else None
                    rangos.setdefault(r, []).append({
                        "combo":      combo_s,
                        "aciertos":   aciertos,
                        "rank_combo": rank_c,
                        "diff_rank":  diff,
                    })

            sorteos.append({
                "sorteo":         sorteo_n,
                "fecha":          fecha,
                "resultado":      resultado,
                "rank_resultado": rank_res,
                "rangos":         {r: rangos[r] for r in _RANGOS_ORDEN if r in rangos},
            })

        sorteos.sort(key=lambda x: x["sorteo"], reverse=True)
        result[juego] = {
            "sorteos":      sorteos,
            "n":            n,
            "k":            k,
            "total_combos": cfg["total_combos"],
        }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  Detalle exportado: {out_path.name}")


def _exportar_historial_index():
    """Genera docs/data/historial_index.json con {juego: {sorteo: {variante: [nums]}}} para todos los sorteos."""
    out_path = DOCS_DATA / "historial_index.json"
    result = {}

    csv_paths = {
        "loto": DATA_DIR / "polla_historial.csv",
        "kino": DATA_DIR / "loteria_historial.csv",
    }
    for juego, csv_path in csv_paths.items():
        if not csv_path.exists():
            continue
        df = pd.read_csv(csv_path)
        vcols = VARIANTE_COLS[juego]
        idx = {}
        for _, row in df.iterrows():
            try:
                sorteo = int(row["sorteo"])
            except Exception:
                continue
            entry = {}
            for variante, cols in vcols.items():
                try:
                    nums = sorted(int(row[c]) for c in cols if pd.notna(row.get(c)))
                    if nums:
                        entry[variante] = nums
                except Exception:
                    pass
            if entry:
                # Fecha del sorteo normalizada a yyyy-mm-dd (loto trae timestamp, kino solo fecha).
                fecha = str(row.get("fecha", "")).strip()[:10]
                if fecha:
                    entry["_fecha"] = fecha
                idx[str(sorteo)] = entry
        result[juego] = idx

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  Índice histórico exportado: {out_path.name} ({sum(len(v) for v in result.values())} sorteos)")


def _enviar_notificaciones(juego: str, ultimo: dict,
                           eval_data: dict | None, range_scores: dict):
    """
    Envía hasta 3 mensajes a Telegram:
      1. Resultado del sorteo recién scrapeado.
      2. Tabla de rendimiento de sugerencias por rango.
      3. Alerta si alguna combinación alcanzó el umbral de aciertos destacados.
    Solo envía si hubo una evaluación nueva (eval_data no es None).
    """
    if eval_data is None:
        return

    pick      = eval_data["pick"]
    emoji     = "🟦" if juego == "kino" else "🟡"
    cap       = juego.capitalize()
    sorteo_n  = eval_data["sorteo_n"]
    resultado = eval_data["resultado"]
    fecha     = eval_data["fecha"]

    # ── 1. Nuevo sorteo ──────────────────────────────────────────────────
    dia     = _DIA_ES.get(ultimo.get("dia", ""), ultimo.get("dia", ""))
    nums_s  = "  ".join(str(n).rjust(2) for n in resultado)
    tg_send(
        f"{emoji} <b>{cap} · Sorteo #{sorteo_n}</b>\n"
        f"📅 {dia} {fecha}\n\n"
        f"🔢 <code>{nums_s}</code>"
    )

    # ── 2. Tabla de rendimiento ───────────────────────────────────────────
    if range_scores:
        hdr  = f"{'Rango':>5}  {'Avg aciertos':<14}  {'Max':>3}"
        sep  = "─" * 30
        rows = []
        for r in _RANGOS_ORDEN:
            if r not in range_scores:
                continue
            v     = range_scores[r]
            label = r.rjust(5) if r != "all" else "Todos"
            avg_s = f"{v['aciertos_avg']:.2f} / {pick}"
            rows.append(f"{label}  {avg_s:<14}  {v['aciertos_max']:>3}")

        if rows:
            n_eval = range_scores.get("all", {}).get("sorteos_evaluados", 1)
            pie    = f"\n({n_eval} sorteo{'s' if n_eval != 1 else ''} evaluado{'s' if n_eval != 1 else ''})"
            tabla  = "\n".join([hdr, sep] + rows)
            tg_send(
                f"📊 <b>Rendimiento de sugerencias · {cap}</b>\n"
                f"Evaluadas vs sorteo #{sorteo_n}\n\n"
                f"<pre>{tabla}{pie}</pre>"
            )

    # ── 3. Alertas de resultados destacados ──────────────────────────────
    umbral = _UMBRAL_ALERTA[juego]
    for rango, v in eval_data["per_rango"].items():
        # Con N_EVAL combos por rango, alertar solo la mejor (evita inundar Telegram).
        c = max(v["combos"], key=lambda x: x["aciertos"])
        if c["aciertos"] >= umbral:
            label  = f"Últ. {rango}" if rango != "all" else "Todos"
            nums_c = "  ".join(str(n).rjust(2) for n in c["combo"])
            sufijo = " 🎉🎉🎉" if c["aciertos"] == pick else ""
            tg_send(
                f"🚨 <b>RESULTADO DESTACADO · {cap}</b>\n\n"
                f"Rango <b>{label}</b>\n"
                f"<code>{nums_c}</code>\n"
                f"✅ <b>{c['aciertos']} de {pick} aciertos</b>{sufijo}"
            )


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
    eval_data = None
    pending   = _cargar_pending(pending_path)
    if pending:
        print("  Evaluando sugerencias del sorteo anterior...")
        eval_data = _evaluar_y_registrar(df, juego_key, num_cols, pending)

    # 1b. Evaluar jugadas personales pendientes
    print("  Evaluando jugadas personales...")
    jugadas_evaluadas = _evaluar_jugadas(df, juego_key, num_cols)
    for j in jugadas_evaluadas:
        pick   = len(num_cols)
        emoji  = "🟦" if juego_key == "kino" else "🟡"
        rango  = j.get("rango_sugerencia") or "manual"
        nums_j = "  ".join(str(n).rjust(2) for n in j["numeros"])
        ac     = j.get("aciertos", {})
        if isinstance(ac, dict):
            ac_lines = "\n".join(
                f"  {LABEL_MAP.get(v, v)}: <b>{a} de {pick}</b>"
                for v, a in ac.items()
            )
        else:
            ac_lines = f"  <b>{ac} de {pick}</b>"
        tg_send(
            f"{emoji} <b>Mi jugada · {juego_key.capitalize()} #{j['sorteo']}</b>\n"
            f"Rango: {rango}\n\n"
            f"Jugué:   <code>{nums_j}</code>\n"
            f"Aciertos:\n{ac_lines}"
        )

    # 2. Calcular métricas y sugerencias nuevas
    data = generar_loto(df) if args.game == "loto" else generar_kino(df)

    # 3. Añadir scores históricos de rangos al JSON
    data["range_scores"] = _range_scores(juego_key)

    # 4. Enviar notificaciones Telegram
    _enviar_notificaciones(juego_key, data.get("ultimo_sorteo", {}),
                           eval_data, data["range_scores"])

    # 5. Guardar pending para el próximo sorteo (las N_EVAL completas: se evalúan
    #    todas para calcular el rendimiento del "mejor grupo").
    ultimo = int(pd.to_numeric(df["sorteo"], errors="coerce").max())
    _guardar_pending(pending_path, ultimo, data["suggestions"])

    # 6. Exportar historial al frontend
    _exportar_historial_json()
    _exportar_detalle_json()
    _exportar_historial_index()

    # 7. Reducir las sugerencias del JSON de métricas a las N_DISPLAY mostradas
    #    en la Home / páginas de juego (el pending ya conserva las N_EVAL).
    data["suggestions"] = {
        rango: combos[:N_DISPLAY] for rango, combos in data["suggestions"].items()
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"OK Guardado en {out_path}")


if __name__ == "__main__":
    main()
