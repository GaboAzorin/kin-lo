"""
retorno.py
Traduce la distribución de aciertos de un grupo de sugerencias a dinero: cuánto se
habría ganado, cuánto habría costado y cuál sería el neto si se hubieran jugado las
500 combinaciones de ese grupo en un sorteo.

Se usa desde metrics.py (al exportar suggestions_detail.json) y desde
scripts/backfill_dist_aciertos.py.

Fuentes de premios
------------------
  - **Kino**: `data/kino_premios_historial.csv`, que acumula el desglose por
    categoría (10-14 aciertos) de cada sorteo desde el sorteo 3216. Lo llena
    `src/scrapers/scraper_premios_kino.py` en el cron; no es backfilleable
    (ver CLAUDE.md).
  - **Loto**: no hay datos por categoría. `polla_historial.csv` solo guarda el pozo
    de 6 aciertos (`LOTO_POZO_REAL`), no lo que pagan 4 y 5 aciertos, así que el
    retorno de Loto NO es calculable y estas funciones devuelven None con el motivo.
"""

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
PREMIOS_KINO_CSV = REPO_ROOT / "data" / "kino_premios_historial.csv"

# Valor de un cartón, en pesos. Kino: $1.000 — coincide con que la categoría de
# 10 aciertos pague exactamente $1.000 (te devuelve el cartón).
VALOR_CARTON = {"kino": 1000}

_MOTIVO_LOTO = ("polla.cl no publica el premio de 4 y 5 aciertos en los datos que "
                "guardamos: solo el pozo de 6 aciertos")


# ---------------------------------------------------------------------------
# Codificación de la distribución de aciertos en el CSV de historial
# ---------------------------------------------------------------------------

def encode_dist(aciertos: list[int]) -> str:
    """Codifica una lista de aciertos como histograma 'nivel:cuenta;…' ascendente."""
    hist: dict[int, int] = {}
    for a in aciertos:
        hist[int(a)] = hist.get(int(a), 0) + 1
    return ";".join(f"{k}:{hist[k]}" for k in sorted(hist))


def decode_dist(s) -> dict[int, int]:
    """Inverso de encode_dist. {} si el valor está vacío o es inválido."""
    out: dict[int, int] = {}
    for parte in str(s).split(";"):
        parte = parte.strip()
        if not parte or ":" not in parte:
            continue
        nivel, cuenta = parte.rsplit(":", 1)
        try:
            out[int(nivel)] = out.get(int(nivel), 0) + int(cuenta)
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------
# Tabla de premios
# ---------------------------------------------------------------------------

_premios_cache: dict[int, dict[int, int]] | None = None


def _cargar_premios_kino() -> dict[int, dict[int, int]]:
    """
    {sorteo: {aciertos: premio_por_carton}} para el juego KINO.

    `premio_individual` es lo que pagó cada cartón ganador. Cuando nadie ganó la
    categoría (típico en 14 aciertos) ese campo viene en 0 y el monto relevante es
    `premio_total`: el pozo completo, que se habría llevado nuestro cartón como
    único ganador.
    """
    global _premios_cache
    if _premios_cache is not None:
        return _premios_cache

    if not PREMIOS_KINO_CSV.exists():
        _premios_cache = {}
        return _premios_cache

    dp = pd.read_csv(PREMIOS_KINO_CSV)
    dp = dp[dp["game_code"] == "KINO"]

    tabla: dict[int, dict[int, int]] = {}
    for _, row in dp.iterrows():
        try:
            sorteo   = int(row["sorteo"])
            aciertos = int(row["aciertos"])
        except (TypeError, ValueError):
            continue
        gan   = pd.to_numeric(row.get("ganadores"), errors="coerce")
        ind   = pd.to_numeric(row.get("premio_individual"), errors="coerce")
        total = pd.to_numeric(row.get("premio_total"), errors="coerce")
        gan   = 0 if pd.isna(gan)   else int(gan)
        ind   = 0 if pd.isna(ind)   else int(ind)
        total = 0 if pd.isna(total) else int(total)

        premio = ind if gan > 0 else total
        if premio > 0:
            tabla.setdefault(sorteo, {})[aciertos] = premio

    _premios_cache = tabla
    return tabla


def tabla_premios(juego: str, sorteo: int) -> tuple[dict[int, int] | None, str]:
    """
    Devuelve (tabla, motivo). `tabla` es {aciertos: premio_por_cartón} o None si no
    hay datos; `motivo` explica por qué falta (cadena vacía si sí hay datos).
    """
    if juego != "kino":
        return None, _MOTIVO_LOTO

    todas = _cargar_premios_kino()
    if not todas:
        return None, "falta data/kino_premios_historial.csv"
    t = todas.get(int(sorteo))
    if not t:
        return None, f"sin premios registrados para el sorteo #{sorteo}"
    return t, ""


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------

def calcular_retorno(juego: str, sorteo: int, dist: dict[int, int],
                     n_combos: int | None = None) -> dict:
    """
    Retorno de jugar TODAS las combinaciones de un grupo en un sorteo.

    Args:
        juego:    "kino" | "loto".
        sorteo:   número del sorteo evaluado.
        dist:     {aciertos: cuántas combinaciones lo lograron} (ver decode_dist).
        n_combos: total de combinaciones del grupo. Si es None se deduce de `dist`.

    Returns:
        {"disponible": True, "ganado", "costo", "neto", "roi", "cartones",
         "premiados", "por_categoria": [...]}  ó
        {"disponible": False, "motivo": ...} si faltan premios o la distribución.

    Nota: los premios de 13 y 14 aciertos son pari-mutuel (se reparte un pozo entre
    los ganadores). Se usa el monto publicado por Lotería, sin descontar la dilución
    que habrían provocado nuestros propios cartones ganadores.
    """
    if not dist:
        return {"disponible": False,
                "motivo": "la distribución de aciertos se registra desde los "
                          "próximos sorteos"}

    premios, motivo = tabla_premios(juego, sorteo)
    if premios is None:
        return {"disponible": False, "motivo": motivo}

    cartones = int(n_combos) if n_combos else sum(dist.values())
    valor    = VALOR_CARTON.get(juego)

    por_categoria = []
    ganado = 0
    premiados = 0
    for aciertos in sorted(dist, reverse=True):
        premio = premios.get(int(aciertos))
        if not premio:
            continue
        cuenta   = int(dist[aciertos])
        subtotal = cuenta * int(premio)
        ganado    += subtotal
        premiados += cuenta
        por_categoria.append({
            "aciertos":    int(aciertos),
            "cartones":    cuenta,
            "premio_unit": int(premio),
            "subtotal":    subtotal,
        })

    out = {
        "disponible":    True,
        "ganado":        ganado,
        "cartones":      cartones,
        "premiados":     premiados,
        "por_categoria": por_categoria,
    }
    if valor:
        costo = cartones * valor
        out.update({
            "valor_carton": valor,
            "costo":        costo,
            "neto":         ganado - costo,
            "roi":          round(ganado / costo * 100, 1) if costo else None,
        })
    return out
