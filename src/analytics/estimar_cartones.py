"""
estimar_cartones.py
Estima cuántos cartones de Kino se jugaron en cada sorteo a partir del número de
ganadores por categoría (data/kino_premios_historial.csv, capturada por
scraper_premios_kino.py).

MÉTODO
------
Un cartón elige 14 números de 25; el sorteo saca 14 de 25. La probabilidad de
acertar exactamente k es hipergeométrica:

    P(k) = C(14,k)·C(11,14-k) / C(25,14)

Si se jugaron N cartones, los ganadores de la categoría k son ~ Poisson(N·P(k)).
Combinando todas las categorías observables (k = 10..13), el estimador de máxima
verosimilitud de N es el pooled estimator:

    N̂ = Σ ganadores_k / Σ P(k)        con error estándar  se = √(Σ ganadores_k) / Σ P(k)

Se excluye k=14 (P≈2e-7, casi siempre 0 ganadores: no aporta).

CAVEAT: asume que cada cartón es 14 números distintos elegidos al azar. Los
jugadores reales eligen números "favoritos" (fechas, patrones), así que el valor
absoluto tiene sesgo. Como ÍNDICE de volumen y para comparar sorteos entre sí, es
robusto: el error estadístico es < 1%.

Solo KINO tiene categorías bajas en la API; ReKino/RequeteKino no son estimables.

Uso:
    python src/analytics/estimar_cartones.py
"""

import csv
import json
from collections import defaultdict
from math import comb, sqrt
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_IN   = REPO_ROOT / "data" / "kino_premios_historial.csv"
JSON_OUT = REPO_ROOT / "docs" / "data" / "kino_cartones.json"

C_25_14 = comb(25, 14)  # 4.457.400
# Categorías usables: las que tienen P(k) no despreciable y suelen tener ganadores.
ACIERTOS_USABLES = (10, 11, 12, 13)


def prob_aciertos(k: int) -> float:
    """P(acertar exactamente k de 14, eligiendo 14 de 25)."""
    return comb(14, k) * comb(11, 14 - k) / C_25_14


P = {k: prob_aciertos(k) for k in ACIERTOS_USABLES}


def estimar(ganadores_por_aciertos: dict[int, int]) -> dict | None:
    """Pooled MLE de N a partir de {aciertos: ganadores}. None si no hay datos."""
    sum_g = sum(ganadores_por_aciertos.get(k, 0) for k in ACIERTOS_USABLES)
    sum_p = sum(P[k] for k in ACIERTOS_USABLES if k in ganadores_por_aciertos)
    if sum_p == 0 or sum_g == 0:
        return None
    n_hat = sum_g / sum_p
    se = sqrt(sum_g) / sum_p
    return {
        "cartones_estimados": round(n_hat),
        "error_estandar":     round(se),
        "error_pct":          round(100 * se / n_hat, 2),
        "ganadores_usados":   sum_g,
    }


def cargar() -> dict[int, dict]:
    """{sorteo: {'fecha':..., 'aciertos':{k:ganadores}}} solo para KINO."""
    por_sorteo: dict[int, dict] = defaultdict(lambda: {"fecha": "", "aciertos": {}})
    with open(CSV_IN, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("game_code") != "KINO":
                continue
            try:
                s = int(row["sorteo"]); k = int(row["aciertos"]); g = int(row["ganadores"])
            except (ValueError, KeyError):
                continue
            por_sorteo[s]["fecha"] = row.get("fecha", "")
            por_sorteo[s]["aciertos"][k] = g
    return por_sorteo


def main():
    if not CSV_IN.exists():
        print(f"No existe {CSV_IN}. Corre antes scraper_premios_kino.py")
        return
    datos = cargar()
    resultados = []
    for s in sorted(datos):
        est = estimar(datos[s]["aciertos"])
        if est:
            resultados.append({"sorteo": s, "fecha": datos[s]["fecha"], **est})

    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metodo": "pooled MLE hipergeometrico sobre ganadores k=10..13 (KINO)",
        "n_sorteos": len(resultados),
        "sorteos": resultados,
    }
    with open(JSON_OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # Resumen por consola
    print(f"Estimación de cartones KINO ({len(resultados)} sorteos):")
    print(f"{'sorteo':>7} {'fecha':>12} {'cartones_est':>13} {'±error':>8} {'err%':>6}")
    for r in resultados:
        print(f"{r['sorteo']:>7} {r['fecha']:>12} {r['cartones_estimados']:>13,} "
              f"{r['error_estandar']:>8,} {r['error_pct']:>5}%")
    if resultados:
        vals = [r["cartones_estimados"] for r in resultados]
        print(f"\nrango: {min(vals):,} – {max(vals):,}  | promedio: {sum(vals)//len(vals):,}")
    print(f"\nJSON escrito en {JSON_OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
