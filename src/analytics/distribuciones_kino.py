"""
distribuciones_kino.py
Precalcula dos distribuciones para la página Kino → docs/data/kino_distribuciones.json

1. SUMA: distribución de la suma de los 14 números sorteados (histograma + media/σ).
   Es aprox. normal (CLT); sirve para mostrar la "forma" típica de un sorteo.
   Se calcula desde data/loteria_historial.csv (KINO).

2. ACIERTOS: distribución hipergeométrica de cuántos números acierta un cartón
   cualquiera (P(k) exacta, k=0..14). NO depende de los números elegidos: es idéntica
   para todo cartón. Se marca k>=10 como "paga". Matemática pura, no usa el CSV.

Uso:
    python src/analytics/distribuciones_kino.py
"""

import csv
import json
from collections import Counter
from math import comb
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_IN   = REPO_ROOT / "data" / "loteria_historial.csv"
JSON_OUT = REPO_ROOT / "docs" / "data" / "kino_distribuciones.json"

NUMS = 14          # números por sorteo
POOL = 25          # rango 1..25
ACIERTOS_PAGA = 10  # desde 10 aciertos hay premio


def _serie_kino() -> list[tuple[int, str, int]]:
    """Lista cronológica de (sorteo, fecha, suma) de cada Kino con los 14 números."""
    filas = []
    with open(CSV_IN, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            nums = []
            ok = True
            for i in range(1, NUMS + 1):
                v = (row.get(f"KINO_n{i}") or "").strip()
                if not v:
                    ok = False
                    break
                nums.append(int(float(v)))
            if ok and len(nums) == NUMS:
                try:
                    sorteo = int(float((row.get("sorteo") or "0").strip()))
                except ValueError:
                    sorteo = 0
                fecha = (row.get("fecha") or "").strip()
                filas.append((sorteo, fecha, sum(nums)))
    filas.sort(key=lambda r: r[0])  # cronológico por nº de sorteo
    return filas


def dist_suma() -> dict:
    serie = _serie_kino()
    sumas = [r[2] for r in serie]
    n = len(sumas)
    media = sum(sumas) / n
    var = sum((s - media) ** 2 for s in sumas) / n
    desv = var ** 0.5
    cnt = Counter(sumas)
    smin, smax = min(sumas), max(sumas)
    # Histograma denso (cada valor entero de suma observado en el rango)
    histograma = [{"suma": s, "count": cnt.get(s, 0)} for s in range(smin, smax + 1)]
    return {
        "n": n,
        "media": round(media, 2),
        "desv": round(desv, 2),
        "min": smin,
        "max": smax,
        "rango_teorico": [sum(range(1, NUMS + 1)), sum(range(POOL - NUMS + 1, POOL + 1))],
        "histograma": histograma,
        # Serie cronológica para la barra temporal de la campana (frontend).
        "serie": {
            "sorteo": [r[0] for r in serie],
            "fecha": [r[1] for r in serie],
            "suma": [r[2] for r in serie],
        },
    }


def dist_aciertos() -> dict:
    """P(acertar exactamente k) = C(14,k)·C(11,14-k)/C(25,14)."""
    total = comb(POOL, NUMS)
    dist = []
    media = 0.0
    for k in range(0, NUMS + 1):
        p = comb(NUMS, k) * comb(POOL - NUMS, NUMS - k) / total
        media += k * p
        dist.append({
            "k": k,
            "p": p,
            "uno_en": round(1 / p) if p > 0 else None,
            "paga": k >= ACIERTOS_PAGA,
        })
    prob_premio = sum(d["p"] for d in dist if d["paga"])
    return {
        "media": round(media, 4),
        "aciertos_paga": ACIERTOS_PAGA,
        "prob_premio": prob_premio,
        "prob_premio_uno_en": round(1 / prob_premio),
        "dist": dist,
    }


def main():
    if not CSV_IN.exists():
        print(f"No existe {CSV_IN}")
        return
    payload = {
        "suma": dist_suma(),
        "aciertos": dist_aciertos(),
    }
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(JSON_OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    s = payload["suma"]; a = payload["aciertos"]
    print(f"SUMA   : n={s['n']} media={s['media']} desv={s['desv']} rango {s['min']}..{s['max']}")
    print(f"ACIERTOS: media={a['media']} prob_premio={a['prob_premio']*100:.2f}% (1 en {a['prob_premio_uno_en']})")
    print(f"JSON -> {JSON_OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
