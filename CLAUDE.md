# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Descripción del Proyecto

Pipeline automático de datos de lotería chilena + sitio web estático en GitHub Pages.

- **polla.cl** → Loto, Recargado, Revancha, Desquite
- **loteria.cl** → Kino, ReKino, RequeteKino

Los datos se actualizan automáticamente con GitHub Actions y se muestran en una interfaz web estática.

## Comandos Principales

```bash
# Instalar dependencias
pip install -r requirements.txt
playwright install chromium --with-deps

# Scraper polla.cl (descarga sorteos nuevos)
python src/scrapers/scraper_polla.py

# Scraper loteria.cl (descarga sorteos nuevos)
python src/scrapers/scraper_loteria.py

# Explorar estructura de loteria.cl (script temporal de investigación)
python investigar_loteria.py

# Generar métricas y sugerencias
python src/analytics/metrics.py --game loto
python src/analytics/metrics.py --game kino

# Preview del sitio local
python -m http.server 8080 --directory docs
# → abrir http://localhost:8080
```

## Arquitectura

### Flujo de datos

```
GitHub Actions (cron)
  → scraper_polla.py / scraper_loteria.py
  → data/polla_historial.csv / data/loteria_historial.csv
  → src/analytics/metrics.py
  → docs/data/loto_metrics.json / kino_metrics.json
  → GitHub Pages sirve docs/ (HTML + JSON)
```

### Scraper polla.cl (`src/scrapers/scraper_polla.py`)

- Usa **Playwright** + token CSRF.
- API endpoint: `POST https://www.polla.cl/es/get/draw/results` con `gameId=5271`.
- Un solo `gameId` trae Loto + Recargado + Revancha + Desquite (en `additionalGameResults`).
- Parser: `src/parsers/loto_parser_v3.py` → función `parse_loto_rich()`.
- Modo nube: `USE_SCRAPEDO=true` + variable `SCRAPEDO_TOKEN`.

### Scraper loteria.cl (`src/scrapers/scraper_loteria.py`)

- Usa **Scrapling** (`Fetcher` o `DynamicFetcher` si el HTML es JS-rendered).
- URL: `https://www.loteria.cl/resultados/resultado-completo/?id=kino&sorteo=N`.
- Solo devuelve los últimos ~26 sorteos.
- Parser: `src/parsers/loteria_parser.py`.

### Scraper histórico Kino (`src/scrapers/scraper_kinohistorico.py`)

- Fuente: `https://kinohistorico.cl/draw/N` (Angular SSG, datos en TransferState JSON).
- Disponibilidad: sorteos **3100–3198** (la web no cubre ni anteriores ni los más recientes).
- Uso: `python src/scrapers/scraper_kinohistorico.py --desde 3198`
- Se detiene automáticamente tras 10 páginas consecutivas sin datos.
- **No incluir Accept-Encoding en los headers** — urllib no descomprime gzip automáticamente.

### Analytics (`src/analytics/`)

- `metrics.py` lee los CSV y genera JSON en `docs/data/`.
- `suggestions.py` (llamado desde metrics.py) genera 5 combinaciones de 14 números (Kino) o 6 (Loto)
  usando scoring estadístico (frecuencia, gaps, suma, paridad, balance).
- **Unicidad garantizada**: ninguna combinación sugerida ha salido antes en el historial.

## Estructura de CSVs

**`data/polla_historial.csv`** — separador `,`
- Columnas: `sorteo, fecha, dia_semana, LOTO_n1..n6, RECARGADO_n1..n6, REVANCHA_n1..n6, DESQUITE_n1..n6`
- (los comodines fueron eliminados; no se usan en las métricas)

**`data/loteria_historial.csv`** — separador `,`
- Columnas: `sorteo, fecha, dia_semana, KINO_n1..n14, REKINO_n1..n14, REQUETEKINO_n1..n14`

## Horarios de GitHub Actions

| Workflow | Cron (UTC) | Equivalente CLT (UTC-4) |
|---|---|---|
| `scrape-loto.yml` | `15 2 * * 3,5,1` | Mar/Jue/Dom 22:15 |
| `scrape-kino.yml` | `59 3 * * 4,6,1` | Mié/Vie/Dom 23:59 |

## Rangos de Números

- **Loto / Recargado / Revancha / Desquite**: 1–41 (el jugador elige 6)
- **Kino / ReKino / RequeteKino**: 14 números de 1–25; el **jugador también elige 14 números de 1–25**
- Combinaciones posibles Loto: C(41,6) = 4.496.388
- Combinaciones posibles Kino: C(25,14) = 4.457.400

## Variables de Entorno

| Variable | Descripción |
|---|---|
| `USE_SCRAPEDO` | `true` para usar Scrape.do como proxy (modo nube) |
| `SCRAPEDO_TOKEN` | Token(s) de Scrape.do, separados por coma |
