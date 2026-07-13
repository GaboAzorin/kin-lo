"""
suggestions.py
Genera combinaciones sugeridas. Se llama desde metrics.py.

Este motor genera combinaciones optimizando dos palancas:

  1. DIVERSIDAD    — las N combinaciones se solapan lo menos posible entre sí,
     maximizando la cobertura del espacio de números si juegas varios cartones.
  2. FORMA TÍPICA  — suma dentro de p10-p90, paridad y balance plausibles
                     (que se parezca a un sorteo real).

Más una restricción de cordura:
  3. UNICIDAD      — ninguna combinación sugerida ha salido antes en el historial
                     (opcionalmente, tampoco en los subjuegos: ver extra_history).

El anti-reparto (penalizar patrones populares) se eliminó a pedido: es preferible
ganar y repartir que no ganar. La función `popularity_penalty` se conserva solo
como métrica descriptiva del backtest; ya no interviene en la generación.
"""

import random
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
# Perfiles por juego
# ---------------------------------------------------------------------------

def _perfil(juego: str) -> dict:
    """Parámetros de selección según el juego.

    lam: peso de la diversidad vs score en la selección MMR (0-1, mayor = más diverso).
    """
    if juego == "kino":
        return {"lam": 0.70}
    # Loto y familia (1-41, elige 6).
    return {"lam": 0.60}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_history_set(df, num_cols: list[str]) -> set[tuple]:
    """Construye un set con todas las combinaciones históricas (tuplas ordenadas)."""
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


def _max_run(nums_sorted: list[int]) -> int:
    """Longitud de la racha consecutiva más larga."""
    max_run = current = 1
    for i in range(1, len(nums_sorted)):
        if nums_sorted[i] - nums_sorted[i - 1] == 1:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 1
    return max_run


def _gap_std(nums_sorted: list[int]) -> float:
    """Desviación estándar de los gaps entre números consecutivos."""
    if len(nums_sorted) < 2:
        return 0.0
    gaps = [nums_sorted[i + 1] - nums_sorted[i] for i in range(len(nums_sorted) - 1)]
    mean = sum(gaps) / len(gaps)
    return (sum((g - mean) ** 2 for g in gaps) / len(gaps)) ** 0.5


def _zone_counts(nums_sorted: list[int], zones: list) -> list[int]:
    """Cuenta cuántos números caen en cada zona definida por (lo, hi)."""
    return [sum(1 for n in nums_sorted if lo <= n <= hi) for lo, hi in zones]


def popularity_penalty(combo, num_range: int, pick: int) -> float:
    """
    Estima qué tan "popular" es una combinación entre apostadores humanos (0-1).
    Mayor = la elige mucha gente = más reparto del premio = peor.

    Heurísticas documentadas en estudios de loterías (Cook & Clotfelter, etc.):
    sesgo de fechas, progresiones, secuencias, múltiplos y patrones visuales.
    """
    combo = sorted(combo)
    pen = 0.0

    # 1. Sesgo de cumpleaños: mucha gente juega fechas (1-31). Solo aplica si el
    #    rango supera 31 (Loto 1-41). Premia incluir números altos (32-41).
    if num_range > 31:
        low_frac = sum(1 for n in combo if n <= 31) / pick
        pen += 0.30 * max(0.0, (low_frac - 0.5) / 0.5)

    # 2. Progresión aritmética (saltos constantes): patrón muy elegido.
    gaps = [combo[i + 1] - combo[i] for i in range(len(combo) - 1)]
    if len(set(gaps)) == 1:
        pen += 0.40

    # 3. Racha consecutiva larga (1-2-3-4-5-6).
    run = _max_run(combo)
    if run >= max(4, pick // 2):
        pen += 0.30
    elif run >= 3:
        pen += 0.10

    # 4. Dispersión baja: todo apretado en un bloque del tablero.
    span = combo[-1] - combo[0]
    if span <= (num_range - 1) * 0.4:
        pen += 0.15

    # 5. Todos múltiplos de un k pequeño (patrón visual en el cartón).
    for k in (5, 7, 3):
        if all(n % k == 0 for n in combo):
            pen += 0.25
            break

    # 6. Todos terminan en el mismo dígito.
    if len(set(n % 10 for n in combo)) == 1:
        pen += 0.20

    return min(1.0, pen)


def _shape_score(combo, sum_p10: int, sum_p90: int,
                 num_range: int, pick: int,
                 dist_params: dict | None = None) -> float:
    """
    Qué tan "típica" se ve la combinación frente al historial (0-1). Cosmético:
    no mejora aciertos, solo evita combos extremos poco realistas.

    Si dist_params no es None, incluye penalización por gap_std y distribución
    de zonas fuera del rango histórico (p10-p90).
    """
    combo_sorted = sorted(combo)
    s = sum(combo_sorted)
    rango = sum_p90 - sum_p10 if sum_p90 > sum_p10 else 1
    if sum_p10 <= s <= sum_p90:
        sc_sum = 1.0
    else:
        dist = min(abs(s - sum_p10), abs(s - sum_p90))
        sc_sum = max(0.0, 1.0 - dist / rango)

    mitad = pick // 2
    pares = sum(1 for n in combo_sorted if n % 2 == 0)
    sc_par = 1.0 if abs(pares - mitad) <= 1 else 0.5

    umbral = num_range // 2
    bajos = sum(1 for n in combo_sorted if n <= umbral)
    sc_bal = 1.0 if abs(bajos - mitad) <= 2 else 0.5

    if dist_params is None:
        return 0.5 * sc_sum + 0.25 * sc_par + 0.25 * sc_bal

    # Extendido: penalizar gap_std y distribución de zonas fuera del rango histórico
    gs = _gap_std(combo_sorted)
    gp10 = dist_params.get("gap_std_p10", 0.0)
    gp90 = dist_params.get("gap_std_p90", float("inf"))
    sc_gap = 1.0 if gp10 <= gs <= gp90 else max(0.0, 1.0 - min(abs(gs - gp10), abs(gs - gp90)))

    zones = dist_params.get("zones", [])
    zp10  = dist_params.get("zone_p10", 0)
    zp90  = dist_params.get("zone_p90", pick)
    if zones:
        counts = _zone_counts(combo_sorted, zones)
        sc_zones = sum(1 for c in counts if zp10 <= c <= zp90) / len(zones)
    else:
        sc_zones = 1.0

    return 0.35 * sc_sum + 0.15 * sc_par + 0.15 * sc_bal + 0.20 * sc_gap + 0.15 * sc_zones


def _seleccionar_diversas(cands, n: int, pick: int, lam: float):
    """
    Selección MMR (maximal marginal relevance): de un shortlist de candidatos
    de alto score (= forma más típica), va eligiendo en cada paso el que
    minimiza el solapamiento máximo con los ya elegidos, sin sacrificar score.

        valor = (1 - lam) * score  -  lam * (solape_max / pick)

    cands: lista [(combo_tuple, score)] ordenada por score desc.
    """
    if not cands:
        return []
    shortlist = cands[:max(400, n * 2)]  # score alto; dimensionado según lo pedido
    elegidos = [shortlist[0]]
    elegidos_set = {shortlist[0][0]}

    while len(elegidos) < n and len(elegidos) < len(shortlist):
        mejor, mejor_val = None, float("-inf")
        for combo, sc in shortlist:
            if combo in elegidos_set:
                continue
            solape_max = max(len(set(combo) & set(c)) for c, _ in elegidos)
            val = (1 - lam) * sc - lam * (solape_max / pick)
            if val > mejor_val:
                mejor_val, mejor = val, (combo, sc)
        if mejor is None:
            break
        elegidos.append(mejor)
        elegidos_set.add(mejor[0])
    return elegidos


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def generar_sugerencias(df, metricas: dict, num_range: int = 41,
                        pick: int = 6, n_sugerencias: int = 5,
                        num_col_prefix: str = "LOTO",
                        df_history=None, juego: str | None = None,
                        n_display: int | None = None,
                        dist_params: dict | None = None,
                        extra_history: set | None = None) -> list[dict]:
    """
    Genera `n_sugerencias` combinaciones optimizadas por diversidad + forma típica.

    Args:
        df:             DataFrame del rango a analizar (para stats de forma).
        metricas:       Dict con sum_stats (p10/p90) calculados sobre df.
        num_range:      Rango de números (41 Loto, 25 Kino).
        pick:           Cuántos números elige el apostador (6 Loto, 14 Kino).
        n_sugerencias:  Cuántas combinaciones devolver.
        num_col_prefix: Prefijo de columnas ("LOTO", "KINO", ...).
        df_history:     DataFrame completo para verificar unicidad. Si None, usa df.
        juego:          "loto" | "kino". Si None se infiere del num_range.
        n_display:      Si se indica (< n_sugerencias), las primeras `n_display`
                        combinaciones se eligen por diversidad MMR (lo que se
                        muestra al usuario) y el resto hasta `n_sugerencias` se
                        rellena por score descendente (set de evaluación masivo).
                        Si es None, TODAS se eligen por MMR (comportamiento
                        clásico, usado por el backtest).
        dist_params:    Parámetros de distribución histórica para Kino:
                        {"gap_std_p10", "gap_std_p90", "zone_p10", "zone_p90", "zones"}.
                        Si None, no se aplica penalización por distribución.
        extra_history:  Set de combinaciones (tuplas ordenadas) adicionales a
                        excluir por unicidad, más allá de las de `df_history`.
                        Lo usa el grupo "Todos + subjuegos" para excluir también
                        lo que salió en los subjuegos (Recargado/Revancha/… o
                        ReKino/RequeteKino).

    Returns:
        Lista de dicts ordenada por score:
        [{"combo": [...], "suma": X, "score": Y,
          "mean_gap": F, "gap_std": F, "zones": [...], "parity": [pares, impares]}, ...]
    """
    if juego is None:
        juego = "kino" if num_range <= 25 else "loto"
    perfil = _perfil(juego)

    num_cols = [f"{num_col_prefix}_n{i}" for i in range(1, pick + 1)]
    hist_df  = df_history if df_history is not None else df
    history  = _build_history_set(hist_df, num_cols)
    if extra_history:
        history = history | extra_history

    sum_p10 = metricas.get("sum_stats", {}).get("p10", 70)
    sum_p90 = metricas.get("sum_stats", {}).get("p90", 180)

    # Pool de candidatos aleatorios únicos (no históricos).
    candidatos: list[tuple] = []
    intentos = 0
    max_intentos = 40_000
    objetivo = 3000
    while len(candidatos) < objetivo and intentos < max_intentos:
        intentos += 1
        combo = tuple(sorted(random.sample(range(1, num_range + 1), pick)))
        if combo in history:
            continue
        score = _shape_score(combo, sum_p10, sum_p90, num_range, pick, dist_params)
        candidatos.append((combo, score))

    candidatos.sort(key=lambda x: x[1], reverse=True)

    if n_display is None or n_display >= n_sugerencias:
        # Comportamiento clásico: todas por diversidad MMR.
        elegidos = _seleccionar_diversas(
            candidatos, n_sugerencias, pick, perfil["lam"]
        )
    else:
        # Las primeras n_display por diversidad (lo que se muestra); el resto
        # hasta n_sugerencias se rellena por score (set de evaluación masivo).
        elegidos = _seleccionar_diversas(
            candidatos, n_display, pick, perfil["lam"]
        )
        ya = {c[0] for c in elegidos}
        for cand in candidatos:
            if len(elegidos) >= n_sugerencias:
                break
            if cand[0] in ya:
                continue
            elegidos.append(cand)
            ya.add(cand[0])

    result = []
    for combo, sc in elegidos:
        combo_sorted = sorted(combo)
        n = len(combo_sorted)
        mg = round((combo_sorted[-1] - combo_sorted[0]) / (n - 1), 2) if n > 1 else 0.0
        gs = round(_gap_std(combo_sorted), 2)
        pares   = sum(1 for x in combo_sorted if x % 2 == 0)
        impares = n - pares
        if dist_params and dist_params.get("zones"):
            zc = _zone_counts(combo_sorted, dist_params["zones"])
        else:
            zc = []
        result.append({
            "combo":       combo_sorted,
            "suma":        sum(combo_sorted),
            "score":       round(sc, 3),
            "mean_gap":    mg,
            "gap_std":     gs,
            "zones":       zc,
            "parity":      [pares, impares],
        })
    return result
