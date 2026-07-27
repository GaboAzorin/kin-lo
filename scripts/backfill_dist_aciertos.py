"""
backfill_dist_aciertos.py

Rellena las columnas `dist_aciertos` y `dist_comodin` de
data/suggestions_history.csv para los sorteos que se evaluaron ANTES de que esas
columnas existieran.

Cómo es posible: los archivos `data/*_suggestions_pending.json` están versionados y
contienen las 500 combinaciones de cada grupo. El historial de git conserva, por lo
tanto, las combinaciones exactas que se jugaron para cada sorteo pasado. Este script
las recupera, las vuelve a comparar contra el resultado real y escribe el histograma
de aciertos.

`dist_comodin` (solo Loto) necesita además la columna `LOTO_comodin` en
polla_historial.csv; si el sorteo no la tiene, corre antes
`scripts/backfill_loto_premio.py <desde> <hasta>`.

CORRER EN LOCAL, no en la nube: depende de `git log` completo. Un clon superficial
solo ve los últimos commits y rellena una fracción de las filas sin avisar.

Seguridad: antes de escribir, verifica que la reconstrucción reproduzca EXACTAMENTE
el `aciertos_avg` y el `aciertos_max` ya guardados en el CSV. Si no calzan, la fila
se omite (significaría que el pending recuperado no es el que se evaluó).

Uso:
    python scripts/backfill_dist_aciertos.py            # aplica los cambios
    python scripts/backfill_dist_aciertos.py --dry-run  # solo reporta
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "analytics"))

from retorno import encode_dist  # noqa: E402

HISTORY_PATH = REPO_ROOT / "data" / "suggestions_history.csv"

JUEGOS = {
    "loto": {
        "pending":  "data/loto_suggestions_pending.json",
        "csv":      REPO_ROOT / "data" / "polla_historial.csv",
        "num_cols": [f"LOTO_n{i}" for i in range(1, 7)],
        # 7º número sorteado; define las categorías SUPER. Existe solo en las filas
        # que pasaron por scripts/backfill_loto_premio.py o por el scraper nuevo.
        "col_comodin": "LOTO_comodin",
    },
    "kino": {
        "pending":  "data/kino_suggestions_pending.json",
        "csv":      REPO_ROOT / "data" / "loteria_historial.csv",
        "num_cols": [f"KINO_n{i}" for i in range(1, 15)],
        "col_comodin": None,
    },
}


def _lleno(v) -> bool:
    """True si la celda del CSV trae un valor real (pandas devuelve NaN si está vacía)."""
    s = str(v or "").strip()
    return bool(s) and s.lower() != "nan"


def _git(*args: str) -> str:
    res = subprocess.run(["git", *args], cwd=REPO_ROOT,
                         capture_output=True, text=True)
    if res.returncode != 0:
        return ""
    return res.stdout


def _pendings_por_sorteo(path: str) -> dict[int, dict]:
    """
    {generado_tras_sorteo: sugerencias} recorriendo el historial de git del archivo.

    `git log` va de más nuevo a más viejo, así que para cada valor de
    `generado_tras_sorteo` nos quedamos con la PRIMERA aparición: es el estado
    vigente del pending justo antes de que se evaluara el sorteo siguiente.
    """
    out: dict[int, dict] = {}
    for commit in _git("log", "--format=%H", "--", path).split():
        blob = _git("show", f"{commit}:{path}")
        if not blob:
            continue
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        tras = data.get("generado_tras_sorteo")
        sugerencias = data.get("sugerencias") or {}
        if tras is None or not sugerencias:
            continue
        out.setdefault(int(tras), sugerencias)
    return out


def _resultados(csv_path: Path, num_cols: list[str],
                col_comodin: str | None) -> dict[int, tuple[set[int], int | None]]:
    """{sorteo: (set(números sorteados), comodín o None)} del CSV histórico."""
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path)
    out: dict[int, tuple[set[int], int | None]] = {}
    for _, row in df.iterrows():
        try:
            sorteo = int(row["sorteo"])
        except (TypeError, ValueError):
            continue
        nums = []
        for c in num_cols:
            try:
                nums.append(int(row[c]))
            except (TypeError, ValueError):
                pass
        if len(nums) != len(num_cols):
            continue
        comodin = None
        if col_comodin:
            v = pd.to_numeric(row.get(col_comodin), errors="coerce")
            if pd.notna(v) and int(v) > 0:
                comodin = int(v)
        out[sorteo] = (set(nums), comodin)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="reporta sin escribir el CSV")
    args = ap.parse_args()

    if not HISTORY_PATH.exists():
        print(f"ERROR: no existe {HISTORY_PATH}", file=sys.stderr)
        return 1

    df_h = pd.read_csv(HISTORY_PATH)
    for col in ("dist_aciertos", "dist_comodin"):
        if col not in df_h.columns:
            df_h[col] = ""

    rellenadas = con_comodin = omitidas = 0

    for juego, cfg in JUEGOS.items():
        pendings  = _pendings_por_sorteo(cfg["pending"])
        resultado = _resultados(cfg["csv"], cfg["num_cols"], cfg["col_comodin"])
        if not pendings:
            print(f"[{juego}] sin pendings en el historial de git.")
            continue

        # pending generado tras N  →  se jugó en el sorteo N+1 ya evaluado.
        for tras, sugerencias in sorted(pendings.items()):
            objetivo = tras + 1
            if objetivo not in resultado:
                continue
            nums, comodin = resultado[objetivo]

            for rango, combos in sugerencias.items():
                mask = ((df_h["juego"] == juego)
                        & (pd.to_numeric(df_h["sorteo_predicho"], errors="coerce") == objetivo)
                        & (df_h["rango"] == rango))
                if not mask.any():
                    continue
                idx = df_h.index[mask][0]
                falta_dist = not _lleno(df_h.at[idx, "dist_aciertos"])
                # `dist_comodin` se añadió después, así que una fila puede tener el
                # histograma completo y aun así faltarle el del comodín.
                falta_com  = comodin is not None and not _lleno(df_h.at[idx, "dist_comodin"])
                if not (falta_dist or falta_com):
                    continue

                acs = [len(set(s["combo"]) & nums) for s in combos]
                if not acs:
                    continue

                # Verificación: la reconstrucción debe calzar con lo ya persistido.
                avg_csv = pd.to_numeric(df_h.at[idx, "aciertos_avg"], errors="coerce")
                max_csv = pd.to_numeric(df_h.at[idx, "aciertos_max"], errors="coerce")
                avg_rec = round(sum(acs) / len(acs), 4)
                max_rec = max(acs)
                if (pd.notna(avg_csv) and abs(float(avg_csv) - avg_rec) > 1e-6) or \
                   (pd.notna(max_csv) and int(max_csv) != max_rec):
                    print(f"  ! {juego} #{objetivo} [{rango}] descalce "
                          f"(csv avg={avg_csv} max={max_csv} / "
                          f"reconstruido avg={avg_rec} max={max_rec}) — omitida")
                    omitidas += 1
                    continue

                if falta_dist:
                    df_h.at[idx, "dist_aciertos"] = encode_dist(acs)
                    rellenadas += 1
                if falta_com:
                    df_h.at[idx, "dist_comodin"] = encode_dist(
                        [len(set(s["combo"]) & nums) for s in combos
                         if comodin in s["combo"]])
                    con_comodin += 1

            print(f"[{juego}] sorteo #{objetivo}: {len(sugerencias)} grupos revisados"
                  f"{'' if comodin is None else f' (comodín {comodin})'}.")

    print(f"\nFilas rellenadas: {rellenadas} · con dist_comodin: {con_comodin}"
          f" · omitidas por descalce: {omitidas}")
    if args.dry_run:
        print("--dry-run: no se escribió nada.")
        return 0
    if rellenadas or con_comodin:
        df_h.reindex(columns=list(df_h.columns)).to_csv(
            HISTORY_PATH, index=False, encoding="utf-8")
        print(f"Escrito: {HISTORY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
