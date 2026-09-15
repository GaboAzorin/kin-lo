# Relay para polla.cl — DESCARTADO (2026-09-15)

> **Esta vía no funciona. No la reintentes sin leer esto.**
>
> El relay se desplegó en Cloudflare Workers y funciona correctamente: alcanza
> polla.cl y devuelve la respuesta. El problema es que **Imperva bloquea también
> la IP de salida de Cloudflare**, igual que la de Azure.
>
> Medido el 2026-09-15 desde `relay-polla.ga-azorin.workers.dev`
> (IP de salida `104.22.10.178`):
>
> ```
> HTTP 403 · set-cookie: incap_ses_... · body con _Incapsula_Resource
> ```
>
> Sumado a lo que ya sabíamos —403 desde Azure con urllib, con fingerprint TLS de
> Chrome y con Chromium real— la conclusión es que **Imperva rechaza rangos de
> datacenter en general**, no un proveedor concreto. Deno Deploy y Val.town corren
> sobre infraestructura de nube más convencional todavía, así que no se probaron:
> si Cloudflare no pasa, ellos tampoco.
>
> Lo que haría falta es una **IP residencial**, que ningún free tier serverless
> ofrece. El código se conserva como evidencia y por si algún día cambia el
> panorama (p. ej. una plataforma con salida residencial).
>
> Alternativas vivas:
>
> - **Proxy residencial** (`scripts/SCRAPINGANT.md`): si el bloqueo es reputación
>   de rangos de datacenter, una IP residencial debería pasar. Se sondea con
>   `python scripts/diagnostico_polla.py --probe scrapingant`.
> - `scripts/sondeo_fuentes_loto.py`, que busca fuentes de resultados que no
>   estén detrás de Imperva.

---

## Qué era (documentación original)

polla.cl bloquea las IPs de GitHub Actions, así que el workflow de Loto no puede
pegarle directo. `worker.js` es un relay mínimo que corre en un free tier
serverless y reenvía las peticiones desde otra IP.

El mismo archivo corre sin cambios en las tres plataformas. La idea es
desplegarlo en varias y dejar que el diagnóstico diga cuál pasa el bloqueo.

## Qué hace

```
Actions  --POST /{url,method,headers,body} + X-Relay-Token-->  worker
worker   --petición real-->  polla.cl
worker   --{status, headers, body} en JSON-->  Actions
```

El `status` HTTP de la respuesta del relay es el **del relay**. Lo que respondió
polla.cl va dentro, en el campo `status` del JSON. Un relay que funciona
devolviendo `200` con `{"status": 403}` adentro significa que el relay está bien
y el bloqueo sigue: son dos fallos distintos y no hay que confundirlos.

## Seguridad

- **Token obligatorio** (`X-Relay-Token`), comparado en tiempo constante.
- **Allowlist de hosts**: solo proxea a polla.cl. Aunque el token se filtre, el
  relay no sirve de proxy abierto hacia cualquier destino.
- El `GET /` de salud no pide token y no expone nada sensible.

Genera el token con algo como `openssl rand -hex 32`. **No lo commitees**: va como
secret del repo y como variable de entorno del worker.

## Despliegue

### Cloudflare Workers

**Corre los comandos desde la carpeta `relay/` del repo clonado**, no desde
cualquier directorio: wrangler lee `wrangler.toml` del directorio actual y
escribe su caché ahí. Lanzarlo desde una ruta protegida del sistema
(`C:\WINDOWS\System32`, por ejemplo) falla con un error de permisos que no
menciona el directorio como causa.

```bash
npm install -g wrangler
wrangler login

cd <ruta-del-repo>/relay      # en Windows: cd C:\ruta\a\kin-lo\relay
wrangler deploy               # wrangler.toml ya trae name, main y fecha
wrangler secret put RELAY_TOKEN   # pega el token cuando lo pida
```

URL resultante: `https://relay-polla.<tu-subdominio>.workers.dev`

### Deno Deploy

```bash
deno install -Arf jsr:@deno/deployctl
cd relay
deployctl deploy --project=relay-polla worker.js
```
El `RELAY_TOKEN` se define en el dashboard del proyecto → Settings →
Environment Variables.

### Val.town

1. Crear un HTTP val nuevo.
2. Pegar el contenido de `worker.js`.
3. Definir `RELAY_TOKEN` en Environment Variables del val.
4. Definir también `VALTOWN=1` — evita que se llame a `Deno.serve`, que en
   Val.town rompe el despliegue.

## Verificar que quedó arriba

```bash
curl https://<tu-url>/            # debe responder {"ok":true,...}
```

Y la ruta completa contra polla.cl:

```bash
curl -X POST https://<tu-url>/ \
  -H "X-Relay-Token: <token>" \
  -H "content-type: application/json" \
  -d '{"url":"https://www.polla.cl/es/view/resultados"}'
```

Si el JSON devuelto trae `"status": 200` y un `csrfToken` en el body, **esa
plataforma esquiva el bloqueo** y es la que hay que usar.

## Conectarlo al repo

Secrets del repositorio:

| Secret | Valor |
|---|---|
| `RELAY_URL` | URL del worker que haya funcionado |
| `RELAY_TOKEN` | el token generado |

Después, correr el workflow **Diagnóstico polla.cl** con la sonda `relay`.

## Si ninguna plataforma pasa

Quiere decir que el bloqueo no es solo por rango de IP. Lo dirá el veredicto del
diagnóstico: si aparece firma de WAF (Cloudflare, Akamai, Imperva, DataDome) o un
challenge de JavaScript, hay que atacar el fingerprint TLS / la ejecución de JS,
y un relay HTTP plano no alcanza.
