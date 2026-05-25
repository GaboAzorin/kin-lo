# Plan de Construcción: kino-loto SaaS en GitHub Pages

> Documento de planificación técnica detallada. Última actualización: 2026-05-25.

---

## Resumen Ejecutivo

Construir desde cero un sistema de datos de lotería chilena compuesto por:

1. **Pipeline de scraping automático** (GitHub Actions): descarga resultados de polla.cl y loteria.cl
2. **Módulo de análisis estadístico**: calcula métricas de frecuencia, gaps y patrones
3. **Generador de combinaciones**: sugiere jugadas estadísticamente balanceadas
4. **Sitio web público** (GitHub Pages): dashboard estático con visualizaciones

**Costo:** $0 (todo en GitHub Free). **Stack:** Python 3.11 + Playwright + Scrapling + Chart.js.

---

## Alcance de Juegos

| Fuente | Juego | Números por sorteo | Rango |
|---|---|---|---|
| polla.cl | Loto | 6 + comodín | 1–41 |
| polla.cl | Recargado | 6 + comodín | 1–41 |
| polla.cl | Revancha | 6 + comodín | 1–41 |
| polla.cl | Desquite | 6 + comodín | 1–41 |
| loteria.cl | Kino | 14 (sorteo) / 6 (apuesta) | 1–41 |
| loteria.cl | ReKino | 14 | 1–41 |
| loteria.cl | RequeteKino | 14 | 1–41 |

**Combinaciones posibles:**
- Loto: C(41,6) = **4.496.388**
- Kino (apuesta del jugador, 6 de 41): **~4.457.400** según el operador

---

## Estructura Final del Repositorio

```
kino-loto/
│
├── .github/
│   └── workflows/
│       ├── scrape-loto.yml          # Se ejecuta mar/jue/dom a las 22:15 CLT
│       └── scrape-kino.yml          # Se ejecuta mié/vie/dom a las 23:59 CLT
│
├── data/                            # Datos crudos (versionados en Git)
│   ├── polla_historial.csv
│   └── loteria_historial.csv
│
├── src/
│   ├── scrapers/
│   │   ├── scraper_polla.py         # Adaptado de scraper_puro.py (solo Loto+adicionales)
│   │   └── scraper_loteria.py       # Nuevo, usa Scrapling
│   ├── parsers/
│   │   ├── loto_parser_v3.py        # Copia del existente (sin cambios)
│   │   └── loteria_parser.py        # Nuevo: parsea HTML de loteria.cl
│   └── analytics/
│       ├── metrics.py               # Calcula métricas y genera JSON
│       └── suggestions.py           # Genera combinaciones sugeridas
│
├── docs/                            # Raíz de GitHub Pages
│   ├── index.html                   # Dashboard general
│   ├── loto/
│   │   └── index.html               # Página detallada Loto
│   ├── kino/
│   │   └── index.html               # Página detallada Kino
│   └── data/                        # JSON generados automáticamente
│       ├── loto_metrics.json
│       └── kino_metrics.json
│
├── requirements.txt
├── CLAUDE.md
└── PLAN.md                          # Este archivo
```

---

## Fase 1: Repositorio Base + Scraper polla.cl

### 1.1 Inicialización del repositorio

```bash
# En GitHub.com:
# 1. Crear repo: kino-loto (público, sin README inicial)
# 2. Settings → Pages → Source: Deploy from branch → main → /docs
# 3. Clonar localmente

git clone https://github.com/<tu-usuario>/kino-loto.git
cd kino-loto

# Crear estructura de directorios
mkdir -p .github/workflows data src/scrapers src/parsers src/analytics docs/data docs/loto docs/kino
```

### 1.2 requirements.txt

```
# Scraping polla.cl (existente)
playwright>=1.43.0

# Scraping loteria.cl (nuevo)
scrapling[fetchers]>=0.4.0

# Analytics
pandas>=2.0.0

# Utilidades
python-dotenv>=1.0.0
```

**Nota importante:** `scrapling install` en el workflow de loteria instala los browsers. Para polla.cl se usa `playwright install chromium --with-deps`.

### 1.3 scraper_polla.py — Cambios respecto a scraper_puro.py

El archivo `scraper_puro.py` original ya tiene la lógica completa. Los cambios son mínimos:

**a) GAME_CONFIG: eliminar Loto 3, Loto 4, Racha**

```python
# ANTES (scraper_puro.py): 4 juegos
GAME_CONFIG = [
    {"name": "LOTO", "id": "5271", ...},
    {"name": "LOTO 3", "id": "2181", ...},
    {"name": "LOTO 4", "id": "5270", ...},
    {"name": "RACHA", "id": "5272", ...}
]

# DESPUÉS (scraper_polla.py): solo 1 juego
GAME_CONFIG = [
    {
        "name": "LOTO",
        "id": "5271",
        "csv": "data/polla_historial.csv",
        "parser": parse_loto_rich,
        "start_draw": 3803,
    }
]
```

**Por qué funciona con 1 solo juego:** `parse_loto_rich` en `loto_parser_v3.py` ya extrae Recargado, Revancha y Desquite desde `additionalGameResults` dentro de la misma respuesta JSON del sorteo de Loto. Una sola llamada a la API trae los 4 juegos.

**b) Filtrar columnas de salida**

El parser original genera decenas de columnas (ganadores, montos, pozos). Solo nos interesan los números:

```python
# Agregar al inicio del archivo
COLUMNS_POLLA = [
    "sorteo", "fecha", "dia_semana",
    # Loto
    "LOTO_n1", "LOTO_n2", "LOTO_n3", "LOTO_n4", "LOTO_n5", "LOTO_n6", "LOTO_comodin",
    # Recargado
    "RECARGADO_n1", "RECARGADO_n2", "RECARGADO_n3", "RECARGADO_n4", "RECARGADO_n5", "RECARGADO_n6", "RECARGADO_comodin",
    # Revancha
    "REVANCHA_n1", "REVANCHA_n2", "REVANCHA_n3", "REVANCHA_n4", "REVANCHA_n5", "REVANCHA_n6", "REVANCHA_comodin",
    # Desquite
    "DESQUITE_n1", "DESQUITE_n2", "DESQUITE_n3", "DESQUITE_n4", "DESQUITE_n5", "DESQUITE_n6", "DESQUITE_comodin",
]

# Modificar guardar_fila() para filtrar:
def guardar_fila(game, row):
    filtered_row = {k: row.get(k, "") for k in COLUMNS_POLLA}
    # ... resto igual, pero usando filtered_row y COLUMNS_POLLA como fieldnames
```

**c) Agregar dia_semana al row**

El parser actual genera `anio`, `mes`, `dia`, `dia_semana` como parte del resultado. Solo necesitamos retener `dia_semana` (ya viene del parser, no hay que agregarlo manualmente).

**d) Cambiar rutas**

```python
# Ruta de salida siempre relativa al repo:
CSV_OUT = "data/polla_historial.csv"
```

### 1.4 loto_parser_v3.py

**Copiar exactamente** desde el directorio actual. No modificar. Ya tiene todo lo necesario:
- Extrae LOTO_n1..n6, LOTO_comodin
- Extrae RECARGADO_n1..n6 desde `additionalGameResults` (keyword 'RECARGADO')
- Extrae REVANCHA_n1..n6 (keyword 'REVANCHA')
- Extrae DESQUITE_n1..n6 (keyword 'DESQUITE')

### 1.5 Schema CSV — polla_historial.csv

```
sorteo,fecha,dia_semana,LOTO_n1,LOTO_n2,LOTO_n3,LOTO_n4,LOTO_n5,LOTO_n6,LOTO_comodin,RECARGADO_n1,RECARGADO_n2,RECARGADO_n3,RECARGADO_n4,RECARGADO_n5,RECARGADO_n6,RECARGADO_comodin,REVANCHA_n1,REVANCHA_n2,REVANCHA_n3,REVANCHA_n4,REVANCHA_n5,REVANCHA_n6,REVANCHA_comodin,DESQUITE_n1,DESQUITE_n2,DESQUITE_n3,DESQUITE_n4,DESQUITE_n5,DESQUITE_n6,DESQUITE_comodin
```

Ejemplo de fila:
```
3803,2020-01-05,Sunday,3,8,15,22,31,38,12,5,10,17,24,33,40,8,2,9,19,27,35,41,15,4,11,20,28,36,39,7
```

---

## Fase 2: Scraper loteria.cl con Scrapling

### 2.1 Investigación del sitio (paso crítico antes de escribir el parser)

**Objetivo:** entender cómo loteria.cl sirve sus resultados históricos antes de escribir código.

```python
# investigar_loteria.py — Script temporal de exploración
from scrapling.fetchers import Fetcher

# Probar página principal
url = "https://www.loteria.cl/resultados/resultado-completo/?id=kino"
page = Fetcher.get(url, stealthy_headers=True)

print("Status:", page.status)
print("Primeros 2000 chars del HTML:")
print(page.html[:2000])

# Buscar si hay un sorteo específico accesible
url2 = "https://www.loteria.cl/resultados/resultado-completo/?id=kino&sorteo=3230"
page2 = Fetcher.get(url2, stealthy_headers=True)
print("\n--- Sorteo específico ---")
print(page2.html[:1000])
```

**Posibles outcomes:**

| Caso | HTML devuelto | Estrategia |
|---|---|---|
| A | HTML completo con números visibles | `Fetcher` + CSS selectors (más simple) |
| B | HTML vacío / `<div>` sin datos | `DynamicFetcher` (JS rendering) |
| C | Error 403/429 | Headers personalizados o `StealthyFetcher` |

**URLs a probar para historial:**
- `?id=kino` — último sorteo
- `?id=kino&sorteo=3230` — sorteo específico
- `?id=kino&fecha=2026-05-21` — por fecha (si existe)

**Referencia:** el proyecto https://github.com/codedeamon/Crawling-Kino-Results usa regex directamente sobre el HTML → confirma que el HTML es parseable.

### 2.2 scraper_loteria.py

```python
"""
scraper_loteria.py
Descarga resultados de Kino/ReKino/RequeteKino desde loteria.cl usando Scrapling.
"""
import csv
import os
import time
from datetime import datetime

# Usar Fetcher simple primero; cambiar a DynamicFetcher si el HTML viene vacío
from scrapling.fetchers import Fetcher  # o DynamicFetcher

from parsers.loteria_parser import parse_kino_page

BASE_URL = "https://www.loteria.cl/resultados/resultado-completo/"
CSV_OUT = "data/loteria_historial.csv"
DELAY_SECONDS = 1.5  # respetar al servidor
MAX_ERRORS = 5

COLUMNS_LOTERIA = [
    "sorteo", "fecha", "dia_semana",
    "KINO_n1","KINO_n2","KINO_n3","KINO_n4","KINO_n5","KINO_n6","KINO_n7",
    "KINO_n8","KINO_n9","KINO_n10","KINO_n11","KINO_n12","KINO_n13","KINO_n14",
    "REKINO_n1","REKINO_n2","REKINO_n3","REKINO_n4","REKINO_n5","REKINO_n6","REKINO_n7",
    "REKINO_n8","REKINO_n9","REKINO_n10","REKINO_n11","REKINO_n12","REKINO_n13","REKINO_n14",
    "REQUETEKINO_n1","REQUETEKINO_n2","REQUETEKINO_n3","REQUETEKINO_n4","REQUETEKINO_n5",
    "REQUETEKINO_n6","REQUETEKINO_n7","REQUETEKINO_n8","REQUETEKINO_n9","REQUETEKINO_n10",
    "REQUETEKINO_n11","REQUETEKINO_n12","REQUETEKINO_n13","REQUETEKINO_n14",
]

def get_start_id() -> int:
    """Lee el último sorteo del CSV para saber desde dónde continuar."""
    if not os.path.exists(CSV_OUT):
        return 1  # o el primer sorteo histórico conocido
    max_id = 0
    with open(CSV_OUT, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("sorteo", "").isdigit():
                max_id = max(max_id, int(row["sorteo"]))
    return max_id + 1 if max_id > 0 else 1

def guardar_fila(row: dict):
    file_exists = os.path.exists(CSV_OUT)
    with open(CSV_OUT, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS_LOTERIA)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in COLUMNS_LOTERIA})

def main():
    current_id = get_start_id()
    errors = 0

    while errors < MAX_ERRORS:
        url = f"{BASE_URL}?id=kino&sorteo={current_id}"
        try:
            page = Fetcher.get(url, stealthy_headers=True, timeout=30)
            row = parse_kino_page(page.html, current_id)

            if row is None:
                # Sorteo no encontrado → puede ser futuro o no existir
                errors += 1
                current_id += 1
                continue

            guardar_fila(row)
            print(f"#{current_id} guardado OK — {row.get('fecha','?')}")
            current_id += 1
            errors = 0
            time.sleep(DELAY_SECONDS)

        except Exception as e:
            print(f"Error en #{current_id}: {e}")
            errors += 1
            time.sleep(2)

if __name__ == "__main__":
    main()
```

### 2.3 loteria_parser.py

El parser exacto depende de la estructura HTML que se descubra en el paso 2.1. El esqueleto:

```python
"""
loteria_parser.py
Parsea el HTML de una página de resultados de loteria.cl.
"""
import re
from datetime import datetime

def parse_kino_page(html: str, sorteo_id: int) -> dict | None:
    """
    Recibe el HTML de la página de un sorteo de Kino y devuelve
    un dict con las columnas del CSV, o None si no hay datos.
    """
    if not html or len(html.strip()) < 500:
        return None  # Página vacía

    row = {"sorteo": sorteo_id}

    # --- Fecha ---
    # Ejemplo hipotético (ajustar a la estructura real):
    # <span class="fecha-sorteo">Miércoles 21 de Mayo de 2026</span>
    fecha_match = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})', html, re.IGNORECASE)
    if fecha_match:
        # parsear fecha y dia_semana
        ...

    # --- Números Kino (14 números) ---
    # Buscar la sección de Kino principal y extraer los 14 números en orden
    # Ajustar selector según la estructura HTML real
    kino_nums = re.findall(r'<span[^>]*class="[^"]*bola-kino[^"]*"[^>]*>(\d+)</span>', html)
    if len(kino_nums) >= 14:
        for i, n in enumerate(kino_nums[:14], 1):
            row[f"KINO_n{i}"] = int(n)

    # --- ReKino y RequeteKino ---
    # Lógica similar, buscar sus secciones específicas en el HTML

    return row if "KINO_n1" in row else None
```

**Nota:** Los selectores exactos se definen al inspeccionar el HTML real en el paso 2.1.

### 2.4 Schema CSV — loteria_historial.csv

El schema ya está definido en el `historial.csv` del proyecto actual:

```
sorteo;fecha;KINO_n1;...;KINO_n14;REKINO_n1;...;REKINO_n14;REQUETEKINO_n1;...;REQUETEKINO_n14
```

**Cambio:** pasar de separador `;` a `,` para consistencia con polla_historial.csv.

---

## Fase 3: Analytics Pipeline

### 3.1 metrics.py

Este script lee el CSV y genera el JSON que consume el frontend.

```python
"""
metrics.py
Genera docs/data/{loto,kino}_metrics.json desde los CSVs históricos.
"""
import pandas as pd
import json
import sys
from itertools import combinations
from pathlib import Path

def calcular_metricas_loto(df: pd.DataFrame) -> dict:
    """Calcula métricas para Loto (y Recargado/Revancha/Desquite)."""
    numero_cols = [f"LOTO_n{i}" for i in range(1, 7)]
    numeros = df[numero_cols].values.flatten()
    numeros = numeros[~pd.isnull(numeros)].astype(int)

    total_sorteos = len(df)

    # 1. Frecuencias absolutas y relativas
    freq = {}
    for n in range(1, 42):
        count = int((numeros == n).sum())
        freq[str(n)] = {
            "count": count,
            "pct": round(count / total_sorteos * 100, 2)
        }

    # 2. Gap: sorteos desde la última aparición de cada número
    gaps = {}
    for n in range(1, 42):
        gap = 0
        for _, row in df.iloc[::-1].iterrows():
            nums_row = [row.get(f"LOTO_n{i}") for i in range(1, 7)]
            if n in nums_row:
                break
            gap += 1
        gaps[str(n)] = gap

    # 3. Distribución de sumas
    sumas = df[numero_cols].sum(axis=1).dropna()
    sum_stats = {
        "min": int(sumas.min()),
        "max": int(sumas.max()),
        "mean": round(float(sumas.mean()), 1),
        "p10": int(sumas.quantile(0.10)),
        "p25": int(sumas.quantile(0.25)),
        "p75": int(sumas.quantile(0.75)),
        "p90": int(sumas.quantile(0.90)),
    }

    # 4. Distribución par/impar
    pares_pct = round(float((numeros % 2 == 0).mean()) * 100, 1)

    # 5. Top 10 pares (co-ocurrencia)
    pair_count = {}
    for _, row in df.iterrows():
        nums = sorted([int(row[f"LOTO_n{i}"]) for i in range(1, 7) if pd.notna(row.get(f"LOTO_n{i}"))])
        for pair in combinations(nums, 2):
            key = f"{pair[0]}-{pair[1]}"
            pair_count[key] = pair_count.get(key, 0) + 1
    top_pairs = sorted(pair_count.items(), key=lambda x: x[1], reverse=True)[:10]

    # 6. Último sorteo
    last = df.iloc[-1]
    ultimo_sorteo = {
        "sorteo": int(last.get("sorteo", 0)),
        "fecha": str(last.get("fecha", "")),
        "numeros": [int(last.get(f"LOTO_n{i}", 0)) for i in range(1, 7)],
        "comodin": int(last.get("LOTO_comodin", 0)) if pd.notna(last.get("LOTO_comodin")) else None,
    }

    return {
        "total_sorteos": total_sorteos,
        "frequencies": freq,
        "gaps": gaps,
        "sum_stats": sum_stats,
        "pares_pct": pares_pct,
        "top_pairs": [{"pair": p[0], "count": p[1]} for p in top_pairs],
        "ultimo_sorteo": ultimo_sorteo,
    }

def main(game: str):
    if game == "loto":
        df = pd.read_csv("data/polla_historial.csv")
        metricas = calcular_metricas_loto(df)
        # (agregar submétricas para Recargado, Revancha, Desquite análogamente)
        output_path = "docs/data/loto_metrics.json"
    elif game == "kino":
        df = pd.read_csv("data/loteria_historial.csv")
        # metricas = calcular_metricas_kino(df)  # análogo pero con 14 números por sorteo
        output_path = "docs/data/kino_metrics.json"
    else:
        raise ValueError(f"Juego desconocido: {game}")

    # Agregar sugerencias
    from suggestions import generar_sugerencias
    metricas["suggestions"] = generar_sugerencias(df, metricas, game)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metricas, f, ensure_ascii=False, indent=2)
    print(f"✓ Métricas guardadas en {output_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", required=True, choices=["loto", "kino"])
    args = parser.parse_args()
    main(args.game)
```

### 3.2 suggestions.py

Algoritmo de scoring para generar combinaciones válidas y estadísticamente balanceadas.

```python
"""
suggestions.py
Genera 5 combinaciones de 6 números para Loto o Kino.
"""
import random
import pandas as pd
from itertools import combinations

def generar_sugerencias(df: pd.DataFrame, metricas: dict, game: str, n=5) -> list:
    """
    Genera n combinaciones de 6 números usando scoring estadístico.
    Garantiza que ninguna combinación haya salido antes en el historial.
    """
    # Construir set de combinaciones históricas (para el check de unicidad)
    num_prefix = "LOTO" if game == "loto" else "KINO"
    num_cols = [f"{num_prefix}_n{i}" for i in range(1, 7)]  # 6 números del jugador

    historial_sets = set()
    for _, row in df.iterrows():
        nums = tuple(sorted(int(row[c]) for c in num_cols if pd.notna(row.get(c))))
        if len(nums) == 6:
            historial_sets.add(nums)

    # Parámetros estadísticos del historial
    sum_p20 = metricas["sum_stats"]["p10"]  # aceptar rango más amplio
    sum_p80 = metricas["sum_stats"]["p90"]
    freq = metricas["frequencies"]  # {"1": {"pct": X}, ...}
    gaps = metricas["gaps"]          # {"1": 3, ...}
    total = metricas["total_sorteos"]

    def score(combo: tuple) -> float:
        s = sum(combo)

        # 1. Suma dentro del rango histórico p10-p90
        score_suma = 1.0 if sum_p20 <= s <= sum_p80 else 0.3

        # 2. Balance par/impar (2-4 pares es lo más común)
        pares = sum(1 for n in combo if n % 2 == 0)
        score_paridad = 1.0 if 2 <= pares <= 4 else 0.5

        # 3. Balance alto/bajo (mitad del rango = 21 para 1-41)
        bajos = sum(1 for n in combo if n <= 20)
        score_balance = 1.0 if 2 <= bajos <= 4 else 0.5

        # 4. Frecuencia: penalizar números con frecuencia extrema (muy alta o muy baja)
        freq_esperada = 100 * 6 / 41  # ~14.6% esperado por número
        freq_scores = []
        for n in combo:
            pct = freq.get(str(n), {}).get("pct", freq_esperada)
            dist = abs(pct - freq_esperada) / freq_esperada
            freq_scores.append(max(0, 1 - dist))
        score_freq = sum(freq_scores) / len(freq_scores)

        # 5. Penalizar 3+ consecutivos
        nums_sorted = sorted(combo)
        consecutivos = 0
        for i in range(len(nums_sorted) - 1):
            if nums_sorted[i+1] - nums_sorted[i] == 1:
                consecutivos += 1
        score_consec = 0.0 if consecutivos >= 2 else 1.0

        # Score final ponderado
        return (
            0.30 * score_suma +
            0.20 * score_paridad +
            0.20 * score_balance +
            0.20 * score_freq +
            0.10 * score_consec
        )

    # Generar candidatos aleatorios y seleccionar los mejores
    candidatos = []
    intentos = 0
    while len(candidatos) < 500 and intentos < 10000:
        intentos += 1
        combo = tuple(sorted(random.sample(range(1, 42), 6)))
        if combo in historial_sets:
            continue
        s = score(combo)
        candidatos.append((combo, s))

    # Ordenar por score y deduplicar, tomar top-n
    candidatos.sort(key=lambda x: x[1], reverse=True)
    resultado = []
    vistos = set()
    for combo, s in candidatos:
        if combo not in vistos and len(resultado) < n:
            vistos.add(combo)
            resultado.append({
                "combo": list(combo),
                "suma": sum(combo),
                "score": round(s, 3),
            })

    return resultado
```

**Output de ejemplo en el JSON:**

```json
"suggestions": [
  {"combo": [5, 12, 19, 26, 33, 38], "suma": 133, "score": 0.891},
  {"combo": [3, 11, 17, 24, 31, 40], "suma": 126, "score": 0.875},
  {"combo": [8, 14, 22, 27, 35, 39], "suma": 145, "score": 0.862},
  {"combo": [6, 15, 20, 28, 32, 37], "suma": 138, "score": 0.851},
  {"combo": [4, 13, 21, 29, 34, 41], "suma": 142, "score": 0.843}
]
```

---

## Fase 4: GitHub Actions

### 4.1 scrape-loto.yml

```yaml
name: Scrape Loto (polla.cl)

on:
  # Horario: mar/jue/dom a las 22:15 CLT
  # CLT = UTC-4 (invierno) → 22:15 CLT = 02:15 UTC del día siguiente
  # Días del sorteo: martes=2, jueves=4, domingo=0
  # Día del job (día siguiente): miércoles=3, viernes=5, lunes=1
  schedule:
    - cron: '15 2 * * 3,5,1'
  workflow_dispatch:   # También permite ejecución manual desde la UI de GitHub

permissions:
  contents: write    # Necesario para hacer commit de los CSV

jobs:
  scrape-loto:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout repositorio
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Setup Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Instalar dependencias Python
        run: pip install -r requirements.txt

      - name: Instalar Chromium para Playwright
        run: playwright install chromium --with-deps

      - name: Ejecutar scraper polla.cl
        run: python src/scrapers/scraper_polla.py

      - name: Calcular métricas y sugerencias (Loto)
        run: python src/analytics/metrics.py --game loto

      - name: Commit y push de datos actualizados
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "data(loto): actualizar historial ${{ github.run_id }}"
          file_pattern: "data/polla_historial.csv docs/data/loto_metrics.json"
```

### 4.2 scrape-kino.yml

```yaml
name: Scrape Kino (loteria.cl)

on:
  # Horario: mié/vie/dom a las 23:59 CLT
  # 23:59 CLT (UTC-4) = 03:59 UTC del día siguiente
  # Días del sorteo: miércoles=3, viernes=5, domingo=0
  # Día del job (día siguiente): jueves=4, sábado=6, lunes=1
  schedule:
    - cron: '59 3 * * 4,6,1'
  workflow_dispatch:

permissions:
  contents: write

jobs:
  scrape-kino:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Instalar dependencias
        run: pip install -r requirements.txt
        # Nota: solo instalar browsers de Scrapling si se usa DynamicFetcher:
        # run: pip install -r requirements.txt && scrapling install

      - name: Ejecutar scraper loteria.cl
        run: python src/scrapers/scraper_loteria.py

      - name: Calcular métricas y sugerencias (Kino)
        run: python src/analytics/metrics.py --game kino

      - uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "data(kino): actualizar historial ${{ github.run_id }}"
          file_pattern: "data/loteria_historial.csv docs/data/kino_metrics.json"
```

### 4.3 Nota sobre timezone

| Juego | Sorteo (hora local CLT) | CLT (UTC-4 invierno) | Cron UTC | Días del job |
|---|---|---|---|---|
| Loto | Mar/Jue/Dom 22:15 | +4h → día sig. | `15 2 * * 3,5,1` | Mié/Vie/Lun |
| Kino | Mié/Vie/Dom 23:59 | +4h → día sig. | `59 3 * * 4,6,1` | Jue/Sáb/Lun |

En verano (CLST = UTC-3), el job corre 1h más tarde en hora local, lo cual es aceptable porque los resultados ya están publicados desde la hora indicada.

---

## Fase 5: Frontend GitHub Pages

### 5.1 Estructura de páginas

**docs/index.html** — Dashboard:
- Header: "kino-loto.cl · Análisis de resultados"
- Card Loto: último sorteo + botón "Ver análisis completo"
- Card Kino: último sorteo + botón "Ver análisis completo"
- Footer: "Actualizado automáticamente · Datos desde polla.cl y loteria.cl"

**docs/loto/index.html** — Análisis Loto:
- Último sorteo: los 6 números destacados + comodín
- **Heatmap de frecuencias**: grilla 1-41 con color según frecuencia (verde=frecuente, rojo=infrecuente)
- **Gráfico de gaps**: barras horizontales por número (qué tan "descansado" está cada uno)
- **Distribución de sumas**: histograma de sumas históricas + línea del rango normal
- **5 combinaciones sugeridas**: cards con los 6 números + suma + score

**docs/kino/index.html** — Análisis Kino: misma estructura.

### 5.2 Cómo se actualiza el frontend

GitHub Pages sirve los archivos de `/docs` directamente. El proceso es:

```
Workflow ejecuta → genera JSON en docs/data/ → hace push → GitHub Pages actualiza
```

El HTML no cambia; solo cambian los JSON. El browser carga el JSON en cada visita con `fetch()`.

### 5.3 Ejemplo de código frontend (fragmento)

```html
<!-- docs/loto/index.html -->
<script>
async function loadData() {
  const resp = await fetch('../data/loto_metrics.json');
  const data = await resp.json();
  
  // Mostrar último sorteo
  const nums = data.ultimo_sorteo.numeros;
  document.getElementById('ultimo-sorteo').innerHTML =
    nums.map(n => `<span class="bola">${n}</span>`).join('');
  
  // Heatmap de frecuencias con Chart.js
  const labels = Object.keys(data.frequencies);   // ['1','2',...,'41']
  const values = labels.map(k => data.frequencies[k].pct);
  
  new Chart(document.getElementById('freq-chart'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Frecuencia (%)',
        data: values,
        backgroundColor: values.map(v => v > 15 ? '#22c55e' : v > 12 ? '#eab308' : '#ef4444')
      }]
    }
  });
  
  // Sugerencias
  const sugEl = document.getElementById('sugerencias');
  data.suggestions.forEach((s, i) => {
    sugEl.innerHTML += `
      <div class="card">
        <h3>Combinación ${i+1}</h3>
        <div class="numeros">${s.combo.map(n => `<span class="bola">${n}</span>`).join('')}</div>
        <small>Suma: ${s.suma} · Score: ${s.score}</small>
      </div>`;
  });
}
loadData();
</script>
```

---

## Orden de Implementación (checklist)

### Semana 1 — Base + polla.cl

- [ ] Crear repo en GitHub, activar Pages
- [ ] Copiar `loto_parser_v3.py` → `src/parsers/loto_parser_v3.py`
- [ ] Escribir `src/scrapers/scraper_polla.py` (adaptar scraper_puro.py)
- [ ] Testear scraper polla.cl localmente
- [ ] Verificar `data/polla_historial.csv` con schema correcto
- [ ] Escribir `.github/workflows/scrape-loto.yml`
- [ ] Push inicial + ejecutar workflow manualmente
- [ ] Verificar que el CSV se actualiza en el repo

### Semana 2 — Kino

- [ ] Ejecutar script de investigación de loteria.cl (`investigar_loteria.py`)
- [ ] Determinar estrategia HTML (Fetcher vs DynamicFetcher)
- [ ] Escribir `src/parsers/loteria_parser.py`
- [ ] Escribir `src/scrapers/scraper_loteria.py`
- [ ] Testear scraper loteria.cl localmente
- [ ] Verificar `data/loteria_historial.csv`
- [ ] Escribir `.github/workflows/scrape-kino.yml`
- [ ] Verificar workflow Kino

### Semana 3 — Analytics + Frontend

- [ ] Escribir `src/analytics/metrics.py`
- [ ] Escribir `src/analytics/suggestions.py`
- [ ] Testear: `python src/analytics/metrics.py --game loto`
- [ ] Verificar `docs/data/loto_metrics.json`
- [ ] Testear: `python src/analytics/metrics.py --game kino`
- [ ] Escribir `docs/index.html`
- [ ] Escribir `docs/loto/index.html`
- [ ] Escribir `docs/kino/index.html`
- [ ] Testear localmente: `python -m http.server 8080 --directory docs`
- [ ] Push final + verificar site en `https://<usuario>.github.io/kino-loto/`

---

## Comandos de Desarrollo

```bash
# Instalar dependencias
pip install -r requirements.txt
playwright install chromium

# Ejecutar scrapers manualmente
python src/scrapers/scraper_polla.py
python src/scrapers/scraper_loteria.py

# Generar métricas
python src/analytics/metrics.py --game loto
python src/analytics/metrics.py --game kino

# Preview del sitio
python -m http.server 8080 --directory docs
# → abrir http://localhost:8080
```

---

## Decisiones Técnicas y Justificaciones

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Playwright para polla.cl | Scrapling | El código ya funciona y polla.cl requiere CSRF token |
| Scrapling para loteria.cl | Playwright | Librería nueva solicitada; más liviana para sitios sin CSRF |
| CSV en Git | SQLite / PostgreSQL | Simplicidad, trazabilidad, sin infraestructura |
| GitHub Pages | Vercel / Netlify | Integración nativa, zero config, $0 |
| HTML/JS puro | React/Vue | Sin build step, deploy instantáneo, mantenimiento mínimo |
| Chart.js | D3.js | Curva de aprendizaje menor, suficiente para este caso |
| 2 CSVs separados | 1 CSV combinado | Fuentes distintas, schemas diferentes, pipelines independientes |
