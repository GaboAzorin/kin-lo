"""
registrar_jugada.py
Registra una jugada personal en data/jugadas.json.
Los aciertos se calculan automáticamente al correr metrics.py.

Uso:
    python src/registrar_jugada.py
    python src/registrar_jugada.py --juego loto
    python src/registrar_jugada.py --juego kino
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR  = REPO_ROOT / "data"
DOCS_DATA = REPO_ROOT / "docs" / "data"
JUGADAS   = DATA_DIR / "jugadas.json"

RANGOS_ORDEN = ["50", "100", "250", "500", "1000", "all"]


def _cargar_jugadas() -> list:
    if not JUGADAS.exists():
        return []
    with open(JUGADAS, encoding="utf-8") as f:
        return json.load(f)


def _guardar_jugadas(jugadas: list):
    with open(JUGADAS, "w", encoding="utf-8") as f:
        json.dump(jugadas, f, ensure_ascii=False, indent=2)


def _cargar_sugerencias(juego: str) -> dict:
    path = DOCS_DATA / f"{juego}_metrics.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("suggestions", {})


def _proximo_sorteo(juego: str) -> int | None:
    csv = DATA_DIR / ("polla_historial.csv" if juego == "loto" else "loteria_historial.csv")
    if not csv.exists():
        return None
    import pandas as pd
    df   = pd.read_csv(csv)
    last = pd.to_numeric(df["sorteo"], errors="coerce").max()
    return int(last) + 1 if not pd.isna(last) else None


def _mostrar_sugerencias(sugerencias: dict, juego: str):
    print(f"\nSugerencias actuales para {juego.upper()}:")
    print(f"  {'Rango':<6}  {'#':<2}  Números")
    print("  " + "-" * 52)
    for rango in RANGOS_ORDEN:
        if rango not in sugerencias:
            continue
        for i, s in enumerate(sugerencias[rango], 1):
            nums = "  ".join(str(n).rjust(2) for n in s["combo"])
            print(f"  {rango:<6}  {i}  [ {nums} ]")
    print()


def _leer_numeros(pick: int, num_range: int) -> list[int]:
    """Pide y valida una lista de `pick` números en rango 1..num_range, sin duplicados."""
    print(f"Ingresa {pick} números del 1 al {num_range} separados por espacio:")
    while True:
        nums_str = input("  > ").strip().split()
        try:
            nums = sorted([int(x) for x in nums_str])
        except ValueError:
            print("  ERROR: solo se aceptan números enteros.")
            continue
        if len(nums) != pick:
            print(f"  ERROR: necesitas exactamente {pick} números.")
            continue
        if any(n < 1 or n > num_range for n in nums):
            print(f"  ERROR: los números deben estar entre 1 y {num_range}.")
            continue
        if len(set(nums)) != pick:
            print("  ERROR: no se permiten números repetidos.")
            continue
        return nums


def _elegir_combo(sugerencias: dict, juego: str) -> tuple[list[int], str | None]:
    pick      = 14 if juego == "kino" else 6
    num_range = 25 if juego == "kino" else 41

    print("Escribe el rango y número (ej: 100-1, 50-2) o 'manual' para ingresar tus números:")
    while True:
        resp = input("  > ").strip().lower()

        if resp == "manual":
            return _leer_numeros(pick, num_range), None

        # Formato rango-indice (ej: "100-1")
        parts = resp.split("-")
        if len(parts) == 2:
            rango, idx_str = parts
            if rango in sugerencias:
                try:
                    idx = int(idx_str) - 1
                    combos = sugerencias[rango]
                    if 0 <= idx < len(combos):
                        return list(combos[idx]["combo"]), rango
                    print(f"  El rango '{rango}' tiene {len(combos)} sugerencias (1-{len(combos)}).")
                    continue
                except ValueError:
                    pass
            else:
                print(f"  Rango '{rango}' no disponible. Opciones: {', '.join(k for k in RANGOS_ORDEN if k in sugerencias)}")
                continue

        print("  Formato inválido. Escribe ej: '100-1', '50-2', 'all-1' o 'manual'.")


def main():
    parser = argparse.ArgumentParser(description="Registra una jugada personal.")
    parser.add_argument("--juego", choices=["loto", "kino"])
    args = parser.parse_args()

    # Elegir juego
    if args.juego:
        juego = args.juego
    else:
        print("¿Qué juego jugaste?  [1] Loto  [2] Kino")
        resp = input("  > ").strip()
        juego = "kino" if resp == "2" else "loto"

    # Próximo sorteo (estimado)
    sorteo = _proximo_sorteo(juego)
    if sorteo is not None:
        print(f"\nPróximo sorteo estimado: #{sorteo}")
        resp = input(f"  Sorteo a registrar [{sorteo}]: ").strip()
        if resp:
            try:
                sorteo = int(resp)
            except ValueError:
                pass
    else:
        print("\nIngresa el número de sorteo:")
        while True:
            try:
                sorteo = int(input("  > ").strip())
                break
            except ValueError:
                print("  ERROR: el sorteo debe ser un número entero.")

    # Mostrar sugerencias y elegir
    sugerencias = _cargar_sugerencias(juego)
    if sugerencias:
        _mostrar_sugerencias(sugerencias, juego)
        numeros, rango = _elegir_combo(sugerencias, juego)
    else:
        print(f"\nNo se encontraron sugerencias. Ingresa números manualmente.")
        pick      = 14 if juego == "kino" else 6
        num_range = 25 if juego == "kino" else 41
        numeros   = _leer_numeros(pick, num_range)
        rango     = None

    # Confirmar
    nums_fmt = "  ".join(str(n).rjust(2) for n in numeros)
    print(f"\nJugada a registrar:")
    print(f"  Juego:   {juego.upper()}")
    print(f"  Sorteo:  #{sorteo}")
    if rango:
        print(f"  Rango:   {rango}")
    print(f"  Números: [ {nums_fmt} ]")
    resp = input("\n¿Confirmar? [S/n]: ").strip().lower()
    if resp == "n":
        print("Cancelado.")
        return

    jugadas = _cargar_jugadas()
    jugadas.append({
        "fecha_jugada":     date.today().isoformat(),
        "juego":            juego,
        "sorteo":           sorteo,
        "numeros":          numeros,
        "rango_sugerencia": rango,
        "aciertos":         None,
    })
    _guardar_jugadas(jugadas)
    print(f"\nJugada registrada. Los aciertos se calcularán al correr el pipeline.")


if __name__ == "__main__":
    main()
