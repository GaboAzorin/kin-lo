# Brief de diseño para Google Stitch — kino-loto

> Objetivo: obtener de Stitch un **lenguaje visual** (look & feel) moderno, con
> glassmorphism y microinteracciones, para reaplicarlo sobre el sitio existente.
> **No buscamos que Stitch reconstruya la funcionalidad** — el HTML/JS ya existe y
> engancha por IDs concretos. Stitch entrega el referente visual; la integración
> es un cambio de CSS sobre el DOM actual.

---

## 0. Cómo usar este documento

1. En Stitch, **empieza una sesión nueva** y pega primero el bloque **"Contexto
   global"** (sección 1). Esto define el sistema de diseño una sola vez.
2. Luego, para cada pantalla, pega el prompt correspondiente (sección 3). Genera,
   itera en el chat de Stitch hasta que te guste.
3. Cuando estés conforme, exporta vía **MCP** y avísame: yo extraigo tokens
   (colores, sombras, blur, radios, tipografía, transiciones) y los reaplico al
   CSS de cada página **conservando los IDs y la estructura del DOM**.
4. Pídele a Stitch que **no invente datos**: que use exactamente los textos,
   números y etiquetas que aparecen en cada prompt. Así el diseño calza con lo real.

---

## 1. Contexto global (pegar primero en Stitch)

```
Estoy rediseñando el look & feel de "kino-loto", un sitio estático de análisis
estadístico de la lotería de Chile (juegos Loto y Kino). Es un sitio de datos:
muestra resultados de sorteos, pozos estimados, cuentas regresivas al próximo
sorteo, y combinaciones de números sugeridas por un algoritmo. El usuario es una
sola persona (uso personal/nicho), en español de Chile, mayormente desktop pero
debe verse impecable en mobile.

DIRECCIÓN VISUAL que quiero:
- Estética moderna, dark, premium. Glassmorphism real: superficies de vidrio
  esmerilado (backdrop blur) con bordes sutiles iluminados y profundidad por capas.
- Fondo oscuro con una "aurora" sutil: gradientes suaves de color de fondo,
  desenfocados, que se vean a través del vidrio de las tarjetas. Que el efecto
  glass tenga algo que refractar; nada de glass sobre negro plano.
- Microinteracciones preciosas: hover con elevación y brillo, transiciones suaves
  (200–300ms, easing tipo ease-out), estados de foco visibles, animación de
  entrada de las tarjetas, números que "cuentan" en los contadores, pills que
  cambian con transición fluida.
- Tipografía limpia, geométrica, con tracking negativo en titulares. Jerarquía
  clara. Buen uso de números tabulares para datos.
- Tienes libertad para proponer una paleta nueva y moderna desde cero (no estoy
  casado con los colores actuales). Pero el sitio tiene DOS marcas/juegos que deben
  distinguirse por color de forma consistente en todas las pantallas: un acento
  para "Loto" y otro para "Kino". Elige dos acentos que se vean premium sobre dark
  y que contrasten bien entre sí. Define también un color de "acierto/positivo"
  (verde) y uno de "alerta/error".

SISTEMA DE DISEÑO que necesito que definas y mantengas idéntico en todas las
pantallas:
- Paleta: fondo base, capas de superficie glass, bordes, texto primario, texto
  atenuado, acento Loto, acento Kino, positivo, error.
- Tipografía: familia, escalas (h1, h2, título de tarjeta, cuerpo, micro-label).
- Radios, sombras, nivel de blur del glass, grosor y tratamiento de bordes.
- Componente "bolita de número": un círculo pequeño con un número de lotería
  dentro (1–41 para Loto, 1–25 para Kino). Aparece en grupos. Define su versión
  Loto y su versión Kino, y una versión chica para listas.
- Componente "pill/chip" seleccionable (para filtros de rango), con estado normal,
  hover, activo y un estado "destacado" (marcado con ★).
- Componente "tarjeta glass" base.
- Botón primario (variante Loto y variante Kino) y botón secundario/fantasma.
- Badge/etiqueta de marca ("Polla.cl" / "Loteria.cl").

ENTREGABLE: quiero el sistema de diseño y las pantallas como referente visual de
alta fidelidad. Mantén consistencia absoluta del sistema entre pantallas. Usa los
textos y datos exactos que te doy en cada pantalla; no inventes contenido.
```

---

## 2. Inventario de componentes (para que tú y Stitch hablen el mismo idioma)

| Componente | Dónde aparece | Notas |
|---|---|---|
| Header | todas | Logo (círculo tipo bolita), título "kino-loto", sello "Datos / Cargado", links de navegación |
| Countdown card | Home | Cuenta regresiva DD:HH:MM:SS al próximo sorteo, con fecha. Una por juego. La más próxima se resalta. |
| Pozo list | Home, Loto, Kino | Filas nombre→monto ($ MM), con un total |
| Bolita de número | todas | Círculo con número. Variantes Loto/Kino, tamaño normal y chico |
| Sug row | Home, Loto, Kino | Fila: índice #N + bolitas + suma Σ con color semántico + botón 🎟 "jugar" |
| Range pills | Home, Loto, Kino, Sugerencias | Filtros: Últ.50/100/250/500/1000/Todos; uno marcado ★ "mejor grupo" |
| Heatmap | Loto, Kino | Grilla de frecuencia de los números |
| Hot/Cold list | Loto, Kino | Listas con barras de progreso (números calientes/fríos) |
| Tab bar | Loto, Kino, Sugerencias, Jugadas | Cambia entre variantes del juego |
| Backtest metrics | Sugerencias | Tarjetas de métricas de rendimiento del algoritmo |
| Tabla de resultados | Loto, Kino, Sugerencias, Jugadas | Tablas de datos con encabezados |
| Formulario | Jugadas, Ingresar | Inputs, radios, checks, grilla de selección de números, botones |
| Disclaimer / info-box | varias | Avisos sutiles, no intrusivos |

---

## 3. Prompts por pantalla

Cada prompt asume que ya pegaste el Contexto global (sección 1) en la misma sesión.

### 3.1 — Home (`/`)

```
Pantalla: HOME del sitio kino-loto. Aplica el sistema de diseño ya definido.

Estructura de arriba a abajo:
1. Header: logo circular tipo bolita de lotería + "kino-loto". A la derecha, un
   sello en dos líneas: "Datos: 15-06-2026" y "Cargado: 17-06-2026 09:42". Y dos
   links de navegación: "Mis jugadas" y "Ingresar sorteo".
2. Subtítulo: "Análisis estadístico de la Lotería de Chile".
3. Fila de DOS countdown cards lado a lado (en mobile, apiladas):
   - Card Loto (acento Loto): etiqueta "Polla.cl", título "Próximo Loto",
     dígitos grandes "02 : 14 : 35 : 09" con labels "días/horas/min/seg" debajo,
     y fecha "martes 17 de junio a las 21:00 CLT". Esta card está RESALTADA por ser
     el sorteo más próximo (borde/halo de acento).
   - Card Kino (acento Kino): etiqueta "Loteria.cl", título "Próximo Kino",
     mismos dígitos, fecha "miércoles 18 de junio a las 22:30 CLT".
4. Dos tarjetas glass grandes lado a lado (apiladas en mobile), una Loto y una Kino,
   cada una con:
   - Header: badge de marca ("Polla.cl" / "Loteria.cl") + título grande ("Loto" / "Kino").
   - Bloque "Pozo estimado próximo sorteo": filas tipo "Loto 1.500 MM",
     "Recargado 300 MM", con un total "$1.800 MM" destacado.
   - Bloque "Último sorteo": "Sorteo #3241, lanzado el 15-06-2026" + una fila de
     bolitas de números (Loto: 6 bolitas como 3, 11, 24, 28, 33, 40 / Kino: 14 bolitas).
   - Bloque "Combinaciones sugeridas para el sorteo #3242": una fila de pills de
     rango (Últ.50, Últ.100, Últ.250, Últ.500, Todos — uno marcado con ★), y debajo
     3 filas de sugerencia: "#1" + bolitas + "Σ 142" (la suma con color según si está
     en zona central) + un botón ícono 🎟 para registrar la jugada.
   - Footer de tarjeta: "3241 sorteos registrados" + botón primario "Análisis completo →".

Quiero que el fondo aurora se note detrás de las tarjetas glass. Microinteracción:
las countdown cards laten suavemente, y las tarjetas se elevan al hover.
```

### 3.2 — Kino (`/kino/`)  · (Loto es idéntica, cambia acento y nombres)

```
Pantalla: detalle KINO de kino-loto. Aplica el sistema de diseño. Acento Kino.

Secciones, cada una con su título de sección en micro-label mayúscula:
1. Header igual que Home + h1 "Kino".
2. "Último sorteo": tarjeta glass con meta ("Sorteo #3241 · 15-06-2026 · miércoles")
   y 14 bolitas de número grandes.
3. "Combinaciones sugeridas para el #3242": pills de rango + lista de filas de
   sugerencia (índice + 14 bolitas + suma Σ + botón 🎟). Igual que en Home.
4. "Frecuencia de números" con una tab-bar arriba: pestañas "Kino / ReKino /
   RequeteKino". Debajo, un HEATMAP: grilla de los números 1–25 coloreados por
   frecuencia (más cálido = más frecuente), tipo mapa de calor.
5. Dos columnas: "Números calientes" y "Números fríos", cada una una lista de
   filas: número en bolita + una barra de progreso horizontal + el conteo. Calientes
   con barra roja/cálida, fríos con barra azul/fría.
6. "Mayor sequía" (gap): tarjeta con filas número + barra + cantidad de sorteos sin salir.
7. Una tabla de datos (resultados históricos) con encabezados: Sorteo, Fecha,
   números. Cabecera sticky, filas con hover.

Mantén el heatmap y las barras elegantes y legibles sobre dark.
```

### 3.3 — Loto (`/loto/`)

```
Igual que la pantalla Kino pero con acento Loto, h1 "Loto", la tab-bar con pestañas
"Loto / Recargado / Revancha / Desquite", el heatmap sobre números 1–41, y 6 bolitas
por sorteo en vez de 14. Mismo sistema de diseño y mismos componentes.
```

### 3.4 — Sugerencias (`/sugerencias/`)

```
Pantalla: SUGERENCIAS de kino-loto. Aplica el sistema de diseño.

1. Header + h1 "Sugerencias".
2. Un disclaimer sutil arriba (caja info discreta): aviso de que son combinaciones
   generadas por un algoritmo, sin garantía.
3. Tab-bar para elegir juego (Loto / Kino).
4. "Backtest / Rendimiento": dos o tres tarjetas glass de métricas, cada una con un
   label, valores grandes y una nota chica. Ej: "Aciertos promedio", "Mejor rango",
   "Sorteos evaluados". Que se vean como tarjetas de dashboard premium.
5. Tabla "Rendimiento por rango": encabezados centrados con métricas por cada rango
   (Últ.50…Todos).
6. Secciones por rango: cada rango es una "rango-section" con header (nombre del
   rango + badge de ranking) que contiene tarjetas colapsables de sorteo
   ("sorteo-card" con header clickeable que expande el cuerpo), mostrando la
   combinación sugerida (bolitas) y cuántos aciertos tuvo, con un rank-badge.
6b. Estado vacío elegante cuando un rango no tiene datos aún.

Las tarjetas de métricas son el héroe visual de esta pantalla; hazlas lucir.
```

### 3.5 — Jugadas (`/jugadas/`)

```
Pantalla: MIS JUGADAS de kino-loto. Aplica el sistema de diseño.

1. Header + h1 "Mis jugadas".
2. Fila de "stat-cards": 6 tarjetas chicas glass, cada una con un valor grande y un
   label ("Jugadas totales", "Aciertos máx", etc.).
3. Botón primario "＋ Agregar jugada" que despliega un PANEL DE FORMULARIO (glass):
   - Selector de juego con radio-tabs (Loto / Kino).
   - Inputs: sorteo (número), fecha.
   - Checks de variantes (Recargado/Revancha… o ReKino/RequeteKino).
   - Selector de números con hint.
   - Acciones: botón "Cancelar" (secundario) y "Registrar" (primario, deshabilitado
     hasta completar).
4. Tabla de jugadas registradas: encabezados (Fecha, Juego, Sorteo, Números,
   Variantes, Aciertos, acción editar ✏). Las celdas de números muestran bolitas
   chicas. Botón editar por fila.

El formulario debe sentirse fluido: aparición animada del panel, foco claro en
inputs, estados disabled bien resueltos.
```

### 3.6 — Ingresar (`/ingresar/`)

```
Pantalla: INGRESAR RESULTADO de un sorteo, kino-loto. Aplica el sistema de diseño.

1. Header + h1 "Ingresar sorteo".
2. Un aviso "token-warn" (oculto por defecto): banner de alerta sutil cuando falta
   configurar el token.
3. Panel glass con formulario:
   - Inputs: sorteo (número) y fecha.
   - "grid-label" + una GRILLA grande para seleccionar/escribir los números del
     sorteo (botones/celdas numeradas que se marcan al seleccionar). Este selector
     de números en grilla es el componente protagónico: hazlo satisfactorio de usar,
     con feedback claro al marcar (microinteracción de selección).
   - Una línea de mensaje de estado.
   - Acciones: "Limpiar" (secundario) y "Enviar resultado" (primario, deshabilitado
     hasta válido).

Foco en que la grilla de selección de números sea bella y táctil.
```

---

## 4. Después de Stitch — qué necesito para integrar

Cuando exportes por MCP, lo ideal es que yo pueda leer:
- Los **tokens del sistema de diseño** (paleta, tipografía, radios, sombras, blur).
- El **CSS de cada componente** (bolita, pill, tarjeta glass, botón, countdown, etc.).
- Las **animaciones/transiciones** (keyframes, curvas, duraciones).

Con eso reescribo los `:root { --vars }` y las reglas de cada página en `docs_src/`,
**sin tocar los IDs ni la estructura del DOM ni el JS**, y luego compilo a `docs/`
con `scripts/encrypt_html.ps1` (StatiCrypt). Así la integración es un swap de
estilos, no un rewrite.

Flujo de integración concreto:
1. Edito estilos en `docs_src/<pagina>/index.html` (solo `<style>`, sin tocar DOM/JS).
2. `$env:STATICRYPT_PASSWORD = "..."; .\scripts\encrypt_html.ps1` → regenera `docs/`.
3. Reviso en local: `python -m http.server 8080 --directory docs`.
```
