# Métricas de distribución en sugerencias y visualización

## Goal

Agregar métricas de distribución (mean_gap, gap_std, zonas, paridad) al motor de
sugerencias y a la UI. También reordenar secciones en /kino/ y /loto/ para mostrar
las sugerencias y su rendimiento primero.

## Requirements

1. **Backend — scoring extendido**
   - Agregar `gap_std` y balance de 4 zonas al `_shape_score()` en `suggestions.py`
   - Percentiles históricos para Kino: gap_std p10=0.72, p90=1.37; zonas p10=2, p90=5 por zona
   - `generar_sugerencias()` recibe los nuevos percentiles desde `metrics.py`

2. **Backend — output enriquecido**
   - Cada sugerencia expone: `mean_gap` (float), `gap_std` (float), `zones` (list[int] x4), `parity` (int par, int impar)

3. **Frontend — reorden de secciones** (kino/index.html y loto/index.html)
   - Nuevo orden: Último sorteo → Combinaciones sugeridas → Rendimiento histórico → Frecuencias → Hot-Cold → Distribución de sumas

4. **Frontend — segunda fila de métricas** (kino/index.html)
   - Debajo de la suma: mean_gap, σ gaps, distribución de zonas (e.g. "3/4/3/4")
   - Loto no recibe segunda fila de métricas en esta tarea (pendiente tarea separada)

## Acceptance Criteria

- [ ] Cada sugerencia en `kino_metrics.json` incluye `mean_gap`, `gap_std`, `zones`, `parity`
- [ ] `_shape_score()` penaliza combos con gap_std o distribución de zonas fuera del rango histórico
- [ ] La página /kino/ muestra Sugeridas antes de Frecuencias
- [ ] La página /loto/ muestra Sugeridas antes de Frecuencias
- [ ] Cada tarjeta de sugerencia Kino tiene segunda fila con mean_gap, σ y zonas
- [ ] El sitio levanta sin errores JS (python -m http.server 8080)

## Out of Scope

- Extender métricas de distribución al motor de Loto (percentiles históricos distintos)
- Cambiar el algoritmo MMR de diversidad
- Agregar las métricas a Rekino/Requetekino

## Technical Notes

- `suggestions.py`: agregar helpers `_mean_gap`, `_gap_std`, `_zone_counts`; extender `_shape_score`; enriquecer dict de retorno
- `metrics.py`: calcular percentiles de gap_std y zonas del historial y pasarlos a `generar_sugerencias()`
- `docs/kino/index.html`: reorden de secciones + segunda fila en tarjeta de sugerencia
- `docs/loto/index.html`: solo reorden de secciones
- Zonas Kino: 1-6 / 7-12 / 13-18 / 19-25
- Percentiles históricos Kino (2439 sorteos): mean_gap p50=1.77, gap_std p10=0.72/p90=1.37, por zona p10=2/p90=5
