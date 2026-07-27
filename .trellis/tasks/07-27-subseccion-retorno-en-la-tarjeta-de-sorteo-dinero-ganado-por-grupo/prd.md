# Subsección "Retorno" en la tarjeta de sorteo

## Problema

La tarjeta de cada sorteo en `/sugerencias/` muestra aciertos (3 sugeridas + top 3 por
grupo), pero no responde la pregunta práctica: **¿cuánta plata se habría ganado si se
jugaban las 500 combinaciones de cada grupo?**

## Objetivo

Agregar una subsección **Retorno** a la tarjeta de sorteo con, **por cada grupo**
(50/100/250/500/1000/all/all_sub/dia/mes):

- **Ganado**: suma de premios de las 500 combinaciones del grupo en ese sorteo.
- **Costo**: `n_combos × valor del cartón`.
- **Neto**: ganado − costo.
- **ROI %**: ganado / costo × 100.
- **Desglose por categoría**: para cada nivel de aciertos premiado, cuántas de las 500
  lo alcanzaron, el premio unitario y el subtotal.

## Datos

### Premios (Kino)
`data/kino_premios_historial.csv` — una fila por sorteo × categoría con
`aciertos`, `ganadores`, `premio_total`, `premio_individual`. Cubre 3216→hoy.
Categorías Kino: 14 (pozo), 13 (pari-mutuel), 12 = $10.000, 11 = $3.500, 10 = $1.000.

Se usa `premio_individual` tal cual lo publicó Lotería: es "lo que pagó cada cartón
ganador de esa categoría". Para 13 y 14 aciertos el premio es pari-mutuel, así que
jugar 500 cartones extra habría diluido el pozo; el monto mostrado es el publicado,
no el diluido (documentar en la UI).

Cuando `ganadores == 0` en la categoría 14, `premio_individual` es 0 pero
`premio_total` es el pozo acumulado: para 14 aciertos se usa `premio_total`
(sería el único ganador).

### Valor del cartón
Kino: **$1.000** (coincide con que acertar 10 devuelve exactamente $1.000).

### Loto
`polla_historial.csv` solo trae el pozo de 6 aciertos (`LOTO_POZO_REAL`), no las
categorías 4 y 5. → El retorno de Loto **no es calculable** y la UI debe decirlo
explícitamente en vez de mostrar $0 (que sería engañoso).

### Distribución de aciertos de las 500
`data/suggestions_history.csv` hoy guarda solo agregados (avg/max/top-3/deciles), no
el histograma. Se agrega la columna **`dist_aciertos`** (`"7:120;8:180;..."`), poblada
en `_evaluar_y_registrar`.

**Backfill:** los `data/*_suggestions_pending.json` están versionados, así que el
historial de git contiene las 500 combinaciones de cada sorteo pasado. Un script
one-off (`scripts/backfill_dist_aciertos.py`) las recupera y rellena `dist_aciertos`.
Cobertura: Kino 3250–3258, Loto 5447–5455. Anteriores: no recuperables → la UI muestra
el placeholder "se registra desde los próximos sorteos".

Validado: la reconstrucción desde git reproduce **exactamente** `aciertos_avg` y
`aciertos_max` ya persistidos en el CSV para el sorteo 3258 en los 9 grupos.

## Entregables

1. `src/analytics/retorno.py` — tabla de premios por sorteo + cálculo de retorno.
2. `src/analytics/metrics.py` — nueva columna `dist_aciertos`; retorno embebido en
   `docs/data/suggestions_detail.json` (por sorteo × grupo) y agregado por grupo en
   `docs/data/suggestions_history.json`.
3. `scripts/backfill_dist_aciertos.py` — backfill one-off desde git.
4. `docs_src/sugerencias/index.html` — subsección "💰 Retorno" en la tarjeta.
5. `CLAUDE.md` — documentar la fuente de premios y el valor del cartón.

## Fuera de alcance

- Recalcular el premio pari-mutuel diluido por los 500 cartones propios.
- Premios por categoría de Loto (requiere cambiar `scraper_polla.py` y no es
  backfilleable; polla.cl solo es accesible desde IP residencial).
- Re-encriptar `docs/` con StatiCrypt (requiere `STATICRYPT_PASSWORD`, se corre local).
