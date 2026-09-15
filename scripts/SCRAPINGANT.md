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

## Pendiente de confirmar

Los nombres exactos de los parámetros (`x-api-key`, `proxy_type`,
`proxy_country`) están tomados de la documentación pero **no se han verificado
contra la API real**. Si alguno está mal, ScrapingAnt responde 4xx y el informe
imprime su mensaje de error, que suele nombrar el parámetro correcto.
