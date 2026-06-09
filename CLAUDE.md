# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Descripción del Proyecto

Pipeline automático de datos de lotería chilena + sitio web estático en GitHub Pages.

- **polla.cl** → Loto, Recargado, Revancha, Desquite
- **loteria.cl** → Kino, ReKino, RequeteKino

Los datos de **Kino se actualizan automáticamente** con GitHub Actions. Los datos de **Loto se actualizan localmente** (polla.cl bloquea las IPs de GitHub) con un script PowerShell.

## Comandos Principales

```bash
# Instalar dependencias
pip install -r requirements.txt
playwright install chromium --with-deps

# Actualizar Loto (correr localmente después de cada sorteo mar/jue/dom; sorteo ~21:00 CLT, resultados publicados ~22:15 CLT)
.\scripts\actualizar_loto.ps1        # scraper + métricas + pozos + commit + push

# Pasos individuales Loto
python src/scrapers/scraper_polla.py
python src/analytics/metrics.py --game loto

# Pasos individuales Kino (normalmente vía GitHub Actions)
python src/scrapers/scraper_loteria.py
python src/scrapers/scraper_kinohistorico.py
python src/analytics/metrics.py --game kino

# Actualizar pozos estimados
python src/scrapers/fetch_pozos.py

# Preview del sitio local
python -m http.server 8080 --directory docs
# → abrir http://localhost:8080
```

## Arquitectura

### Flujo de datos

```
LOTO (local, manual)
  scripts/actualizar_loto.ps1
    → scraper_polla.py       (polla.cl bloquea IPs de GitHub Actions)
    → metrics.py --game loto
    → fetch_pozos.py
    → git commit + push
    → data/polla_historial.csv  docs/data/loto_metrics.json  docs/data/pozos.json

KINO (automático, GitHub Actions cron)
  scrape-kino.yml
    → scraper_loteria.py      (últimos 26 sorteos)
    → scraper_kinohistorico.py (sorteos nuevos del historial)
    → metrics.py --game kino
    → fetch_pozos.py
    → git auto-commit
    → data/loteria_historial.csv  docs/data/kino_metrics.json  docs/data/pozos.json

GitHub Pages sirve docs/ → https://gaboazorin.github.io/kin-lo/
```

### Scraper polla.cl (`src/scrapers/scraper_polla.py`)

- Usa **Playwright** + token CSRF.
- API endpoint: `POST https://www.polla.cl/es/get/draw/results` con `gameId=5271`.
- Un solo `gameId` trae Loto + Recargado + Revancha + Desquite (en `additionalGameResults`).
- Parser: `src/parsers/loto_parser_v3.py` → función `parse_loto_rich()`.
- **Solo funciona desde IPs residenciales/corporativas.** polla.cl bloquea IPs de GitHub Actions.
- Correr con `.\scripts\actualizar_loto.ps1` después de cada sorteo.

### Scraper loteria.cl (`src/scrapers/scraper_loteria.py`)

- Usa la **API REST** `https://rckino.loteria.cl/api/sorteos` consumida con `urllib` (stdlib).
- Sin parámetros → últimos ~26 sorteos; `?sorteo=N` → sorteo N si está dentro de esa ventana.
- La ventana solo expone los últimos ~26 sorteos; el scraper acumula los nuevos en el CSV.
- Parser inline (`_parse_bolitas` dentro del propio scraper); sin Scrapling ni parser HTML externo.

### Scraper histórico Kino (`src/scrapers/scraper_kinohistorico.py`)

- Fuente: **API REST** `https://kinohistorico.cl/kino-api/draws?page=N&limit=50`
- Cobertura: **~2433 sorteos desde 2006** (sorteo 799 en adelante).
- Uso: `python src/scrapers/scraper_kinohistorico.py` (descarga todo lo que no esté en el CSV)
- Uso incremental: `python src/scrapers/scraper_kinohistorico.py --desde 3198`
- **Nota técnica**: la web Angular de kinohistorico.cl llama a `/kino-api/draws/{id}` via AJAX.
  Solo el sorteo 3100 tenía datos pre-renderizados en HTML (SSG); los demás requieren JS.
  Usar la API REST directamente es mucho más eficiente.

### Analytics (`src/analytics/`)

- `metrics.py` lee los CSV y genera JSON en `docs/data/`.
- `suggestions.py` (llamado desde metrics.py) genera **500 combinaciones por rango** de 14 números
  (Kino) o 6 (Loto) optimizando anti-reparto + diversidad. Las primeras 3 (diversidad MMR) son las
  que se muestran en la Home / páginas de juego; las 500 se guardan en el `*_suggestions_pending.json`.
- **Mejor grupo (★)**: tras el sorteo se evalúan las 500 por rango y el rango con mejor promedio de
  aciertos se marca como "mejor grupo". La página `/sugerencias/` muestra las **3 con más aciertos**
  por rango (top-3 a posteriori), no las 3 mostradas en la Home.
- **Unicidad garantizada**: ninguna combinación sugerida ha salido antes en el historial.

## Estructura de CSVs

**`data/polla_historial.csv`** — separador `,`
- Columnas: `sorteo, fecha, dia_semana, LOTO_n1..n6, RECARGADO_n1..n6, REVANCHA_n1..n6, DESQUITE_n1..n6`
- (los comodines fueron eliminados; no se usan en las métricas)

**`data/loteria_historial.csv`** — separador `,`
- Columnas: `sorteo, fecha, dia_semana, KINO_n1..n14, REKINO_n1..n14, REQUETEKINO_n1..n14`

## Actualización de datos

| Juego | Método | Cuándo |
|---|---|---|
| **Loto** | `.\scripts\actualizar_loto.ps1` (local) | Después de cada sorteo (sorteo ~21:00 CLT; resultados ~22:15 CLT): mar/jue/dom |
| **Kino** | GitHub Actions cron automático | `scrape-kino.yml`: `59 3 * * 4,6,1` (UTC) = mié/vie/dom 23:59 CLT |

## Rangos de Números

- **Loto / Recargado / Revancha / Desquite**: 1–41 (el jugador elige 6)
- **Kino / ReKino / RequeteKino**: 14 números de 1–25; el **jugador también elige 14 números de 1–25**
- Combinaciones posibles Loto: C(41,6) = 4.496.388
- Combinaciones posibles Kino: C(25,14) = 4.457.400

