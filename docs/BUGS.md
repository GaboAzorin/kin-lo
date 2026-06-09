# Informe de Bugs — kino-loto

**Fecha del análisis:** 2026-06-09
**Alcance:** `src/` (scrapers, parsers, analytics, notificaciones), `scripts/` (PowerShell), `.github/workflows/`, `docs_src/` (frontend) y archivos de datos.

> ⚠️ Nota: este archivo vive en `docs/`, que GitHub Pages sirve públicamente.
> StatiCrypt solo encripta los HTML; este markdown es accesible sin contraseña.

---

## Resumen

| # | Severidad | Componente | Bug |
|---|-----------|------------|-----|
| 1 | ✅ Alta | jugadas (3 escritores) | Formato de `fecha_jugada` inconsistente: ISO vs dd-mm-yyyy |
| 2 | ✅ Alta | scraper_polla.py | Un sorteo puede perderse permanentemente ante respuesta vacía transitoria |
| 3 | 🔴 Alta | Privacidad | Los JSON de datos y `data/jugadas.json` son públicos pese a StatiCrypt; PAT en localStorage |
| 4 | ✅ Alta | scrape-kino.yml | Re-encriptación StatiCrypt en cada cron: commits ruidosos y pérdida de datos si falta el secret |
| 5 | ✅ Alta | actualizar_loto.ps1 | `git reset --hard` en reintentos destruye cambios locales ajenos al pipeline |
| 6 | ✅ Media | scraper_polla.py | No escribe header si el CSV existe pero está vacío |
| 7 | ✅ Media | metrics.py | Notificación Telegram puede mostrar el día de la semana de otro sorteo |
| 8 | ✅ Media | metrics.py | `_evaluar_y_registrar`: firma `-> int` y docstring no coinciden con lo que retorna |
| 9 | 🟡 Media | datos | Crecimiento sin límite de `suggestions_history.csv` y JSON derivados |
| 10 | ✅ Media | jugadas web + metrics.py | `computeAciertos` cliente deja jugadas sin `resultado_sorteo` y bloquea la re-evaluación del pipeline |
| 11 | ✅ Media | requirements / CLAUDE.md | Dependencia `scrapling` sin uso; documentación del scraper Kino desactualizada |
| 12 | ✅ Media | registrar_jugada.py | Entrada manual sin validación cuando no hay sugerencias (crash por `ValueError`) |
| 13 | ✅ Media | scraper_kinohistorico.py | Crash al final si el CSV no existe y no se descargó nada |
| 14 | ✅ Media | metrics.py | `historial_index.json` admite variantes con números incompletos |
| 15 | 🟡 Media | frontend | Código GitHub-API duplicado en 4 páginas con divergencias entre copias |
| 16 | ✅ Baja | docs / frontend | Hora del sorteo Loto inconsistente: countdown 21:00 vs documentación 22:15 |
| 17 | ✅ Baja | scrape-kino.yml | Comentario de timezone ignora el horario de verano chileno (UTC-3) |
| 18 | ✅ Baja | encrypt_html.ps1 / workflow | Salt y lista de páginas StatiCrypt duplicados en dos lugares |
| 19 | ✅ Baja | jugadas web | El chequeo de duplicados ignora `variantes` |
| 20 | ✅ Baja | suggestions.py | Shortlist MMR fijo en 400 limita `n_sugerencias > 400` en modo clásico |
| 21 | ✅ Baja | loto_parser_v3.py | `fromtimestamp` sin timezone: la fecha depende del reloj de la máquina |
| 22 | ✅ Baja | docs_src/index.html | Doble `margin-left:auto` en el header rompe la alineación del timestamp |

---

## Detalle y resolución

### 1. 🔴 Formato de `fecha_jugada` inconsistente entre los tres escritores — ✅ Resuelto 2026-06-09

**Ubicación:**
- `src/registrar_jugada.py:171` → escribe ISO: `date.today().isoformat()` → `"2026-06-09"`
- `docs_src/index.html:733`, `docs_src/loto/index.html:645`, `docs_src/kino/index.html:637` → escriben `new Date().toLocaleDateString('es-CL')` → `"09-06-2026"` (y el padding de ceros depende del motor JS)
- `docs_src/jugadas/index.html:555` → escribe `dd-mm-yyyy` manual

**Problema:** la página Mis Jugadas **asume** `dd-mm-yyyy`:
- `docs_src/jugadas/index.html:376` — el sort hace `fecha_jugada.split('-').reverse().join('')`; con una fecha ISO produce una clave invertida y el orden queda mal.
- `docs_src/jugadas/index.html:528` — al editar hace `const [d, m, y] = j.fecha_jugada.split('-')`; con ISO interpreta el año como día y **corrompe la fecha al guardar**.

Hoy `data/jugadas.json` solo tiene fechas dd-mm-yyyy porque las últimas jugadas se registraron desde la web, pero el bug está latente: la próxima jugada registrada con `registrar_jugada.py` lo gatilla.

**Resolución:**
1. Normalizar **todo a ISO (`yyyy-mm-dd`)**: es ordenable lexicográficamente y es lo que produce `<input type="date">`.
2. Cambiar los tres escritores web a `new Date().toISOString().slice(0,10)` (o construir la fecha local explícitamente para no desfasarse por UTC).
3. En `jugadas/index.html`, guardar directamente el valor del input (`f-fecha`, ya ISO) sin invertirlo, y en `openFormEdit`/sort detectar el formato legado: si `fecha[4] === '-'` es ISO, si no, convertir dd-mm-yyyy → ISO una sola vez.
4. Script de migración único sobre `data/jugadas.json` que convierta las fechas existentes a ISO.

---

### 2. 🔴 scraper_polla.py puede perder un sorteo permanentemente — ✅ Resuelto 2026-06-09

**Ubicación:** `src/scrapers/scraper_polla.py:282-289`

```python
if not json_data or not json_data.get("results"):
    ts = json_data.get("drawDate") if json_data else None
    if ts and datetime.fromtimestamp(ts / 1000) > datetime.now():
        break
    current_id += 1        # ← avanza el ID aunque el fallo sea transitorio
    consec_errors += 1
    continue
```

**Problema:** si la API devuelve `results` vacío de forma transitoria para un sorteo que sí existe (p. ej. publicado a medias), el scraper avanza `current_id`. Si un sorteo posterior se guarda en el mismo run, `get_start_id()` (que parte de `max+1`) **nunca volverá a intentar el saltado** → hueco permanente en el CSV. Hoy los CSV no tienen huecos, pero el riesgo existe en cada corrida cercana a la hora del sorteo.

**Resolución:**
- No avanzar `current_id` cuando la respuesta está vacía sin `drawDate` futuro; reintentar el mismo ID hasta `MAX_CONSECUTIVE_ERRORS` y abortar el run sin avanzar.
- Alternativa más robusta: que `get_start_id()` busque el primer hueco (`min` faltante) en lugar de `max+1`, igual que hace el scraper de kinohistorico con su set `existing`.

---

### 3. 🔴 Los datos quedan públicos pese a StatiCrypt + PAT en localStorage

**Ubicación:** arquitectura general (`docs/data/*.json`, `data/jugadas.json`, `getToken()` en las 4 páginas).

**Problema:**
1. StatiCrypt encripta **solo los HTML**. Todos los `docs/data/*.json` (métricas, historial completo, sugerencias, rendimiento, pozos) se sirven sin contraseña en GitHub Pages.
2. `data/jugadas.json` —tus jugadas personales con fechas y números— es legible por cualquiera vía el repo público o `api.github.com/repos/GaboAzorin/kin-lo/contents/data/jugadas.json` (el frontend lo lee así, incluso sin token).
3. El PAT de GitHub (con permiso de escritura sobre el repo) se guarda en `localStorage` apenas ofuscado en base64. Cualquiera con acceso al navegador puede extraerlo, y los JSON se inyectan con `innerHTML` sin sanitizar (riesgo bajo porque los datos vienen del propio repo, pero la superficie existe).

**Resolución:**
- Asumir y documentar que la "protección" actual es solo cosmética para los HTML, **o** mover el sitio a un hosting con auth real (Cloudflare Access, Netlify password) si la privacidad importa.
- Para `jugadas.json`: usar un PAT *fine-grained* limitado a `contents:write` de este único repo y con expiración corta (minimiza el daño si se filtra).
- Mover los datos personales fuera del repo público (p. ej. un Gist secreto) si se quiere privacidad real.

---

### 4. 🔴 scrape-kino.yml: re-encriptación StatiCrypt en cada cron — ✅ Resuelto 2026-06-09

**Ubicación:** `.github/workflows/scrape-kino.yml:60-69`

**Problema:**
1. La salida de StatiCrypt no es determinista (IV aleatorio), así que **cada corrida del cron re-commitea los 5 HTML aunque nada haya cambiado** → historial lleno de diffs binarios de ~todo el HTML y redeploys de Pages innecesarios.
2. Si el secret `STATICRYPT_PASSWORD` está vacío o se borra, el step falla **después** de scrapear y calcular métricas pero **antes** del commit → todo el trabajo del run se pierde (el CSV/JSON generados no se commitean). El sorteo se recupera en el siguiente run gracias a la ventana de 26, pero el pending de sugerencias generado se descarta.

**Resolución:**
- Encriptar solo cuando `docs_src/` cambió: condicionar el step con `git diff --quiet HEAD -- docs_src/` o un hash guardado.
- Agregar guard al inicio del step: `if [ -z "$STATICRYPT_PASSWORD" ]; then echo "secret faltante"; exit 1; fi` **antes** de los pasos de scraping (o mover el step de encriptación antes de metrics, o darle `continue-on-error: true` y excluir los HTML del commit en ese caso).

---

### 5. 🔴 actualizar_loto.ps1: `git reset --hard` destruye trabajo local — ✅ Resuelto 2026-06-09

**Ubicación:** `scripts/actualizar_loto.ps1:119`

**Problema:** en el bucle de reintentos de push, `git reset --hard origin/main` borra **todo** cambio local no commiteado, no solo los artefactos del pipeline. Si en el paso 1 se restauraron cambios del stash (línea 79) y el push falla, esos cambios del usuario se pierden sin aviso. Además:
- `git add $archivos` (línea 97) falla con "pathspec did not match" si alguno de los 9 archivos aún no existe, y el exit code no se chequea.
- `git status --porcelain` (línea 98) mira el repo completo: archivos sucios ajenos al pipeline hacen pasar el check, y el `git commit` posterior puede fallar sin nada staged (tampoco se chequea).

**Resolución:**
- Antes del `reset --hard`, verificar que el árbol esté limpio fuera de `$archivos`; si no, abortar con mensaje. O usar `git checkout origin/main -- <archivos>` para descartar solo los artefactos del pipeline.
- Chequear `$LASTEXITCODE` después de `git add` y `git commit`.
- Restringir el check de cambios a los archivos del pipeline: `git status --porcelain -- $archivos`.

---

### 6. 🟡 scraper_polla.py no escribe header sobre CSV vacío — ✅ Resuelto 2026-06-09

**Ubicación:** `src/scrapers/scraper_polla.py:135`

**Problema:** `file_exists = CSV_OUT.exists()` — si el archivo existe con 0 bytes (creación fallida previa, truncado), se agregan filas sin header y pandas leerá la primera fila de datos como header. `scraper_loteria.py:156` ya lo resuelve con `st_size > 10`.

**Resolución:** copiar el patrón: `file_exists = CSV_OUT.exists() and CSV_OUT.stat().st_size > 10`.

---

### 7. 🟡 Telegram: día de la semana de un sorteo distinto al notificado — ✅ Resuelto 2026-06-09

**Ubicación:** `src/analytics/metrics.py:775` (`_enviar_notificaciones`)

**Problema:** el mensaje "Nuevo sorteo" usa `sorteo_n`/`resultado`/`fecha` de `eval_data` (el **primer** sorteo posterior al pending), pero `dia` viene de `ultimo` (el **último** sorteo del CSV). Si entraron 2+ sorteos desde la última corrida, el día de la semana mostrado corresponde a otro sorteo.

**Resolución:** derivar el día desde `eval_data["fecha"]` (`datetime.strptime(fecha[:10], "%Y-%m-%d").strftime("%A")` + `_DIA_ES`), no desde `ultimo`.

---

### 8. 🟡 `_evaluar_y_registrar`: contrato de retorno incoherente — ✅ Resuelto 2026-06-09

**Ubicación:** `src/analytics/metrics.py:191-275`

**Problema:** la firma declara `-> int` y el docstring dice "retorna cuántas se agregaron", pero la función retorna `dict | None` (el dict con `sorteo_n`, `per_rango`, etc. que consume `_enviar_notificaciones`). Funciona, pero el contrato miente y cualquier refactor guiado por la firma lo romperá.

**Resolución:** cambiar la anotación a `-> dict | None` y actualizar el docstring.

---

### 9. 🟡 Crecimiento sin límite de historial de sugerencias

**Ubicación:** `data/suggestions_history.csv` (ya 747 KB / 12.163 filas en ~3 semanas), `docs/data/suggestions_detail.json` (98 KB), `docs/data/historial_index.json` (543 KB).

**Problema:** cada sorteo agrega ~3.000 filas al CSV (500 combos × 6 rangos). En un año serán ~900k filas (~55 MB): `pd.read_csv` completo en cada corrida del pipeline, y el frontend descarga `suggestions_detail.json` entero. `historial_index.json` ya pesa 543 KB y crece con cada sorteo.

**Resolución:**
- Guardar en el CSV solo agregados por rango (avg/max/top-3 combos) en vez de las 500 filas crudas, o rotar el CSV (mantener últimos N sorteos + un resumen acumulado).
- Limitar `suggestions_detail.json` a los últimos ~30 sorteos.
- Servir `historial_index.json` separado por juego o comprimido (Pages ya hace gzip, pero el parse en el cliente igual cuesta).

---

### 10. 🟡 `computeAciertos` cliente bloquea la evaluación canónica del pipeline — ✅ Resuelto 2026-06-09

**Ubicación:** `docs_src/jugadas/index.html:473-484` + `src/analytics/metrics.py:303`

**Problema:** al crear/editar una jugada de un sorteo ya sorteado, la web calcula `aciertos` (dict) con `historial_index.json`. Luego `_evaluar_jugadas` salta toda jugada cuyo `aciertos` ya sea dict → esa jugada **nunca** recibe `resultado_sorteo` del pipeline (la tabla no podrá mostrar los números sorteados) y un cálculo hecho con un índice desactualizado queda congelado para siempre. Además se pierde la notificación Telegram de esa jugada.

**Resolución:** en `_evaluar_jugadas`, re-evaluar también las jugadas con `aciertos` dict pero **sin** `resultado_sorteo`; o que el cliente guarde `aciertos: null` y deje la evaluación solo al pipeline (más simple y una sola fuente de verdad).

---

### 11. 🟡 Dependencia `scrapling` muerta y documentación desactualizada — ✅ Resuelto 2026-06-09

**Ubicación:** `requirements.txt:6`, `CLAUDE.md` (sección "Scraper loteria.cl")

**Problema:** `scraper_loteria.py` ya no usa Scrapling: consume la API `https://rckino.loteria.cl/api/sorteos` con `urllib`. Sin embargo `requirements.txt` instala `scrapling[fetchers]` en cada corrida del cron (dependencia pesada, riesgo de fallo de instalación inútil) y CLAUDE.md describe el mecanismo viejo (`Fetcher`/`DynamicFetcher`, URL `loteria.cl/resultados/resultado-completo`).

**Resolución:** eliminar `scrapling` de requirements y actualizar CLAUDE.md con la API real (`rckino.loteria.cl/api/sorteos`, ventana de 26 sorteos, sin parser HTML).

---

### 12. 🟡 registrar_jugada.py: entrada manual sin validación — ✅ Resuelto 2026-06-09

**Ubicación:** `src/registrar_jugada.py:148-154`

**Problema:** en el camino "no hay sugerencias", los números se parsean sin `try` (un texto no numérico revienta con `ValueError`), y no se valida cantidad, rango 1–N ni duplicados — a diferencia del camino `manual` de `_elegir_combo` que sí valida (líneas 79-92). También `sorteo = int(input(...))` en la línea 140 puede crashear.

**Resolución:** extraer la validación de `_elegir_combo` a una función `_leer_numeros(pick, num_range)` y usarla en ambos caminos; envolver el `int(input())` del sorteo en un loop con `try`.

---

### 13. 🟡 scraper_kinohistorico.py: crash con CSV inexistente y cero descargas — ✅ Resuelto 2026-06-09

**Ubicación:** `src/scrapers/scraper_kinohistorico.py:238-239`

**Problema:** si el CSV no existe y la descarga no produjo filas (API caída, `--desde` muy alto), el print final hace `int(df["sorteo"].min())` sobre un DataFrame vacío → `ValueError: cannot convert float NaN to integer`. Cosmético pero hace fallar el run (y en el workflow está con `continue-on-error`, así que pasa desapercibido).

**Resolución:** guardar el resumen final con `if len(df): ... else: print("CSV vacío")`.

---

### 14. 🟡 `historial_index.json` admite variantes con números incompletos — ✅ Resuelto 2026-06-09

**Ubicación:** `src/analytics/metrics.py:737-739` (`_exportar_historial_index`)

**Problema:** `nums = sorted(int(row[c]) for c in cols if pd.notna(row.get(c)))` incluye la variante aunque tenga menos números que el pick (fila parcialmente corrupta). El frontend (`computeAciertos`) calcularía aciertos contra una lista incompleta sin error visible.

**Resolución:** exigir la cantidad exacta: `if len(nums) == len(cols): entry[variante] = nums`.

---

### 15. 🟡 Código GitHub-API cuadruplicado y divergente

**Ubicación:** `docs_src/index.html:661-747`, `docs_src/loto/index.html:580-658`, `docs_src/kino/index.html` (equivalente), `docs_src/jugadas/index.html:238-282`

**Problema:** `getToken`, `ghGetFile`, `ghPutFile` y `handleJugar` están copiados en 4 páginas y **ya divergieron**: el `ghGetFile` del home/loto/kino lanza error si no hay token, el de jugadas hace fetch anónimo; el formato de `fecha_jugada` también difiere (bug #1). Cada fix futuro debe replicarse a mano en 4 lugares.

**Resolución:** extraer a `docs_src/js/gh-api.js` compartido e incluirlo con `<script src>` en las 4 páginas (StatiCrypt encripta el HTML; el JS externo quedaría visible, igual que hoy lo está dentro de los HTML fuente del repo — no cambia la exposición real).

---

### 16. 🟢 Hora del sorteo Loto inconsistente (21:00 vs 22:15) — ✅ Resuelto 2026-06-09

**Ubicación:** `docs_src/index.html:352-355` (countdown a las 21:00), `CLAUDE.md` y `scripts/actualizar_loto.ps1:8` ("~22:15 CLT")

**Problema:** el contador de la home apunta a las 21:00 (coincide con el timestamp `21:00:00` que registra polla.cl en el CSV), pero la documentación dice 22:15. Una de las dos está mal; si el sorteo real es ~21:00, el comentario del script induce a correr el pipeline antes de tiempo o confunde.

**Resolución:** verificar la hora real del sorteo en polla.cl y unificar countdown + documentación.

---

### 17. 🟢 Comentario de timezone del cron Kino ignora el horario de verano — ✅ Resuelto 2026-06-09

**Ubicación:** `.github/workflows/scrape-kino.yml:3-6`

**Problema:** el comentario asume CLT = UTC-4 fijo. En verano chileno (sep–abr) Chile está en UTC-3, así que `59 3 UTC` son las 00:59 locales, no las 23:59. El job igual corre después del sorteo (sin impacto funcional), pero el comentario documenta mal el comportamiento real.

**Resolución:** corregir el comentario indicando ambos casos (23:59 CLT invierno / 00:59 CLST verano).

---

### 18. 🟢 Configuración StatiCrypt duplicada — ✅ Resuelto 2026-06-09

**Ubicación:** `scripts/encrypt_html.ps1:19-28` y `.github/workflows/scrape-kino.yml:64-69`

**Problema:** el salt y la lista de 5 páginas están hardcodeados en dos lugares. Agregar una página nueva o cambiar el salt en uno solo de los dos rompe silenciosamente el otro (con salts distintos, la contraseña recordada por el navegador deja de funcionar entre páginas).

**Resolución:** que el workflow ejecute un único script compartido (versión bash del ps1, o `node` script) que lea la lista de páginas de un solo lugar (p. ej. un `staticrypt-pages.txt`).

---

### 19. 🟢 Chequeo de duplicados de jugadas ignora variantes — ✅ Resuelto 2026-06-09

**Ubicación:** `docs_src/jugadas/index.html:589-592`, `docs_src/index.html:731`, `src/...` (mismo criterio)

**Problema:** la clave de duplicado es `juego + sorteo + números`. Si jugaste el mismo cartón dos veces (una solo Loto, otra Loto+Recargado), la segunda se descarta silenciosamente (`if (!dup)` no avisa).

**Resolución:** incluir `variantes` en la clave o, mejor, avisar al usuario ("ya existe esta jugada") en vez de ignorar en silencio.

---

### 20. 🟢 Shortlist MMR fijo en 400 limita pedidos grandes — ✅ Resuelto 2026-06-09

**Ubicación:** `src/analytics/suggestions.py:225` (`shortlist = cands[:400]`)

**Problema:** en modo clásico (`n_display=None`, usado por `backtest.py`), `_seleccionar_diversas` nunca puede devolver más de 400 combos aunque se pidan más (`while ... len(elegidos) < len(shortlist)`). Hoy el backtest usa `n=10` y producción usa `n_display=3`, así que es latente, pero un `--n 500` en backtest devolvería 400 sin aviso.

**Resolución:** dimensionar el shortlist según lo pedido: `shortlist = cands[:max(400, n * 2)]`, o documentar el límite en el docstring.

---

### 21. 🟢 `fromtimestamp` sin timezone en el parser de Loto — ✅ Resuelto 2026-06-09

**Ubicación:** `src/parsers/loto_parser_v3.py:32` (también `scraper_polla.py:284`)

**Problema:** `datetime.fromtimestamp(ts / 1000)` usa el timezone local de la máquina. Corriendo el scraper desde otra zona horaria (viaje, VPS), la fecha del sorteo puede desplazarse un día respecto al historial existente.

**Resolución:** fijar la zona: `datetime.fromtimestamp(ts / 1000, tz=ZoneInfo("America/Santiago"))`.

---

### 22. 🟢 Doble `margin-left:auto` en el header de la home — ✅ Resuelto 2026-06-09

**Ubicación:** `docs_src/index.html:30` (CSS de `header span`) y `:220` (link "Mis jugadas" con `margin-left:auto` inline)

**Problema:** ambos elementos compiten por el margen automático: el espacio libre se reparte entre los dos y el timestamp `#last-update` queda centrado-flotante en vez de pegado a la derecha junto al link.

**Resolución:** dejar `margin-left:auto` solo en el primero de los dos elementos del extremo derecho (el span) y quitar el inline del link.

---

## Orden sugerido de resolución

1. **#1 (fechas)** — es el que corrompe datos al usarlo; arreglar antes de la próxima jugada vía `registrar_jugada.py`.
2. **#5 y #2** — protegen la integridad del repo y del historial.
3. **#4 y #11** — estabilizan el cron de Kino.
4. **#10, #7, #6, #12, #13, #14** — robustez del pipeline.
5. **#3** — decisión de arquitectura (privacidad): definir si se acepta el modelo actual o se migra.
6. **#9 y #15** — deuda de mantenimiento; atacar antes de que el CSV crezca más.
7. Resto (🟢) — oportunísticos.
