# Ordenar jugadas por fecha de sorteo real

## Goal

La tabla de `/jugadas/` ordena y muestra por `fecha_jugada` (cuándo se registró la
apuesta), no por la fecha real del sorteo. Como el Kino se registra con varios días
de anticipación, una jugada de Kino con sorteo posterior queda *debajo* de una de Loto
con sorteo anterior (ej. Loto #5433 sorteo 02-06 sobre Kino #3235 sorteo 03-06).
Queremos ordenar y mostrar por **fecha real del sorteo**.

## What I already know

* Columna FECHA: `docs/jugadas/index.html:336` → `${j.fecha_jugada}`.
* Orden: `index.html:354-356` → desc por `fecha_jugada` (dd-mm-yyyy→yyyymmdd), desempate por sorteo desc.
* `historial_index.json` tiene `{juego: {sorteo: {variante:[nums]}}}` — **no** incluye fecha.
* Generador del índice: `metrics.py:_exportar_historial_index()` (líneas 691-725). El CSV
  origen tiene columna `fecha` en formato `yyyy-mm-dd`.
* El frontend ya carga `historial_index.json` (`index.html:605`) y lo usa en `computeAciertos`
  iterando solo las variantes del usuario (`index.html:454`), así que agregar una clave extra
  por sorteo no rompe esa función.
* Jugadas pendientes (ej. #5434) no tienen entrada en el índice → no tienen fecha de sorteo.

## Requirements (evolving)

* Backend: `_exportar_historial_index()` agrega la fecha del sorteo a cada entrada del índice.
* Frontend: ordenar la tabla por fecha de sorteo (desc) y mostrar esa fecha en la columna FECHA.
* Manejo de jugadas pendientes (sin fecha de sorteo aún) — ver Open Questions.

## Decision (ADR-lite)

**Context**: Las jugadas pendientes (sorteo aún no realizado) no tienen entrada en
`historial_index.json`, por lo que no hay fecha de sorteo para ordenar/mostrar.

**Decision**: Las pendientes van **al tope** de la tabla. En la columna FECHA muestran su
`fecha_jugada` (fecha de registro) con marca **"(pendiente)"**. El resto de las filas se
ordena por **fecha de sorteo real** (desc); entre pendientes se ordenan por fecha de registro (desc).

**Consequences**: La columna FECHA es heterogénea (fecha de sorteo para las resueltas, fecha
de registro para las pendientes), pero la marca "(pendiente)" lo deja explícito y evita confusión.

## "Pendiente" = sin resultado

Una jugada se considera pendiente si **no existe** entrada para su sorteo en
`historialIndex[juego][sorteo]` (señal directa de que el sorteo aún no ocurrió/se scrapeó).

## Acceptance Criteria

* [ ] `historial_index.json` incluye `_fecha` (yyyy-mm-dd) por sorteo sin romper `computeAciertos`.
* [ ] La tabla se ordena: pendientes primero (por fecha de registro desc), luego resueltas por fecha de sorteo desc, desempate por sorteo desc.
* [ ] Las filas resueltas muestran la fecha del **sorteo** en la columna FECHA.
* [ ] Las filas pendientes muestran su fecha de registro + marca "(pendiente)".

## Out of Scope

* Cambiar el formato/almacenamiento de `jugadas.json`.
* Cambiar otras páginas (Home, sugerencias, kino, loto).

## Technical Notes

* Estructura propuesta del índice: `{sorteo: {variante:[nums], "_fecha":"yyyy-mm-dd"}}`
  (clave con prefijo `_` para no confundirla con una variante).
* Frontend: lookup `historialIndex[juego][sorteo]._fecha`.
