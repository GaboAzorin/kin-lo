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
  - **Loto**: `data/polla_historial.csv`, que desde que scraper_polla.py guarda
    todas las categorías (`LOTO_MONTO`, `QUINA_5_ACIERTOS_MONTO`, …) trae el premio
    unitario de cada una. Los sorteos anteriores solo tienen los números y devuelven
    None con el motivo. No es backfilleable.

Comodín (solo Loto)
-------------------
Loto sortea un 7º número, el comodín. Las categorías "SUPER_*" exigen que esté
entre los 6 elegidos, así que un mismo número de aciertos paga distinto según lo
lleve o no. Por eso el retorno de Loto necesita `dist_comodin` además de
`dist_aciertos`; sin ella se calcula solo con las categorías normales.
"""

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
PREMIOS_KINO_CSV = REPO_ROOT / "data" / "kino_premios_historial.csv"
PREMIOS_LOTO_CSV = REPO_ROOT / "data" / "polla_historial.csv"

# Valor de un cartón, en pesos. Kino: $1.000 — coincide con que la categoría de
# 10 aciertos pague exactamente $1.000 (te devuelve el cartón). Loto: $1.000, que
# es `columnPrice` de la API (viene en centésimas: 100000).
VALOR_CARTON = {"kino": 1000, "loto": 1000}

# Columna de premio unitario en polla_historial.csv por (aciertos, lleva comodín).
# Un cartón de 6 no puede hacer "6 + comodín": sus 6 números ya son los principales.
COLS_LOTO = {
    (6, False): "LOTO_MONTO",
    (5, True):  "SUPER_QUINA_5_ACIERTOS_COMODIN_MONTO",
    (5, False): "QUINA_5_ACIERTOS_MONTO",
    (4, True):  "SUPER_CUATERNA_4_ACIERTOS_COMODIN_MONTO",
    (4, False): "CUATERNA_4_ACIERTOS_MONTO",
    (3, True):  "SUPER_TERNA_3_ACIERTOS_COMODIN_MONTO",
    (3, False): "TERNA_3_ACIERTOS_MONTO",
    (2, True):  "SUPER_DUPLA_2_ACIERTOS_COMODIN_MONTO",
}

# Si la categoría quedó desierta el premio unitario es 0 y lo que estaba en juego
# es el pozo, que se habría llevado nuestro cartón como único ganador.
POZO_LOTO = {
    "LOTO_MONTO":                             "LOTO_POZO_REAL",
    "SUPER_QUINA_5_ACIERTOS_COMODIN_MONTO":   "SUPER_QUINA_5_ACIERTOS_COMODIN_POZO_REAL",
}

_MOTIVO_LOTO_VIEJO = ("polla.cl publica el premio de cada categoría, pero no se "
                      "guardaba: este sorteo es anterior a que empezáramos a "
                      "registrarlo")


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


_premios_loto_cache: dict[int, dict[tuple[int, bool], int]] | None = None


def _cargar_premios_loto() -> dict[int, dict[tuple[int, bool], int]]:
    """
    {sorteo: {(aciertos, lleva_comodín): premio_por_cartón}} para LOTO.

    Las columnas `*_MONTO` son el premio unitario (`divident` de la API). Cuando la
    categoría quedó desierta valen 0; para las dos de arriba se usa entonces el pozo
    real, que se habría llevado nuestro cartón. Las categorías bajas sin ganadores no
    tienen pozo acumulable, así que quedan fuera.
    """
    global _premios_loto_cache
    if _premios_loto_cache is not None:
        return _premios_loto_cache

    if not PREMIOS_LOTO_CSV.exists():
        _premios_loto_cache = {}
        return _premios_loto_cache

    dp = pd.read_csv(PREMIOS_LOTO_CSV)
    tabla: dict[int, dict[tuple[int, bool], int]] = {}
    for _, row in dp.iterrows():
        try:
            sorteo = int(row["sorteo"])
        except (TypeError, ValueError):
            continue

        # `LOTO_POZO_REAL` existe desde antes que el resto de las categorías, así que
        # por sí solo no basta: daría un retorno "disponible" de $0 para sorteos en
        # los que en realidad no sabemos qué pagaron 3, 4 y 5 aciertos.
        if not any(pd.notna(row.get(col)) for clave, col in COLS_LOTO.items()
                   if clave[0] < 6):
            continue

        for clave, col in COLS_LOTO.items():
            monto = pd.to_numeric(row.get(col), errors="coerce")
            monto = 0 if pd.isna(monto) else int(monto)
            if monto <= 0:
                pozo_col = POZO_LOTO.get(col)
                pozo = pd.to_numeric(row.get(pozo_col), errors="coerce") if pozo_col else None
                monto = 0 if pozo is None or pd.isna(pozo) else int(pozo)
            if monto > 0:
                tabla.setdefault(sorteo, {})[clave] = monto

    _premios_loto_cache = tabla
    return tabla


def tabla_premios(juego: str, sorteo: int) -> tuple[dict[tuple[int, bool], int] | None, str]:
    """
    Devuelve (tabla, motivo). `tabla` es {(aciertos, lleva_comodín): premio_por_cartón}
    o None si no hay datos; `motivo` explica por qué falta (vacío si sí hay datos).
    Kino no tiene comodín, así que todas sus claves llevan False.
    """
    if juego == "kino":
        todas = _cargar_premios_kino()
        if not todas:
            return None, "falta data/kino_premios_historial.csv"
        t = todas.get(int(sorteo))
        if not t:
            return None, f"sin premios registrados para el sorteo #{sorteo}"
        return {(a, False): p for a, p in t.items()}, ""

    if juego == "loto":
        todas = _cargar_premios_loto()
        if not todas:
            return None, "falta data/polla_historial.csv"
        t = todas.get(int(sorteo))
        if not t:
            return None, _MOTIVO_LOTO_VIEJO
        return t, ""

    return None, f"juego desconocido: {juego}"


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------

def calcular_retorno(juego: str, sorteo: int, dist: dict[int, int],
                     n_combos: int | None = None,
                     dist_comodin: dict[int, int] | None = None) -> dict:
    """
    Retorno de jugar TODAS las combinaciones de un grupo en un sorteo.

    Args:
        juego:        "kino" | "loto".
        sorteo:       número del sorteo evaluado.
        dist:         {aciertos: cuántas combinaciones lo lograron} (ver decode_dist).
        n_combos:     total de combinaciones del grupo. Si es None se deduce de `dist`.
        dist_comodin: solo Loto, subconjunto de `dist` que además lleva el comodín.
                      Si falta, se calcula sin las categorías "SUPER_*" y la salida
                      queda marcada con `parcial: True`.

    Returns:
        {"disponible": True, "ganado", "costo", "neto", "roi", "cartones",
         "premiados", "por_categoria": [...]}  ó
        {"disponible": False, "motivo": ...} si faltan premios o la distribución.

    Nota: los premios de las categorías altas son pari-mutuel (se reparte un pozo
    entre los ganadores). Se usa el monto publicado, sin descontar la dilución que
    habrían provocado nuestros propios cartones ganadores.
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

    # Loto sin comodín registrado: no se pueden separar las categorías "SUPER_*",
    # así que todo el grupo se cobra a la tarifa normal y el total queda subestimado.
    con_comodin = dist_comodin or {}
    parcial = juego == "loto" and not con_comodin and any(k[1] for k in premios)

    por_categoria = []
    ganado = 0
    premiados = 0
    for aciertos in sorted(dist, reverse=True):
        n_super  = int(con_comodin.get(aciertos, 0))
        n_normal = int(dist[aciertos]) - n_super
        for lleva, cuenta in ((True, n_super), (False, n_normal)):
            premio = premios.get((int(aciertos), lleva))
            if not premio or cuenta <= 0:
                continue
            subtotal = cuenta * int(premio)
            ganado    += subtotal
            premiados += cuenta
            por_categoria.append({
                "aciertos":    int(aciertos),
                "comodin":     lleva,
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
    if parcial:
        out["parcial"] = True
        out["nota"] = ("sin el comodín del sorteo: no incluye las categorías "
                       "SUPER (5, 4, 3 aciertos + comodín y 2 + comodín)")
    if valor:
        costo = cartones * valor
        out.update({
            "valor_carton": valor,
            "costo":        costo,
            "neto":         ganado - costo,
            "roi":          round(ganado / costo * 100, 1) if costo else None,
        })
    return out
