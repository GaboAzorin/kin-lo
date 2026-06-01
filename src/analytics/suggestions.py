"""
suggestions.py
Genera combinaciones sugeridas. Se llama desde metrics.py.

CONTEXTO ESTADÍSTICO (ver src/analytics/backtest.py):
En una lotería justa, todas las combinaciones son equiprobables y los sorteos
son independientes. El backtest sobre el historial confirma que NINGÚN criterio
sobre los números mejora los aciertos frente al azar (smart ≈ random ≈ esperanza
hipergeométrica). Por eso este motor NO intenta "predecir": optimiza las dos
únicas palancas con valor real:

  1. ANTI-REPARTO  — evita patrones que mucha gente juega (fechas, progresiones,
     secuencias, múltiplos, mismo dígito). Si ganas, repartes con menos gente →
     mayor premio esperado. (No cambia la probabilidad de ganar.)
  2. DIVERSIDAD    — las N combinaciones se solapan lo menos posible entre sí,
     maximizando la cobertura del espacio de números si juegas varios cartones.

Más dos restricciones de cordura:
  3. UNICIDAD      — ninguna combinación sugerida ha salido antes en el historial.
  4. FORMA TÍPICA  — suma dentro de p10-p90, paridad y balance plausibles
                     (cosmético: que se parezca a un sorteo real).

El criterio de "frecuencia esperada" del motor anterior se eliminó: el backtest
mostró que era ruido (falacia caliente/frío).

Loto (1-41, elige 6) y Kino (1-25, elige 14) usan perfiles distintos porque en
Kino eliges más de la mitad de los números: suma/paridad/balance casi no varían,
así que el peso recae en anti-reparto y diversidad.
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
    """Pesos y parámetros de selección según el juego.

    w_pop: peso del anti-reparto vs forma típica en el score de candidatos.
    lam:   peso de la diversidad vs score en la selección MMR (0-1, mayor = más diverso).
    """
    if juego == "kino":
        # Eliges 14 de 25: forma casi sin varianza → todo el peso en anti-reparto.
        return {"w_pop": 0.75, "lam": 0.70}
    # Loto y familia (1-41, elige 6).
    return {"w_pop": 0.60, "lam": 0.60}


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
                 num_range: int, pick: int) -> float:
    """
    Qué tan "típica" se ve la combinación frente al historial (0-1). Cosmético:
    no mejora aciertos, solo evita combos extremos poco realistas.
    """
    s = sum(combo)
    rango = sum_p90 - sum_p10 if sum_p90 > sum_p10 else 1
    if sum_p10 <= s <= sum_p90:
        sc_sum = 1.0
    else:
        dist = min(abs(s - sum_p10), abs(s - sum_p90))
        sc_sum = max(0.0, 1.0 - dist / rango)

    mitad = pick // 2
    pares = sum(1 for n in combo if n % 2 == 0)
    sc_par = 1.0 if abs(pares - mitad) <= 1 else 0.5

    umbral = num_range // 2
    bajos = sum(1 for n in combo if n <= umbral)
    sc_bal = 1.0 if abs(bajos - mitad) <= 2 else 0.5

    return 0.5 * sc_sum + 0.25 * sc_par + 0.25 * sc_bal


def _seleccionar_diversas(cands, n: int, pick: int, lam: float):
    """
    Selección MMR (maximal marginal relevance): de un shortlist de candidatos
    de alto score (= baja popularidad), va eligiendo en cada paso el que
    minimiza el solapamiento máximo con los ya elegidos, sin sacrificar score.

        valor = (1 - lam) * score  -  lam * (solape_max / pick)

    cands: lista [(combo_tuple, score, pop)] ordenada por score desc.
    """
    if not cands:
        return []
    shortlist = cands[:400]              # todos de score alto / popularidad baja
    elegidos = [shortlist[0]]
    elegidos_set = {shortlist[0][0]}

    while len(elegidos) < n and len(elegidos) < len(shortlist):
        mejor, mejor_val = None, float("-inf")
        for combo, sc, pop in shortlist:
            if combo in elegidos_set:
                continue
            solape_max = max(len(set(combo) & set(c)) for c, _, _ in elegidos)
            val = (1 - lam) * sc - lam * (solape_max / pick)
            if val > mejor_val:
                mejor_val, mejor = val, (combo, sc, pop)
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
                        n_display: int | None = None) -> list[dict]:
    """
    Genera `n_sugerencias` combinaciones optimizadas por anti-reparto + diversidad.

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

    Returns:
        Lista de dicts ordenada por score:
        [{"combo": [...], "suma": X, "score": Y, "popularidad": Z}, ...]
    """
    if juego is None:
        juego = "kino" if num_range <= 25 else "loto"
    perfil = _perfil(juego)
    w_pop = perfil["w_pop"]

    num_cols = [f"{num_col_prefix}_n{i}" for i in range(1, pick + 1)]
    hist_df  = df_history if df_history is not None else df
    history  = _build_history_set(hist_df, num_cols)

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
        shape = _shape_score(combo, sum_p10, sum_p90, num_range, pick)
        pop   = popularity_penalty(combo, num_range, pick)
        score = (1 - w_pop) * shape + w_pop * (1 - pop)
        candidatos.append((combo, score, pop))

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

    return [
        {
            "combo":       list(combo),
            "suma":        sum(combo),
            "score":       round(sc, 3),
            "popularidad": round(pop, 3),
        }
        for combo, sc, pop in elegidos
    ]
