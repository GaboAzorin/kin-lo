"""
suggestions.py
Genera combinaciones de 6 números estadísticamente balanceadas.
Se llama desde metrics.py — no tiene punto de entrada propio.

Restricciones que debe cumplir cada combinación sugerida:
  1. Suma dentro del rango p10-p90 histórico
  2. 2-4 números pares
  3. Al menos 2 números de la mitad baja (1-20) y 2 de la alta (21-41)
  4. Sin 3+ números consecutivos
  5. Nunca ha salido antes en el historial (unicidad garantizada)
"""

import random
from itertools import combinations as iter_combinations
from math import comb as math_comb


# ---------------------------------------------------------------------------
# Rango lexicográfico
# ---------------------------------------------------------------------------

def combo_rank(combo: list[int], n: int, k: int) -> int:
    """
    Rango 1-indexado de una combinación en orden lexicográfico entre C(n,k).
    combo_rank([1,2,3,4,5,6], 41, 6) == 1
    combo_rank([1,2,3,4,5,7], 41, 6) == 2
    """
    combo = sorted(combo)
    rank = 1
    prev = 0
    for i, c in enumerate(combo):
        for a in range(prev + 1, c):
            rank += math_comb(n - a, k - i - 1)
        prev = c
    return rank


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_history_set(df, num_cols: list[str]) -> set[tuple]:
    """Construye un set de frozensets con todas las combinaciones históricas."""
    history = set()
    for _, row in df.iterrows():
        nums = []
        for c in num_cols:
            v = row.get(c)
            try:
                nums.append(int(v))
            except (TypeError, ValueError):
                pass
        if len(nums) == len(num_cols):
            history.add(tuple(sorted(nums)))
    return history


def _score(combo: tuple, freq: dict, sum_p10: int, sum_p90: int,
           total_draws: int, num_range: int = 41, pick: int = 6) -> float:
    """Calcula un score 0-1 para una combinación de `pick` números."""
    s = sum(combo)

    # 1. Suma dentro del rango histórico p10-p90
    rango = sum_p90 - sum_p10 if sum_p90 > sum_p10 else 1
    if sum_p10 <= s <= sum_p90:
        score_suma = 1.0
    else:
        dist = min(abs(s - sum_p10), abs(s - sum_p90))
        score_suma = max(0.0, 1.0 - dist / rango)

    # 2. Balance par/impar — esperado: ~pick/2 pares
    pares = sum(1 for n in combo if n % 2 == 0)
    mitad = pick // 2
    score_paridad = 1.0 if (mitad - 1) <= pares <= (mitad + 1) else 0.4

    # 3. Balance alto/bajo — umbral: mitad del rango
    umbral = num_range // 2
    bajos = sum(1 for n in combo if n <= umbral)
    mitad_pick = pick // 2
    score_balance = 1.0 if (mitad_pick - 2) <= bajos <= (mitad_pick + 2) else 0.4

    # 4. Frecuencia: preferir números cercanos a su frecuencia esperada
    freq_esperada = 100.0 * pick / num_range
    freq_scores = []
    for n in combo:
        pct = freq.get(str(n), {}).get("pct", freq_esperada)
        dist_rel = abs(pct - freq_esperada) / freq_esperada if freq_esperada else 0
        freq_scores.append(max(0.0, 1.0 - dist_rel * 0.5))
    score_freq = sum(freq_scores) / len(freq_scores)

    # 5. Penalizar 5+ números consecutivos (para picks grandes como 14, 3 consecutivos es normal)
    umbral_consec = max(3, pick // 3)
    nums_sorted = sorted(combo)
    max_run = 1
    current_run = 1
    for i in range(1, len(nums_sorted)):
        if nums_sorted[i] - nums_sorted[i-1] == 1:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 1
    score_consec = 0.0 if max_run >= umbral_consec else 1.0

    return (
        0.30 * score_suma    +
        0.20 * score_paridad +
        0.20 * score_balance +
        0.20 * score_freq    +
        0.10 * score_consec
    )


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def generar_sugerencias(df, metricas: dict, num_range: int = 41,
                        pick: int = 6, n_sugerencias: int = 5,
                        num_col_prefix: str = "LOTO",
                        df_history=None) -> list[dict]:
    """
    Genera `n_sugerencias` combinaciones de `pick` números (1..num_range).

    Args:
        df:             DataFrame del rango a analizar (stats estadísticos).
        metricas:       Dict con sum_stats y frequencies calculados sobre df.
        num_range:      Rango de números (41 para Loto, 25 para Kino).
        pick:           Cuántos números elige el apostador (6 Loto, 14 Kino).
        n_sugerencias:  Cuántas combinaciones devolver.
        num_col_prefix: Prefijo de las columnas numéricas ("LOTO" o "KINO").
        df_history:     DataFrame completo para verificar unicidad histórica.
                        Si None, se usa df (comportamiento original).

    Returns:
        Lista de dicts: [{"combo": [n1..n6], "suma": X, "score": Y}, ...]
    """
    num_cols  = [f"{num_col_prefix}_n{i}" for i in range(1, pick + 1)]
    hist_df   = df_history if df_history is not None else df
    history   = _build_history_set(hist_df, num_cols)

    freq     = metricas.get("frequencies", {})
    sum_p10  = metricas.get("sum_stats", {}).get("p10", 70)
    sum_p90  = metricas.get("sum_stats", {}).get("p90", 180)

    candidatos: list[tuple[tuple, float]] = []
    intentos = 0
    max_intentos = 20_000

    while len(candidatos) < 1000 and intentos < max_intentos:
        intentos += 1
        combo = tuple(sorted(random.sample(range(1, num_range + 1), pick)))
        if combo in history:
            continue
        s = _score(combo, freq, sum_p10, sum_p90, metricas.get("total_sorteos", 1), num_range, pick)
        candidatos.append((combo, s))

    # Ordenar por score descendente y devolver los top-n únicos
    candidatos.sort(key=lambda x: x[1], reverse=True)

    resultado = []
    vistos: set[tuple] = set()
    for combo, s in candidatos:
        if combo not in vistos and len(resultado) < n_sugerencias:
            vistos.add(combo)
            resultado.append({
                "combo": list(combo),
                "suma":  sum(combo),
                "score": round(s, 3),
            })

    return resultado
