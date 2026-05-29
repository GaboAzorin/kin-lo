"""
backtest.py
Mide si las sugerencias del motor estadístico (suggestions.py) superan a una
selección puramente aleatoria, comparándolas contra los resultados reales del
historial y contra la esperanza teórica (distribución hipergeométrica).

Idea clave: en una lotería justa, ningún criterio cambia la probabilidad de
ganar — todas las combinaciones son equiprobables y los sorteos son
independientes. Este script existe para *confirmarlo con datos* y detectar si
los filtros de "forma" (suma p10-p90, paridad, balance, frecuencia…) producen
algún sesgo medible —positivo o negativo— frente al azar puro.

Para cada sorteo objetivo t se usan SOLO los sorteos anteriores a t como
historial/estadísticas (walk-forward, sin fuga de información), se generan N
combinaciones con el motor ("smart") y N combinaciones aleatorias válidas
("random"), y se cuentan los aciertos contra el resultado real de t.

Comparación principal: test pareado sobre el promedio de aciertos por sorteo
(cada sorteo aporta un par smart/random), que respeta la independencia entre
sorteos. Se reportan además los pooled means y los aciertos máximos.

Uso:
    python src/analytics/backtest.py --game loto
    python src/analytics/backtest.py --game kino --draws 300 --n 10
    python src/analytics/backtest.py --game loto --rango 250 --seed 7
"""

import argparse
import json
import random
import statistics
import sys
from itertools import combinations as iter_combinations
from math import sqrt
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "analytics"))

from suggestions import generar_sugerencias, popularity_penalty  # noqa: E402

DATA_DIR  = REPO_ROOT / "data"
DOCS_DATA = REPO_ROOT / "docs" / "data"

GAME_CFG = {
    "loto": {
        "csv":       DATA_DIR / "polla_historial.csv",
        "prefix":    "LOTO",
        "pick":      6,
        "num_range": 41,
    },
    "kino": {
        "csv":       DATA_DIR / "loteria_historial.csv",
        "prefix":    "KINO",
        "pick":      14,
        "num_range": 25,
    },
}


# ---------------------------------------------------------------------------
# Stats mínimos (reimplementados aquí para no arrastrar el import de metrics.py
# y su cadena de notificaciones)
# ---------------------------------------------------------------------------

def _frecuencias(df: pd.DataFrame, cols: list[str], num_range: int) -> dict:
    total = len(df)
    nums = df[cols].apply(pd.to_numeric, errors="coerce").values.flatten()
    nums = nums[~pd.isnull(nums)].astype(int)
    out = {}
    for n in range(1, num_range + 1):
        count = int((nums == n).sum())
        out[str(n)] = {"count": count, "pct": round(count / total * 100, 2) if total else 0}
    return out


def _sum_stats(df: pd.DataFrame, cols: list[str]) -> dict:
    sumas = df[cols].apply(pd.to_numeric, errors="coerce").sum(axis=1).dropna()
    return {
        "p10": int(sumas.quantile(0.10)),
        "p90": int(sumas.quantile(0.90)),
    }


def _stats_ligeros(df: pd.DataFrame, cols: list[str], num_range: int) -> dict:
    return {
        "total_sorteos": len(df),
        "frequencies":   _frecuencias(df, cols, num_range),
        "sum_stats":     _sum_stats(df, cols),
    }


# ---------------------------------------------------------------------------
# Brazos del experimento
# ---------------------------------------------------------------------------

def _random_combos(history: set, num_range: int, pick: int, n: int,
                   rng: random.Random) -> list[tuple]:
    """N combinaciones uniformes válidas (sin repetir el historial)."""
    out = []
    while len(out) < n:
        c = tuple(sorted(rng.sample(range(1, num_range + 1), pick)))
        if c in history:
            continue
        out.append(c)
    return out


def _build_history_set(df: pd.DataFrame, cols: list[str]) -> set:
    history = set()
    for _, row in df.iterrows():
        nums = []
        for c in cols:
            try:
                nums.append(int(row[c]))
            except (TypeError, ValueError):
                pass
        if len(nums) == len(cols):
            history.add(tuple(sorted(nums)))
    return history


def _avg_pairwise_overlap(combos: list) -> float:
    """Promedio de números compartidos entre cada par de combinaciones."""
    if len(combos) < 2:
        return 0.0
    sets = [set(c) for c in combos]
    olaps = [len(a & b) for a, b in iter_combinations(sets, 2)]
    return statistics.mean(olaps)


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

def backtest(game: str, draws: int, n: int, rango, seed: int, min_hist: int = 50):
    cfg = GAME_CFG[game]
    prefix, pick, num_range = cfg["prefix"], cfg["pick"], cfg["num_range"]
    cols = [f"{prefix}_n{i}" for i in range(1, pick + 1)]

    df = pd.read_csv(cfg["csv"])
    df["_s"] = pd.to_numeric(df["sorteo"], errors="coerce")
    df = df.dropna(subset=["_s"]).sort_values("_s").reset_index(drop=True)

    # Filas con los `pick` números válidos
    mask = df[cols].apply(pd.to_numeric, errors="coerce").notna().all(axis=1)
    df = df[mask].reset_index(drop=True)

    total = len(df)
    if total < min_hist + 10:
        print(f"ERROR: muy pocos sorteos válidos ({total}).")
        return

    # Sorteos objetivo: los últimos `draws`, pero siempre con >= min_hist de historia
    start = max(min_hist, total - draws)
    targets = list(range(start, total))

    rng_rand = random.Random(seed)        # brazo aleatorio
    random.seed(seed)                     # brazo smart (usa el random global)

    esperanza = pick * pick / num_range   # E[aciertos] hipergeométrica (result=pick)

    per_draw = []   # (smart_avg_ac, rand_avg_ac, smart_max_ac, rand_max_ac)
    smart_all, rand_all = [], []
    smart_pop, rand_pop = [], []     # popularidad media por sorteo (menor = mejor)
    smart_olap, rand_olap = [], []   # solapamiento medio entre combos (menor = mejor)

    print(f"Backtest {game.upper()}  | sorteos objetivo: {len(targets)} "
          f"(de #{int(df.iloc[start]['_s'])} a #{int(df.iloc[-1]['_s'])})")
    print(f"  combos/brazo: {n}  | rango stats: {rango}  | seed: {seed}")
    print(f"  E[aciertos] teórica (azar): {esperanza:.4f}\n")

    for t in targets:
        df_hist = df.iloc[:t]
        if rango != "all":
            df_stats = df_hist.tail(int(rango))
        else:
            df_stats = df_hist

        resultado = set(int(df.iloc[t][c]) for c in cols)
        history = _build_history_set(df_hist, cols)
        stats = _stats_ligeros(df_stats, cols, num_range)

        smart = generar_sugerencias(
            df_stats, stats, num_range=num_range, pick=pick,
            n_sugerencias=n, num_col_prefix=prefix, df_history=df_hist, juego=game,
        )
        smart_combos = [s["combo"] for s in smart]
        rand_combos = _random_combos(history, num_range, pick, n, rng_rand)

        s_ac = [len(set(c) & resultado) for c in smart_combos]
        r_ac = [len(set(c) & resultado) for c in rand_combos]
        if not s_ac or not r_ac:
            continue

        smart_all.extend(s_ac)
        rand_all.extend(r_ac)
        per_draw.append((
            statistics.mean(s_ac), statistics.mean(r_ac),
            max(s_ac), max(r_ac),
        ))
        smart_pop.append(statistics.mean(popularity_penalty(c, num_range, pick) for c in smart_combos))
        rand_pop.append(statistics.mean(popularity_penalty(c, num_range, pick) for c in rand_combos))
        smart_olap.append(_avg_pairwise_overlap(smart_combos))
        rand_olap.append(_avg_pairwise_overlap(rand_combos))

    extra = {
        "smart_pop":  statistics.mean(smart_pop) if smart_pop else 0.0,
        "rand_pop":   statistics.mean(rand_pop) if rand_pop else 0.0,
        "smart_olap": statistics.mean(smart_olap) if smart_olap else 0.0,
        "rand_olap":  statistics.mean(rand_olap) if rand_olap else 0.0,
    }
    return _reporte(game, per_draw, smart_all, rand_all, esperanza, pick, extra)


def _reporte(game, per_draw, smart_all, rand_all, esperanza, pick, extra) -> dict | None:
    if not per_draw:
        print("Sin sorteos evaluables.")
        return None

    nd = len(per_draw)
    smart_pool = statistics.mean(smart_all)
    rand_pool = statistics.mean(rand_all)

    # Test pareado sobre el promedio de aciertos por sorteo (independencia entre sorteos)
    diffs = [d[0] - d[1] for d in per_draw]
    mean_d = statistics.mean(diffs)
    sd_d = statistics.pstdev(diffs) if nd > 1 else 0.0
    se_d = sd_d / sqrt(nd) if nd else 0.0
    z = mean_d / se_d if se_d else 0.0

    smart_max_avg = statistics.mean(d[2] for d in per_draw)
    rand_max_avg = statistics.mean(d[3] for d in per_draw)
    smart_best = max(d[2] for d in per_draw)
    rand_best = max(d[3] for d in per_draw)

    print("─" * 60)
    print(f"{'':<26}{'SMART':>10}{'RANDOM':>10}{'TEÓRICO':>12}")
    print(f"{'aciertos prom.':<26}{smart_pool:>10.4f}{rand_pool:>10.4f}{esperanza:>12.4f}")
    print(f"{'max prom. por sorteo':<26}{smart_max_avg:>10.4f}{rand_max_avg:>10.4f}{'—':>12}")
    print(f"{'mejor acierto único':<26}{smart_best:>10d}{rand_best:>10d}{pick:>12d}")
    print("─" * 60)
    print("Aciertos: ¿supera el motor al azar?")
    print(f"  diferencia pareada smart−random: {mean_d:+.4f}  (z ≈ {z:+.2f}, n={nd})")
    sig = "SÍ" if abs(z) >= 1.96 else "NO"
    print(f"  ¿significativa al 95%?: {sig}", end="  ")
    if abs(z) < 1.96:
        print("→ dentro del ruido (lo esperado en lotería justa).")
    elif z > 0:
        print("→ ventaja medible (por condicionar a forma típica; NO sube P[ganar]).")
    else:
        print("→ por DEBAJO del azar; revisar filtros.")

    # ── Palancas con valor real: anti-reparto y diversidad ────────────────
    pop_red = (1 - extra["smart_pop"] / extra["rand_pop"]) * 100 if extra["rand_pop"] else 0.0
    print("─" * 60)
    print("Palancas con valor real (donde el motor SÍ debe ganar):")
    print(f"{'popularidad media':<26}{extra['smart_pop']:>10.4f}{extra['rand_pop']:>10.4f}"
          f"   ({pop_red:+.0f}% vs azar)")
    print(f"{'solapamiento entre combos':<26}{extra['smart_olap']:>10.4f}{extra['rand_olap']:>10.4f}")
    print("  popularidad ↓ = repartes el premio con menos gente (mayor premio esperado)")
    print("  solapamiento ↓ = tus combos cubren más números distintos")
    print("─" * 60)

    return {
        "game":         game,
        "n_sorteos":    nd,
        "pick":         pick,
        "aciertos":     {"smart": round(smart_pool, 4), "random": round(rand_pool, 4),
                         "teorico": round(esperanza, 4)},
        "aciertos_test": {"diff": round(mean_d, 4), "z": round(z, 2),
                          "significativo": bool(abs(z) >= 1.96)},
        "popularidad":  {"smart": round(extra["smart_pop"], 4),
                         "random": round(extra["rand_pop"], 4),
                         "reduccion_pct": round(pop_red, 1)},
        "solapamiento": {"smart": round(extra["smart_olap"], 4),
                         "random": round(extra["rand_olap"], 4)},
    }


def main():
    ap = argparse.ArgumentParser(description="Backtest sugerencias vs azar")
    ap.add_argument("--game", choices=["loto", "kino"], required=True)
    ap.add_argument("--draws", type=int, default=200,
                    help="nº de sorteos recientes a evaluar (default 200)")
    ap.add_argument("--n", type=int, default=10,
                    help="combos por brazo por sorteo (default 10)")
    ap.add_argument("--rango", default="all",
                    help="ventana de stats: entero (últimos N) o 'all' (default)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--json", action="store_true",
                    help="escribe docs/data/backtest.json para el sitio")
    args = ap.parse_args()

    rango = args.rango if args.rango == "all" else int(args.rango)
    resumen = backtest(args.game, args.draws, args.n, rango, args.seed)

    if args.json and resumen:
        out_path = DOCS_DATA / "backtest.json"
        existing = {}
        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        existing[args.game] = resumen
        existing["_meta"] = {"draws": args.draws, "n": args.n,
                             "rango": str(rango), "seed": args.seed}
        out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"JSON actualizado: {out_path}")


if __name__ == "__main__":
    main()
