# Pre-registro: ¿hay tendencias predecibles en los rangos del Kino?

> **Estado:** ABIERTO, esperando definir hipótesis. Creado 2026-06-18.
> **Para retomar:** el usuario dirá *"Quiero entrarle"*. Ver sección **▶ CÓMO SEGUIR MAÑANA**.

---

## ▶ CÓMO SEGUIR MAÑANA (instrucciones para Claude)

Cuando el usuario diga "Quiero entrarle" (o similar), hacer esto, en orden:

1. **Leer este documento completo** + el contexto del journey (sección "Resumen").
2. **Ayudar al usuario a fijar UNA hipótesis precisa** (máximo 2-3), llenando la plantilla
   de la sección "Hipótesis a congelar". Debe quedar 100% especificada ANTES de mirar
   ningún sorteo ≥ 3242: estadística + cortes de bins exactos + dirección esperada +
   horizonte + umbral. Sin ambigüedad (si no, se cae en el look-elsewhere que ya demostramos).
3. **Congelar**: escribir la hipótesis final + timestamp en la sección "REGISTRO CONGELADO"
   de este archivo y commitear ("preregistro: congelar hipotesis tendencias-kino").
   El commit es la prueba de que se fijó antes de ver los datos.
4. **Evaluar SOLO out-of-sample**: correr el test definido únicamente sobre sorteos
   ≥ 3242 (los que NO se usaron para generar la hipótesis). NO re-usar el histórico
   799–3241 para "confirmar" — eso es trampa (in-sample).
5. Si todavía no hay suficientes sorteos nuevos (ver "Horizonte"), dejar el test agendado
   y reportar "faltan N sorteos". El pipeline (`scrape-kino.yml`) ya acumula los nuevos.

**Regla de oro:** un efecto solo cuenta si (a) sobrevive a la dirección y umbral pre-fijados
y (b) aparece en datos que no se usaron para encontrarlo. Nada de mover los cortes después.

---

## Baseline CONGELADO (no tocar)

- **Datos usados para generar hipótesis:** sorteos KINO **799–3241** (2006-01-08 a 2026-06-17),
  2.443 sorteos. Fuente: `data/loteria_historial.csv`.
- **Out-of-sample (datos de evaluación):** sorteo **3242 en adelante** (≥ 2026-06-19).
  Al 2026-06-18 ninguno se ha sorteado aún → pre-registro legítimo.
- Estadísticas de la suma (referencia): media μ = 181,1 · σ = 18,6 · rango teórico 105–259
  (observado 117–239). Distribución exacta por combinatoria en `src/analytics/distribuciones_kino.py`.

---

## Resumen del journey (qué ya probamos y el veredicto)

La pregunta del usuario: ¿el historial de en qué **rango** (de suma, gap, σ, zonas) cae cada
sorteo permite predecir el rango del próximo? (No la combinación exacta — eso quedó claro que no.)

Tests hechos sobre 799–3241, todos con veredicto NULO o frágil:

| Test | Resultado | Veredicto |
|---|---|---|
| Frecuencia de cada número 1–25 | chi² = 14,1 (umbral 36,4) | sin sesgo de número |
| Suma por día de la semana | dom/mié/vie todos ≈ 12,9 (azar = 13,0); no persiste en split-half | sin efecto |
| Autocorrelación lag-1 de la suma | r = +0,03 | **sin memoria** (test más sensible, no depende de bins) |
| Gambler's fallacy (tras suma alta/baja) | siguiente ≈ media, sin compensación | sin compensación |
| Combinaciones exactas repetidas | 0 en 2.443 | repeticiones no ocurren |
| Matriz de transición de rangos (±1σ) | chi² = 11,07 → p ≈ 0,025 "significativo" | **FRÁGIL**: ver abajo |

**El hallazgo frágil (clave):** la matriz de transición con bins ±1σ dio p ≈ 0,025. PERO al
cambiar el corte de los bins, la significancia se evapora: 2-bins/mediana p=0,54; terciles
p=0,40; cuartiles p=0,12. Solo el ±1σ se "enciende" → artefacto de look-elsewhere (researcher
degrees of freedom), no señal real. Además la celda fuerte (ALTO→BAJO baja) apuntaba a leve
*pegajosidad*, dirección CONTRARIA a la "compensación" que intuye el usuario.

Conclusión a la fecha: **no hay tendencia explotable detectada in-sample.** La autocorrelación
continua (r≈0) y la fragilidad ante los bins lo respaldan. El pre-registro es el único camino
honesto que queda: fijar una hipótesis y probarla en datos futuros.

---

## Protocolo de pre-registración

1. **Una sola hipótesis** (o un set fijo y pequeño, con corrección de Bonferroni si son 2-3).
   Nada de probar muchas y quedarse con la que pega.
2. **Especificación completa ANTES de ver datos nuevos**: estadística exacta, cortes de bins
   exactos (valores numéricos), dirección esperada (signo), horizonte (nº de sorteos), umbral.
3. **Evaluación solo out-of-sample** (sorteos ≥ 3242).
4. **Umbral honesto**: p < 0,05 una cola en la dirección pre-fijada. Recomendado exigir además
   tamaño de efecto mínimo (p. ej. la celda objetivo se desvía ≥ X puntos de la base).
5. **Horizonte mínimo**: definir cuántos sorteos nuevos se necesitan para tener poder. Con efectos
   chicos, esto es del orden de 100+ sorteos (≈ 8-10 meses a 3/semana). Decidir mañana si se acepta
   esa espera o se elige una hipótesis con efecto grande detectable antes.

---

## Hipótesis a congelar (PLANTILLA — llenar mañana)

> Llenar cada campo con el usuario. Ejemplo pre-rellenado con la candidata del journey;
> el usuario puede reemplazarla por la suya.

- **H (en palabras):** _p. ej. "tras un sorteo de suma ALTA (>μ+σ), el siguiente tiende a NO ser BAJO"_
- **Estadística:** _suma de los 14 números / gap medio / σ de los números / reparto por zonas_
- **Bins exactos (valores):** _p. ej. BAJO < 162,5 · MEDIO 162,5–199,7 · ALTO > 199,7_
- **Celda/relación objetivo:** _p. ej. P(siguiente = BAJO | anterior = ALTO)_
- **Dirección esperada (signo):** _p. ej. < base (15,9%)_
- **Umbral:** _p ej. p < 0,05 una cola + desviación ≥ 3 puntos_
- **Horizonte:** _N sorteos out-of-sample antes de dictar veredicto_

Otras estadísticas disponibles para hipótesis (ya existen o son fáciles de derivar del CSV):
- **suma** (lista) — `src/analytics/distribuciones_kino.py`
- **gap** (distancia media entre números consecutivos del sorteo) — derivable
- **σ interna** (dispersión de los 14 números) — derivable
- **zonas** (cuántos números caen en 1-7 / 8-13 / 14-19 / 20-25, etc.) — derivable

---

## REGISTRO CONGELADO

> _(vacío — se llena al congelar mañana, con timestamp y commit)_

---

## Procedimiento técnico (reproducible)

El test base ya está validado; mañana se adapta a la hipótesis elegida. Esqueleto:

1. Leer `data/loteria_historial.csv`, columnas `KINO_n1..14`, ordenar por `sorteo`.
2. Calcular la estadística elegida por sorteo; clasificar en los bins pre-fijados.
3. Separar: histórico (≤3241) solo como referencia de la "base"; evaluación (≥3242).
4. Sobre los ≥3242: construir la relación objetivo (p. ej. matriz de transición) y testear
   contra la base con la dirección y umbral pre-fijados. Permutación para el p-valor empírico.
5. Reportar: tamaño de efecto, p, ¿cruza el umbral en la dirección correcta?, nº de sorteos usados.

Tests previos (para referencia de implementación) se corrieron inline en la sesión del 2026-06-18;
la matriz de transición y el chequeo de robustez por bins son el patrón a reutilizar.
