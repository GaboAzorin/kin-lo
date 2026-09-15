# Relay serverless para scraping de polla.cl desde GitHub Actions

## Goal

Automatizar la actualización de datos de Loto en GitHub Actions (hoy manual/local,
vía `scripts/actualizar_loto.ps1`) sin costo y sin depender de la máquina del
usuario. polla.cl bloquea las IPs de GitHub Actions (Azure). La vía elegida es un
**relay serverless gratuito** que hace de salida alternativa: Actions llama al
relay, el relay llama a polla.cl y devuelve el JSON.

## What I already know

* `src/scrapers/scraper_polla.py` usa Playwright + token CSRF contra
  `POST https://www.polla.cl/es/get/draw/results` (`gameId=5271`).
* Un solo `gameId` trae Loto + Recargado + Revancha + Desquite.
* `scrape_polla()` ya acepta `proxy_config` y lo pasa a `chromium.launch()`.
* Existe soporte a medias de Scrape.do (`USE_SCRAPEDO`, `SCRAPEDO_TOKEN`,
  `scraper_polla.py:398-409`). **La cuenta del usuario fue baneada** → esa vía
  está muerta por ahora.
* El token de Scrape.do nunca estuvo hardcodeado en el repo (verificado en todo
  el historial de git); el ban no vino de una filtración desde aquí.
* `.github/workflows/scrape-loto.yml` existe pero está desactivado (`if: false`).
* `fetch_pozos.py` y `scripts/backfill_loto_premio.py` también pegan a polla.cl.
* La API responde a cualquier `drawId` histórico → los premios son backfilleables.

## Hallazgos medidos (corrida en Actions, 2026-09-15)

* IP del runner: `172.174.223.248` — `AS8075 Microsoft Corporation`, Virginia US.
  Confirma que Actions sale por Azure.
* `GET /es/view/resultados` → **403 con WAF de Imperva/Incapsula** (body con
  `_Incapsula_Resource`). El mismo 403 en el POST a la API.
* **Refuta la premisa del repo**: no es un filtro de IP a secas como decía
  CLAUDE.md, hay un WAF comercial delante.
* Endpoints móviles descartados: `api.polla.cl` no resuelve por DNS; las rutas
  bajo `www.polla.cl` caen en el mismo 403 de Imperva.

### Confusión del experimento (importante)

La sonda usa `urllib`, cuyo fingerprint TLS Imperva rechaza en cualquier IP.
Respecto del setup que SÍ funciona (PC del usuario) cambiaron DOS variables:
IP (residencial CL → Azure US) y cliente (Chromium real → urllib). El 403 se
explica por cualquiera de las dos, así que el veredicto automático
("un relay probablemente no baste") está sobre-afirmando: es hipótesis, no dato.

## Assumptions (temporary)

* Si el bloqueo es de fingerprint, basta cambiar de cliente HTTP (curl-cffi) y no
  hace falta relay ni cuentas. **EN VALIDACIÓN** (sondas `impersonate`/`playwright`).
* Si el bloqueo es de reputación de IP, el relay debe además imitar fingerprint de
  navegador — el `fetch()` del worker NO lo hace, así que `relay/worker.js` tal
  como está podría fallar igual.

## Decision (ADR-lite)

**Context**: Hay que sacar el tráfico de una IP que no sea de Azure, gratis y sin
nada corriendo en la máquina del usuario. No sabemos si el bloqueo es por rango de
IP o por WAF, así que no se puede elegir plataforma por razonamiento previo.

**Decision**:
1. Relay portable (`relay/worker.js`) que corre igual en Cloudflare Workers,
   Deno Deploy y Val.town. Se despliega en varias y el diagnóstico decide cuál pasa.
2. Autenticación por token compartido (`X-Relay-Token`), comparado en tiempo
   constante, más allowlist de hosts para que no quede como proxy abierto si el
   token se filtra.
3. Antes del relay se corre un workflow de diagnóstico que mide el bloqueo real.

**Consequences**: El usuario debe crear cuentas en 2-3 plataformas. A cambio, si
una falla tenemos alternativa inmediata sin reescribir nada. Si TODAS fallan, el
diagnóstico lo dirá y significa que el bloqueo no es por IP — ahí el relay no
sirve y hay que replantear.

## Open Questions

* ¿El bloqueo es por rango de IP o por WAF? → lo responde el workflow de diagnóstico.
* ¿El flujo CSRF+POST funciona sin Playwright, con HTTP plano por el relay?
  → se decide cuando sepamos si el relay llega.

## Requirements (evolving)

* Costo $0 recurrente, sin trial que expire.
* Orquestación en GitHub Actions; nada corre en la máquina del usuario.
* No degradar el flujo local existente (`actualizar_loto.ps1` sigue siendo fallback).

## Acceptance Criteria (evolving)

* [ ] Un workflow de diagnóstico reporta el status/body real de polla.cl desde Actions.
* [ ] El relay obtiene un sorteo conocido desde polla.cl y devuelve su JSON.
* [ ] `scraper_polla.py` puede usar el relay y escribir una fila válida en el CSV.
* [ ] El workflow de Loto queda activo con cron mar/jue/dom post-sorteo.

## Estado

Hecho (sin verificar contra polla.cl real — falta correr en Actions):
* `scripts/diagnostico_polla.py` — sondas directo / movil / relay + veredicto.
* `relay/worker.js` — relay portable a 3 plataformas.
* `relay/README.md` — despliegue y verificación.
* `.github/workflows/diagnostico-polla.yml` — corre el diagnóstico a mano.

Probado localmente: auth del worker (token ausente/incorrecto/longitud distinta),
allowlist de hosts, URL inválida, método no permitido, ruta feliz, reenvío de body
POST, preservación del status upstream, y el cliente Python contra un relay falso.

Pendiente: desplegar el relay y correr el workflow. Nada de esto toca polla.cl
todavía.

## Out of Scope (explicit)

* Cuentas de pago o free tiers con tarjeta.
* Runners self-hosted / cualquier ejecución en la máquina del usuario.
* Multi-cuenta para farmear free tiers.
* Migrar el scraping de Kino (ya funciona en Actions).

## Technical Notes

* Sin salida de red a polla.cl desde la sesión de Claude → toda prueba real
  ocurre en Actions o en el relay ya desplegado.
