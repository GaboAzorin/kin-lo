# Design tokens extraídos de Stitch — kino-loto "Premium Glass / Aurora"

> Fuente: `design/stitch_export/.../DESIGN.md` + el CSS real de
> `detalle_kino_..._corregida/code.html`. Cuando hay conflicto entre el `DESIGN.md`
> abstracto y el código renderizado, **manda el código** (es lo que se ve en las
> capturas que aprobamos).

## Base / fondo (Aurora)
- Fondo base: `#111318`
- Aurora: 3 "blobs" `position:fixed`, `filter: blur(100px)`, `opacity:0.4`,
  `border-radius:50%`, animación `float 20s infinite ease-in-out alternate`:
  - blob 1: 600px, `#3b82f6` (Kino blue), top/left -10%
  - blob 2: 500px, `#6b21a8` (purple), bottom 0 / right -5%, delay -5s
  - blob 3: 400px, `#0ea5e9` (cyan), top/left 40%, delay -10s
- `@keyframes float { 0%{translate(0,0) scale(1)} 100%{translate(50px,50px) scale(1.1)} }`

## Acentos de marca
- **Loto = ámbar `#f59e0b`** (variantes: `#ffc174`, `#ffb95f` para texto/realces)
- **Kino = azul `#3b82f6`**
- Positivo/Σ-zona-central: verde `#56e5a9` / `tertiary-fixed #6ffbbe`
- Error / sequía: rojo (`bg-red-500/400/300/200`)
- Texto: `on-surface #e2e2e8`; atenuado `on-surface-variant #d8c3ad`

## Glass card
```css
.glass-card{
  background-color: rgba(30,32,36,0.4);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.1);
  background-image: radial-gradient(circle at 50% 0%, rgba(255,255,255,0.05) 0%, transparent 70%);
}
.glass-card:hover{           /* "lift & glow" */
  border-color: rgba(255,255,255,0.25);
  box-shadow: 0 0 15px rgba(59,130,246,0.15);  /* glow del acento del juego */
  transition: all .3s ease;
}
```

## Bolitas de número (siempre círculo perfecto)
```css
.kino-ball{ border-radius:50%; background:rgba(59,130,246,0.1); border:1px solid #3b82f6;
            color:#fff; box-shadow: inset 0 0 10px rgba(59,130,246,0.2); font-weight:600; }
/* Loto = mismo patrón con #f59e0b: background rgba(245,158,11,0.1); border #f59e0b;
   box-shadow inset 0 0 10px rgba(245,158,11,0.2) */
/* tamaños */ -lg:48px/18px  -md:32px/14px  -sm:24px/12px
```

## Heatmap (5 niveles, por opacidad del acento)
```css
.heat-1{background:rgba(59,130,246,0.1)} .heat-2{.3} .heat-3{.5} .heat-4{.7}
.heat-5{background:rgba(59,130,246,0.9); border-color:#60a5fa!important; box-shadow:0 0 10px rgba(96,165,250,0.5)}
/* Loto: mismos niveles con 245,158,11 */
```
Grilla: `grid-cols-5 gap-2`, celdas `aspect-square rounded-lg border border-white/10`.

## Pills de rango (chips)
- Normal: `rounded-full border border-white/20`, texto atenuado, hover `border-white/30 + texto blanco`.
- Activo: borde del acento + texto del acento + glow suave.
- ★ "mejor grupo": `bg-gradient-to-r from-amber-400 to-amber-600 text-black`,
  `shadow-[0_0_10px_rgba(245,158,11,0.5)]`, ícono estrella.

## Botones
- Primario Loto/Kino: relleno del acento + overlay gloss blanco 10%, transición 200ms.
- Fantasma: transparente, `border-white/20`, hover `bg-white/5`.

## Barras (calientes / fríos / sequía)
- Pista: `h-2 rounded-full bg-white/10 overflow-hidden`.
- Relleno: calientes `bg-orange-500..300`, fríos `bg-blue-500..300`, sequía `bg-red-500..200`.

## Tipografía
- Titulares: **Montserrat** 600/700, tracking negativo (`-0.02em` a `-0.04em`).
- Cuerpo y datos: **Inter**; datos/números con `font-variant-numeric: tabular-nums`.
- Micro-labels de sección: 12px, 600, `uppercase`, `letter-spacing .05em`, color atenuado.
- (Iconos en Stitch: Material Symbols. En la integración los reemplazo por los emojis/SVG
  que ya usa el sitio o por SVG inline; no es obligatorio meter Material Symbols.)

## Header
- `bg-surface/60 backdrop-blur-xl`, borde inferior `white/10`, fixed top.
- Estructura: logo+`kino-loto` (izq) · nav (centro) · sello de fecha (der).

## Badges de marca
- `Polla.cl`: tag neutro white-alpha. `Loteria.cl`: tag azul-alpha (`bg-blue-900/40 text-blue-200`).

## Radios / spacing
- Radios: card/input `0.5rem`, cards grandes hasta `0.75–1rem`, pills/bolitas `full`.
- Padding interno de cards: mínimo 24px. Container máx 1280px. Base de ritmo 8px.

## Notas de integración
- El sitio NO usa Tailwind: traduzco estas utilidades a CSS plano en el `<style>` de
  cada `docs_src/<pagina>/index.html`, reescribiendo `:root{--vars}` y las clases
  existentes (`.bola`, `.sug-pill`, `.card`, `.heatmap`, etc.) **sin tocar IDs ni JS**.
- Las fuentes pasan de Geist a Montserrat+Inter (Google Fonts).
