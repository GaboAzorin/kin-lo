# Proyectar el bin de suma del sorteo siguiente — red neuronal vs. línea base

**Fecha:** 2026-06-22
**Código:** `src/analytics/predecir_bin_suma.py`
**Datos:** `data/loteria_historial.csv` (Kino, 2.435 muestras útiles), `data/polla_historial.csv` (Loto, 1.629)

## Qué se construyó

Un pipeline ML/DL que, a partir de la suma de cada sorteo, intenta predecir el
**bin (rango de suma)** al que pertenecerá el sorteo siguiente. Incluye:

- **Modelos:** regresión logística multinomial (sklearn), red **MLP** y red
  **LSTM** (PyTorch), todos sobre features de los últimos K=10 sorteos.
- **Líneas base:** *modal* (siempre el bin más frecuente), *marginal esperada*
  (Σ pᵢ²) y *persistencia* (mismo bin que el sorteo anterior).
- **Split temporal** 80/20 (entrena pasado → evalúa futuro, sin fuga).
- **Control de permutación:** se baraja el orden temporal del target y se
  reentrena el MLP. Si la accuracy no cae, el modelo nunca usó señal temporal.

## Resultados (accuracy en test)

| | Kino (5 bins quantile) | Loto (5 bins quantile) | Kino (7 bins fijos) |
|---|---|---|---|
| Modal | 0,209 | 0,196 | 0,355 |
| Marginal esperada | 0,201 | 0,200 | 0,255 |
| Persistencia | 0,170 | **0,239** | 0,244 |
| Logística | 0,197 | 0,178 | 0,380 |
| MLP | **0,216** | 0,184 | 0,329 |
| LSTM | 0,187 | 0,181 | 0,357 |
| **Control permutación** | 0,181 | 0,184 | 0,285 |

## Veredicto: NULO en los tres casos

En ningún escenario el mejor modelo supera a la mejor línea base más allá del
ruido binomial (±1σ ≈ 0,02). En Loto, la propia *persistencia* (0,239) le gana a
todas las redes — coincidencia del azar, no señal.

Las redes hacen exactamente lo previsto: **convergen a la distribución marginal**.
Sus probabilidades proyectadas para el próximo sorteo son indistinguibles del
histograma histórico de bins. Con bins fijos la accuracy "sube" a ~0,38 solo
porque el bin central acumula ~35% de los sorteos; el modelo gana repitiendo la
marginal, no leyendo el pasado.

## Por qué era inevitable

La suma de un sorteo es una muestra sin reemplazo de un pool fijo, **independiente**
del sorteo anterior. Un aproximador de funciones solo extrae señal existente; aquí
no la hay. Esto reconfirma el cierre del experimento de tendencias Kino
(`analysis/preregistro-tendencias-kino.md`): el muro es el **poder estadístico**.
La autocorrelación lag-1 de la suma es r≈0,03 — ni significativa in-sample —, así
que ninguna arquitectura puede inventar memoria donde el proceso no la tiene.

**Lo único honesto que se puede proyectar del próximo sorteo es la marginal:** el
bin central es el más probable, con la misma probabilidad de siempre.

## Reproducir

```bash
python src/analytics/predecir_bin_suma.py --game kino --bins 5 --binning quantile
python src/analytics/predecir_bin_suma.py --game loto --bins 5 --binning quantile
python src/analytics/predecir_bin_suma.py --game kino --bins 7 --binning fixed
```

JSON con métricas y proyección: `analysis/predecir_bin_suma_{kino,loto}.json`.
