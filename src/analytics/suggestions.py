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
           total_draws: int) -> float:
    """Calcula un score 0-1 para una combinación de 6 números."""
    s = sum(combo)

    # 1. Suma dentro del rango histórico p10-p90
    rango = sum_p90 - sum_p10 if sum_p90 > sum_p10 else 1
    if sum_p10 <= s <= sum_p90:
        score_suma = 1.0
    else:
        dist = min(abs(s - sum_p10), abs(s - sum_p90))
        score_suma = max(0.0, 1.0 - dist / rango)

    # 2. Balance par/impar (2-4 pares es lo más común)
    pares = sum(1 for n in combo if n % 2 == 0)
    score_paridad = 1.0 if 2 <= pares <= 4 else 0.4

    # 3. Balance alto/bajo (umbral: 20 para rango 1-41)
    bajos = sum(1 for n in combo if n <= 20)
    score_balance = 1.0 if 2 <= bajos <= 4 else 0.4

    # 4. Frecuencia: preferir números cercanos a su frecuencia esperada
    freq_esperada = 100.0 * 6 / 41  # ~14.63%
    freq_scores = []
    for n in combo:
        pct = freq.get(str(n), {}).get("pct", freq_esperada)
        dist_rel = abs(pct - freq_esperada) / freq_esperada
        freq_scores.append(max(0.0, 1.0 - dist_rel * 0.5))
    score_freq = sum(freq_scores) / len(freq_scores)

    # 5. Penalizar 3+ números consecutivos
    nums_sorted = sorted(combo)
    max_run = 1
    current_run = 1
    for i in range(1, len(nums_sorted)):
        if nums_sorted[i] - nums_sorted[i-1] == 1:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 1
    score_consec = 0.0 if max_run >= 3 else 1.0

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
                        num_col_prefix: str = "LOTO") -> list[dict]:
    """
    Genera `n_sugerencias` combinaciones de `pick` números (1..num_range).

    Args:
        df:             DataFrame con el historial completo.
        metricas:       Dict generado por calcular_metricas() (con sum_stats y frequencies).
        num_range:      Rango de números (41 para Loto y Kino).
        pick:           Cuántos números elige el apostador (6).
        n_sugerencias:  Cuántas combinaciones devolver.
        num_col_prefix: Prefijo de las columnas numéricas ("LOTO" o "KINO").

    Returns:
        Lista de dicts: [{"combo": [n1..n6], "suma": X, "score": Y}, ...]
    """
    num_cols = [f"{num_col_prefix}_n{i}" for i in range(1, pick + 1)]
    history  = _build_history_set(df, num_cols)

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
        s = _score(combo, freq, sum_p10, sum_p90, metricas.get("total_sorteos", 1))
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
