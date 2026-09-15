# ScrapingAnt — proxy residencial para polla.cl

> Vive aquí, junto a `diagnostico_polla.py`, que es el único código que lo usa
> hoy. `relay/README.md` documenta una vía ya **descartada**; meter dentro de
> ella la alternativa viva confundiría las dos.

## Por qué

polla.cl está detrás de Imperva y rechaza **rangos de datacenter**, no un
proveedor concreto. Está medido: 403 desde GitHub Actions (Azure) con `urllib`,
con fingerprint TLS de Chrome y con Chromium real; y 403 también desde un relay
propio en Cloudflare Workers.

Lo único que queda por probar es salir por una **IP residencial**. ScrapingAnt
ofrece proxies residenciales en un free tier de **10.000 créditos al mes,
recurrentes y sin tarjeta**.

## Crear la cuenta y sacar la API key

1. Registrarse en <https://scrapingant.com/> (basta el email; no pide tarjeta
   para el plan gratuito).
2. Entrar al dashboard. La **API key** aparece en la portada / sección
   *API key*; es una cadena hexadecimal larga.
3. Copiarla. No pegarla en ningún archivo del repo: es un repo público.

## Cargarla como secret del repo

En GitHub: **Settings → Secrets and variables → Actions → New repository
secret**.

- Name: `SCRAPINGANT_API_KEY`
- Secret: la key copiada

Si el secret no existe, la sonda lo reporta como "no configurada" y no gasta
nada ni intenta salir a la red.

## País del proxy: Chile NO está disponible

Medido en Actions (2026-09-15): pedirle `proxy_country=cl` a ScrapingAnt devuelve
**422** con la lista de países permitidos. `cl` no aparece. De Latinoamérica solo
hay **`br`, `mx` y `bz`**.

Países disponibles (textual desde el error de la API):

```
ae br bz ca cn cz de es fr gb hk id il in it jp kr mx my nh nl ph pk pl
ro ru sa sc se sg th tr tw uk us vn
```

El resto de los parámetros (`url`, `x-api-key`, `proxy_type=residential`) sí
fueron aceptados: el 422 señalaba únicamente a `proxy_country`.

**Por defecto no se envía país**: la sonda usa el pool global de ScrapingAnt.
Es la prueba más limpia de "¿basta una IP residencial?", sin mezclar la variable
geográfica. Si polla.cl además filtrara por geografía, ninguna opción de
ScrapingAnt serviría — pero eso es una hipótesis que el diagnóstico tiene que
distinguir, no algo dado.

### Probar con un país concreto

Definir la **variable de repositorio** (no secret) `SCRAPINGANT_COUNTRY`:
**Settings → Secrets and variables → Actions → pestaña *Variables* → New
repository variable**, con valor `br` o `mx`. El workflow la pasa tal cual.

En local:

```bash
SCRAPINGANT_COUNTRY=br SCRAPINGANT_API_KEY=... \
  python scripts/diagnostico_polla.py --probe scrapingant
```

Si el valor no está en la lista de arriba, la sonda **falla antes de hacer la
petición** y muestra los válidos: así un `cl` por costumbre no quema créditos en
un 422 evitable.

Cuando la sonda falle **con** país configurado, el veredicto avisa de que el
resultado puede deberse a esa geografía y sugiere reintentar sin país. Si falla
**sin** país, esa salvedad no se imprime porque no aplica.

## Cómo correrla

Desde la pestaña **Actions → Diagnóstico polla.cl → Run workflow**, eligiendo
`scrapingant` en el desplegable.

En local:

```bash
SCRAPINGANT_API_KEY=... python scripts/diagnostico_polla.py --probe scrapingant
```

## Presupuesto de créditos

Cada petición con `proxy_type=residential` cuesta **~25 créditos** de los 10.000
mensuales (≈ 400 peticiones al mes). Por eso:

- la sonda hace **una sola petición** por corrida y **no reintenta** nunca;
- `scrapingant` **no** se incluye en la opción `todas` del workflow ni en la
  corrida por defecto del script: solo corre si se la pide explícitamente.

## Cómo leer el resultado

Un `200` de la API de ScrapingAnt **no** significa éxito: el servicio puede
devolver 200 con el HTML de bloqueo de Imperva dentro. El veredicto por eso
distingue tres casos y solo el primero es un éxito:

| Resultado | Significa |
|---|---|
| 200 **con `csrfToken`** en el HTML | la vía residencial funciona |
| 200 pero con firma de Imperva en el HTML | el proxy residencial no basta |
| 4xx/5xx de la propia API | key inválida, créditos agotados o parámetros mal |

## Estado de los parámetros

Verificado contra la API real (corrida en Actions, 2026-09-15): `url`,
`x-api-key`, `proxy_type` y `proxy_country` son nombres correctos — el único
error devuelto fue el valor `cl` de `proxy_country`. Lo que sigue sin verificarse
es si la vía residencial atraviesa el WAF de polla.cl: para eso hay que correr la
sonda con una API key válida.
