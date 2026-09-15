"""
diagnostico_polla.py
Sondea desde dónde se puede alcanzar polla.cl. No escribe datos: solo reporta.

Existe porque el repo asume "polla.cl bloquea las IPs de GitHub Actions" sin haber
registrado nunca el error real. Sin saber si el bloqueo es por rango de IP o por
WAF, elegir una solución (relay serverless, proxy, otra fuente) es adivinar.

Sondas:
  directo      — polla.cl desde donde corra esto (en Actions = IP de Azure)
  movil        — endpoints candidatos de API de app móvil, que suelen no llevar WAF
  impersonate  — misma IP que `directo`, pero con fingerprint TLS de Chrome
  playwright   — misma IP, con Chromium real y el flujo CSRF + POST completo
  relay        — vía el relay serverless, si RELAY_URL está definido
  scrapingant  — vía ScrapingAnt con proxy residencial (free tier)

`directo`, `impersonate` y `playwright` salen por la MISMA IP y solo cambian el
cliente: comparándolas se separa "me bloquean por reputación de IP" de "me
bloquean por cómo me veo", que llevan a soluciones completamente distintas.

`scrapingant` queda FUERA de la corrida por defecto: cada petición gasta
créditos de un free tier limitado y no renovable dentro del mes, así que solo
corre cuando se la pide explícitamente con --probe.

Uso:
    python scripts/diagnostico_polla.py                 # sondas por defecto
    python scripts/diagnostico_polla.py --probe directo
    python scripts/diagnostico_polla.py --probe scrapingant   # gasta créditos

Salida: informe legible a stdout y, con --json, un JSON para inspección posterior.
El exit code es 0 aunque todas las sondas fallen: un bloqueo es un resultado
válido del diagnóstico, no un error de ejecución.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE_URL = "https://www.polla.cl/es/view/resultados"
API_URL = "https://www.polla.cl/es/get/draw/results"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Sorteo antiguo y ya cerrado: si la API responde, debe traer resultados. Sirve de
# canario — un 200 con `results` vacío aquí significa que la respuesta no es real.
SORTEO_CANARIO = 5000
GAME_ID = "5271"

TIMEOUT = 30
BODY_SNIPPET = 600

# ScrapingAnt: API de scraping con salida por proxies residenciales. Es la
# hipótesis viva después de que relay serverless, fingerprint TLS y Chromium real
# dieran 403 — todos salen por rangos de datacenter, que es justo lo que Imperva
# rechaza. Free tier: 10.000 créditos/mes recurrentes y sin tarjeta.
SCRAPINGANT_URL = "https://api.scrapingant.com/v2/general"
# Nombres de parámetro tomados de la documentación de ScrapingAnt. No se pudieron
# verificar contra la API real (este entorno no tiene salida de red): CONFIRMAR en
# la primera corrida de Actions. Si alguno no existe, la API responde 400/422 con
# el nombre correcto en el mensaje de error, que el informe imprime tal cual.
SCRAPINGANT_PARAMS = {
    "x-api-key": None,          # se rellena con la key del entorno
    "proxy_type": "residential",
}
# Modo por defecto: SIN navegador (`browser=false`).
#
# Medido en Actions (2026-09-15) con `proxy_type=residential` y pool global:
# ScrapingAnt devolvió 423 tras 6,6 s con "Our browser was detected by target
# site". O sea: la petición SÍ llegó a polla.cl y lo que Imperva detectó fue el
# NAVEGADOR headless que ScrapingAnt usa por defecto, no necesariamente la IP.
#
# La página de resultados sirve el `csrfToken` en el HTML, sin JavaScript, así
# que el render no aporta nada: apagarlo quita justo la superficie que falló y
# además cuesta menos créditos. Es a la vez el experimento correcto y el barato.
#
# El nombre del parámetro (`browser`) y su valor ("false") vienen de la
# documentación de ScrapingAnt; NO se pudieron verificar contra la API real
# desde este entorno (sin salida de red) — CONFIRMAR en la primera corrida, como
# se hizo con los demás parámetros. Si el nombre fuese otro, la API responde 422
# nombrando el correcto y el informe lo imprime tal cual.
SCRAPINGANT_BROWSER_DEFECTO = "false"
# Países con proxy residencial en ScrapingAnt, textual desde el 422 que devolvió
# la API al pedirle `proxy_country=cl` (corrida en Actions, 2026-09-15).
#
# CHILE NO ESTÁ. De Latinoamérica solo hay br, mx y bz. Importa porque, si
# polla.cl filtra además por geografía y no solo por reputación de IP, entonces
# NINGUNA opción de ScrapingAnt serviría y la vía residencial estaría muerta por
# una razón distinta de la que se está probando. Es una hipótesis que este mismo
# diagnóstico debe distinguir, no un hecho: por eso el default es NO mandar país
# (pool global de ScrapingAnt), que es la prueba más limpia de "¿basta una IP
# residencial?" sin meter la variable geográfica de por medio.
SCRAPINGANT_PAISES = [
    "ae", "br", "bz", "ca", "cn", "cz", "de", "es", "fr", "gb", "hk", "id",
    "il", "in", "it", "jp", "kr", "mx", "my", "nh", "nl", "ph", "pk", "pl",
    "ro", "ru", "sa", "sc", "se", "sg", "th", "tr", "tw", "uk", "us", "vn",
]
# Una petición residencial cuesta ~25 créditos de los 10.000 mensuales. Por eso la
# sonda hace UNA sola petición por corrida y no reintenta nunca: un bucle de
# reintentos podría vaciar el mes entero en una tarde.
SCRAPINGANT_TIMEOUT = 120

# Rutas candidatas de API de app móvil. No están documentadas; son los patrones
# habituales. Que devuelvan 404 es informativo (no existen), que devuelvan 200 es
# el mejor resultado posible de este diagnóstico.
CANDIDATOS_MOVIL = [
    "https://www.polla.cl/api/draw/results",
    "https://www.polla.cl/api/v1/draw/results",
    "https://api.polla.cl/draw/results",
    "https://api.polla.cl/v1/results",
    "https://www.polla.cl/es/get/draw/results",
]


def _request(url, method="GET", data=None, headers=None, timeout=TIMEOUT,
             cuerpo_completo=False):
    """Ejecuta una petición y devuelve siempre un dict, incluso si falla.

    urllib levanta HTTPError para 4xx/5xx, pero aquí un 403 es justamente el dato
    que buscamos, así que se captura y se reporta como resultado normal.

    `cuerpo_completo` añade `body_completo` con la respuesta entera. Por defecto
    está apagado porque el informe solo necesita un fragmento y el JSON no debe
    engordar con páginas enteras; se enciende cuando hay que buscar algo que
    puede aparecer más allá del fragmento (p. ej. `csrfToken` en el HTML que
    devuelve un intermediario).
    """
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)

    payload = data.encode() if isinstance(data, str) else data
    req = urllib.request.Request(url, data=payload, headers=hdrs, method=method)

    inicio = datetime.now(timezone.utc)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            crudo = resp.read() if cuerpo_completo else resp.read(BODY_SNIPPET * 4)
            cuerpo = crudo.decode("utf-8", errors="replace")
            return {
                "url": url,
                "status": resp.status,
                "headers": dict(resp.headers),
                "body": cuerpo[:BODY_SNIPPET],
                "body_len": len(cuerpo),
                **({"body_completo": cuerpo} if cuerpo_completo else {}),
                "error": None,
                "ms": int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000),
            }
    except urllib.error.HTTPError as e:
        crudo = e.read() if cuerpo_completo else e.read(BODY_SNIPPET * 4)
        cuerpo = crudo.decode("utf-8", errors="replace")
        return {
            "url": url,
            "status": e.code,
            "headers": dict(e.headers or {}),
            "body": cuerpo[:BODY_SNIPPET],
            "body_len": len(cuerpo),
            **({"body_completo": cuerpo} if cuerpo_completo else {}),
            "error": f"HTTP {e.code}",
            "ms": int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000),
        }
    except Exception as e:
        return {
            "url": url,
            "status": None,
            "headers": {},
            "body": "",
            "body_len": 0,
            "error": f"{type(e).__name__}: {e}",
            "ms": int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000),
        }


def _resultado_error(nombre, url, error, ms=0):
    """Resultado con forma de sonda para fallos previos a cualquier petición.

    Las sondas opcionales (dependencia ausente, browser sin instalar) tienen que
    reportarse, no reventar: un `status` None marca "no se midió", que el
    veredicto trata distinto de un rechazo HTTP.
    """
    return {
        "nombre": nombre,
        "url": url,
        "status": None,
        "headers": {},
        "body": "",
        "body_len": 0,
        "error": error,
        "ms": ms,
    }


def _pistas_waf(res):
    """Busca en headers y cuerpo la firma de un WAF conocido.

    Distingue el caso que decide todo el diseño: un bloqueo por rango de IP (que
    un relay esquiva) frente a un WAF con challenge (que no).
    """
    pistas = []
    headers_txt = " ".join(f"{k}: {v}" for k, v in res.get("headers", {}).items()).lower()
    cuerpo = (res.get("body") or "").lower()
    firmas = {
        "cloudflare": ["cf-ray", "cloudflare", "__cf_bm"],
        "akamai": ["akamai", "ak_bmsc", "x-akamai"],
        "imperva": ["incap_ses", "visid_incap", "imperva", "_incapsula_"],
        "aws-waf": ["x-amzn-waf", "awswaf"],
        "datadome": ["datadome"],
        "challenge-js": ["just a moment", "enable javascript", "checking your browser"],
    }
    for nombre, marcas in firmas.items():
        if any(m in headers_txt or m in cuerpo for m in marcas):
            pistas.append(nombre)
    return pistas


def probe_directo():
    """polla.cl sin intermediarios, desde la IP de quien ejecute esto."""
    resultados = []

    r = _request(BASE_URL)
    r["nombre"] = "GET página de resultados"
    r["tiene_csrf"] = "csrfToken" in (r.get("body") or "")
    resultados.append(r)

    # El POST sin token CSRF válido puede legítimamente fallar; lo que importa es
    # distinguir "me rechazó por token" de "me bloqueó por IP antes de mirar nada".
    cuerpo = f"gameId={GAME_ID}&drawId={SORTEO_CANARIO}&csrfToken=probe"
    r = _request(
        API_URL,
        method="POST",
        data=cuerpo,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "x-requested-with": "XMLHttpRequest",
            "Origin": "https://www.polla.cl",
            "Referer": BASE_URL,
        },
    )
    r["nombre"] = "POST API de resultados (sin CSRF real)"
    resultados.append(r)
    return resultados


def probe_movil():
    """Endpoints candidatos de app móvil. Un 200 aquí resolvería todo gratis."""
    resultados = []
    for url in CANDIDATOS_MOVIL:
        r = _request(
            url,
            method="POST",
            data=json.dumps({"gameId": GAME_ID, "drawId": SORTEO_CANARIO}),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                # UA de app, no de navegador: es lo que distingue esta sonda.
                "User-Agent": "okhttp/4.12.0",
            },
        )
        r["nombre"] = f"POST móvil {url}"
        resultados.append(r)
    return resultados


def probe_relay():
    """polla.cl a través del relay serverless.

    Es la sonda que valida la hipótesis central: si `directo` falla y esta pasa,
    el bloqueo era por IP y el relay resuelve el problema.
    """
    relay_url = os.environ.get("RELAY_URL", "").strip()
    relay_token = os.environ.get("RELAY_TOKEN", "").strip()
    if not relay_url:
        return [{
            "nombre": "relay",
            "url": "(no configurado)",
            "status": None,
            "headers": {},
            "body": "",
            "body_len": 0,
            "error": "RELAY_URL no está definido — despliega el relay primero",
            "ms": 0,
        }]

    peticion = json.dumps({
        "url": BASE_URL,
        "method": "GET",
        "headers": {"User-Agent": USER_AGENT},
    })
    r = _request(
        relay_url,
        method="POST",
        data=peticion,
        headers={
            "Content-Type": "application/json",
            "X-Relay-Token": relay_token,
        },
        timeout=60,
    )
    r["nombre"] = "GET página de resultados vía relay"

    # El relay devuelve el resultado envuelto; hay que mirar dentro para saber qué
    # le respondió polla.cl a él, que es distinto de lo que el relay nos respondió.
    try:
        envuelto = json.loads(r.get("body") or "{}")
        r["status_upstream"] = envuelto.get("status")
        r["tiene_csrf"] = "csrfToken" in (envuelto.get("body") or "")
    except (json.JSONDecodeError, AttributeError):
        r["status_upstream"] = None
        r["tiene_csrf"] = False

    return [r]


def probe_scrapingant():
    """polla.cl vía ScrapingAnt, que sale por proxies residenciales.

    Es la sonda que queda después de descartar el relay: si el bloqueo es puro
    reputación de IP de datacenter (que es lo que indican los 403 desde Azure y
    desde Cloudflare), una IP residencial debería pasar.

    Por defecto NO se fija país: se usa el pool global. Definiendo la variable de
    entorno SCRAPINGANT_COUNTRY (p. ej. `br` o `mx`) se prueba una geografía
    concreta, sin tocar código. Chile no está disponible (ver SCRAPINGANT_PAISES).

    Por defecto tampoco se renderiza con navegador (`browser=false`): el 423 que
    devolvió la API dice que lo detectado fue el navegador, y el HTML con el
    csrfToken no necesita JS. Con SCRAPINGANT_BROWSER=true se vuelve a probar el
    modo navegador sin tocar código.

    Hace UNA sola petición y no reintenta: cada request residencial cuesta ~25
    créditos de los 10.000 del free tier mensual.
    """
    pais = os.environ.get("SCRAPINGANT_COUNTRY", "").strip().lower()
    browser_env = os.environ.get("SCRAPINGANT_BROWSER", "").strip().lower()
    # Cualquier valor que no sea "true" se trata como false: el default es no
    # renderizar, y un valor mal escrito no debería activar en silencio el modo
    # caro que además es el que ya falló.
    con_browser = browser_env == "true"
    nombre = (
        "GET página de resultados vía ScrapingAnt (proxy residencial, "
        + ("con navegador" if con_browser else "sin navegador")
        + ", "
        + (f"país={pais}" if pais else "pool global")
        + ")"
    )

    if pais and pais not in SCRAPINGANT_PAISES:
        # Falla ANTES de pedir nada: un país inválido es un 422 seguro, y gastar
        # un request (y créditos) para que la API repita lo que ya sabemos aquí
        # sería tirar free tier a la basura.
        return [_resultado_error(
            nombre,
            SCRAPINGANT_URL,
            f"SCRAPINGANT_COUNTRY='{pais}' no es un país válido de ScrapingAnt "
            f"(no se hizo ninguna petición). Válidos: {', '.join(SCRAPINGANT_PAISES)}. "
            "Chile no está disponible; dejar la variable sin definir usa el pool global.",
        )]

    api_key = os.environ.get("SCRAPINGANT_API_KEY", "").strip()
    if not api_key:
        # Sin key no se intenta nada: así la sonda nunca consume créditos por
        # accidente ni revienta el diagnóstico completo.
        return [_resultado_error(
            nombre,
            SCRAPINGANT_URL,
            "SCRAPINGANT_API_KEY no está configurada — crear cuenta gratis en "
            "scrapingant.com, copiar la API key del dashboard y cargarla como "
            "secret SCRAPINGANT_API_KEY (ver scripts/SCRAPINGANT.md)",
        )]

    params = dict(SCRAPINGANT_PARAMS, url=BASE_URL)
    params["x-api-key"] = api_key
    params["browser"] = "true" if con_browser else SCRAPINGANT_BROWSER_DEFECTO
    if pais:
        params["proxy_country"] = pais
    url = f"{SCRAPINGANT_URL}?{urllib.parse.urlencode(params)}"

    # Misma query pero sin la key: es la que se reporta e informa.
    publicos = {k: v for k, v in params.items() if k != "x-api-key"}
    url_publica = f"{SCRAPINGANT_URL}?{urllib.parse.urlencode(publicos)}"

    # Cuerpo completo: `csrfToken` aparece bien entrado el HTML, mucho más allá
    # del fragmento que guarda el informe.
    r = _request(url, timeout=SCRAPINGANT_TIMEOUT, cuerpo_completo=True)
    r["nombre"] = nombre
    # La URL con la key dentro no debe acabar en el informe ni en el artifact.
    r["url"] = url_publica
    r["pais"] = pais or None
    r["browser"] = con_browser

    # Dos cosas distintas que hay que reportar por separado:
    #   - el status de la API de ScrapingAnt (¿me atendió el servicio?)
    #   - qué contenido devolvió (¿es la página real de polla.cl?)
    # ScrapingAnt puede responder 200 y entregar el HTML de bloqueo de Imperva;
    # leer ese caso como éxito es exactamente el error que hay que evitar.
    contenido = r.get("body_completo") or r.get("body") or ""
    r.pop("body_completo", None)  # no se persiste: es la página entera
    r["tiene_csrf"] = "csrfToken" in contenido
    r["pistas_extra"] = _pistas_waf({"headers": {}, "body": contenido})

    return [r]


def probe_impersonate():
    """polla.cl con fingerprint TLS/JA3 de Chrome, sin levantar navegador.

    Corre desde la MISMA IP que `directo`; lo único que cambia es el cliente. Si
    `directo` (urllib) da 403 y esta da 200, el bloqueo no es por reputación de IP
    sino por fingerprint — y entonces sobra todo el andamiaje de relay.
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError as e:
        # Sonda opcional: su ausencia no debe tumbar el diagnóstico completo.
        return [_resultado_error(
            "GET página de resultados (fingerprint Chrome)",
            BASE_URL,
            f"curl_cffi no está instalado ({e}) — "
            "instalar con 'pip install curl-cffi' para correr esta sonda",
        )]

    inicio = datetime.now(timezone.utc)
    try:
        resp = cffi_requests.get(
            BASE_URL,
            headers={"User-Agent": USER_AGENT},
            impersonate="chrome",
            timeout=TIMEOUT,
        )
    except Exception as e:
        return [_resultado_error(
            "GET página de resultados (fingerprint Chrome)",
            BASE_URL,
            f"{type(e).__name__}: {e}",
            ms=int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000),
        )]

    cuerpo = resp.text or ""
    return [{
        "nombre": "GET página de resultados (fingerprint Chrome)",
        "url": BASE_URL,
        "status": resp.status_code,
        "headers": dict(resp.headers),
        "body": cuerpo[:BODY_SNIPPET],
        "body_len": len(cuerpo),
        "tiene_csrf": "csrfToken" in cuerpo,
        "error": None if 200 <= resp.status_code < 300 else f"HTTP {resp.status_code}",
        "ms": int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000),
    }]


async def _playwright_probe():
    """Replica el flujo real del scraper: Chromium, token CSRF y POST a la API.

    Es la única sonda que prueba el camino completo. Un 200 en el GET no basta:
    el WAF puede servir la página y luego rechazar la API, así que se exige que
    el JSON traiga `results` con contenido.
    """
    from playwright.async_api import async_playwright

    res = {
        "nombre": "Chromium real: GET + CSRF + POST API",
        "url": API_URL,
        "status": None,
        "headers": {},
        "body": "",
        "body_len": 0,
        "tiene_csrf": False,
        "error": None,
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=USER_AGENT,
                ignore_https_errors=True,
            )
            page = await context.new_page()
            page.set_default_timeout(TIMEOUT * 1000)

            navegacion = await page.goto(BASE_URL, wait_until="domcontentloaded")
            res["status_get"] = navegacion.status if navegacion else None

            html = await page.content()
            token = await page.evaluate(
                "document.querySelector('input[name=\"csrfToken\"]')?.value"
            )
            if not token:
                for patron in [
                    r'csrfToken["\']\s*[:=]\s*["\']([a-zA-Z0-9]+)["\']',
                    r'"csrfToken"\s*:\s*"([^"]+)"',
                ]:
                    m = re.search(patron, html)
                    if m:
                        token = m.group(1)
                        break

            res["tiene_csrf"] = bool(token)
            if not token:
                # Sin token no se puede ni intentar el POST; el GET ya dice bastante.
                res["status"] = res["status_get"]
                res["body"] = html[:BODY_SNIPPET]
                res["body_len"] = len(html)
                res["error"] = "No se encontró token CSRF en el HTML servido"
                return res

            resp = await page.request.post(
                API_URL,
                data={
                    "gameId": GAME_ID,
                    "drawId": SORTEO_CANARIO,
                    "csrfToken": token,
                },
                headers={
                    "x-requested-with": "XMLHttpRequest",
                    "Origin": "https://www.polla.cl",
                    "Referer": BASE_URL,
                },
            )
            cuerpo = await resp.text()
            res["status"] = resp.status
            res["headers"] = dict(resp.headers)
            res["body"] = cuerpo[:BODY_SNIPPET]
            res["body_len"] = len(cuerpo)
            if not (200 <= resp.status < 300):
                res["error"] = f"HTTP {resp.status}"

            try:
                datos = json.loads(cuerpo)
                res["tiene_results"] = bool(datos.get("results"))
            except (json.JSONDecodeError, AttributeError):
                res["tiene_results"] = False
            return res
        finally:
            await browser.close()


def probe_playwright():
    """Envuelve la sonda async para que tenga la misma firma que las demás."""
    inicio = datetime.now(timezone.utc)
    try:
        import playwright  # noqa: F401
    except ImportError as e:
        return [_resultado_error(
            "Chromium real: GET + CSRF + POST API",
            API_URL,
            f"playwright no está instalado ({e}) — "
            "instalar con 'pip install playwright && playwright install chromium'",
        )]

    try:
        res = asyncio.run(_playwright_probe())
    except Exception as e:
        # Falta el binario de Chromium, timeout de navegación, red caída…
        return [_resultado_error(
            "Chromium real: GET + CSRF + POST API",
            API_URL,
            f"{type(e).__name__}: {e}",
            ms=int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000),
        )]

    res.setdefault("ms", int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000))
    return [res]


PROBES = {
    "directo": probe_directo,
    "movil": probe_movil,
    "impersonate": probe_impersonate,
    "playwright": probe_playwright,
    "relay": probe_relay,
    "scrapingant": probe_scrapingant,
}

# Sondas que corren cuando no se pide ninguna en concreto. 'scrapingant' queda
# fuera a propósito: gasta créditos de un free tier limitado, y el diagnóstico se
# corre a menudo para comparar clientes, donde esa sonda no aporta nada.
PROBES_POR_DEFECTO = [p for p in PROBES if p != "scrapingant"]


def imprimir(nombre_probe, resultados):
    print(f"\n{'=' * 70}")
    print(f"SONDA: {nombre_probe}")
    print("=" * 70)
    for r in resultados:
        estado = r.get("status")
        marca = "OK " if estado and 200 <= estado < 300 else "XX "
        print(f"\n{marca}{r.get('nombre', r['url'])}")
        print(f"    url:    {r['url']}")
        print(f"    status: {estado}   ({r['ms']} ms)")
        if r.get("status_upstream") is not None:
            print(f"    status polla.cl (dentro del relay): {r['status_upstream']}")
        if r.get("error"):
            print(f"    error:  {r['error']}")
        if r.get("status_get") is not None:
            print(f"    status GET página: {r['status_get']}")
        if r.get("tiene_csrf"):
            print("    csrf:   token CSRF presente en el HTML")
        if "tiene_results" in r:
            print(f"    results: {'JSON con resultados reales' if r['tiene_results'] else 'sin resultados en el JSON'}")
        pistas = sorted(set(_pistas_waf(r)) | set(r.get("pistas_extra") or []))
        if pistas:
            print(f"    WAF:    {', '.join(pistas)}")
        interesantes = ["server", "cf-ray", "x-cache", "content-type", "location"]
        for k, v in r.get("headers", {}).items():
            if k.lower() in interesantes:
                print(f"    {k}: {v}")
        if r.get("body"):
            cuerpo = r["body"].replace("\n", " ")[:300]
            print(f"    body ({r['body_len']}b): {cuerpo}")


def veredicto(todo):
    """Traduce las sondas a la conclusión que decide el diseño.

    Solo opina sobre las sondas que realmente corrieron: afirmar "no responde"
    sobre algo que no se midió es precisamente el error que este diagnóstico
    existe para corregir.
    """
    print(f"\n{'=' * 70}")
    print("VEREDICTO")
    print("=" * 70)

    # Las tres sondas de cliente salen por la misma IP. Cruzarlas es lo que separa
    # "bloqueo por reputación de IP" de "bloqueo por cómo se ve el cliente", y esa
    # distinción decide si hace falta relay (y cuentas en terceros) o no.
    def _estado(nombre):
        """'ok' / 'rechazo' / 'sin_medir' — o None si la sonda no se ejecutó."""
        if nombre not in todo:
            return None
        rs = todo[nombre]
        if any(r.get("status") and 200 <= r["status"] < 300 for r in rs):
            return "ok"
        if all(r.get("status") is None for r in rs):
            return "sin_medir"
        return "rechazo"

    e_directo = _estado("directo")
    e_imp = _estado("impersonate")
    e_pw = _estado("playwright")

    if "directo" in todo:
        directo = todo["directo"]
        directo_ok = any(r.get("status") == 200 for r in directo)
        waf = sorted({p for r in directo for p in _pistas_waf(r)})

        # Un fallo de transporte (DNS, túnel, timeout) no es lo mismo que un
        # rechazo de polla.cl: si nunca llegamos a hablar con el servidor, no
        # sabemos nada sobre su política de bloqueo.
        sin_conexion = all(r.get("status") is None for r in directo)

        if directo_ok:
            print("polla.cl RESPONDE directo desde esta IP.")
            print("  → Si esto corrió en Actions, el bloqueo ya no existe y no hace")
            print("    falta relay: basta reactivar scrape-loto.yml.")
        elif sin_conexion:
            print("NO se pudo establecer conexión con polla.cl — ninguna petición")
            print("obtuvo respuesta HTTP.")
            print(f"  → Error: {directo[0].get('error')}")
            print("  → Esto NO prueba que polla.cl bloquee: puede ser la red desde")
            print("    donde se ejecuta (proxy, DNS, firewall). Correr en Actions")
            print("    para obtener un resultado concluyente.")
        else:
            print("polla.cl NO responde directo desde esta IP (rechazo con respuesta HTTP).")
            if waf:
                print(f"  → Firma de WAF detectada: {', '.join(waf)}.")
            if e_imp is not None or e_pw is not None:
                # Con otra sonda desde la misma IP, la causa la decide el cruce de
                # más abajo; opinar aquí sería adelantarse al dato.
                print("  → La causa (IP vs. cliente) la decide la comparación de abajo.")
            elif waf:
                print("    Un relay serverless probablemente NO baste: el WAF mira más")
                print("    que la IP. Habría que revisar fingerprint TLS / challenge JS.")
            else:
                print("  → Sin firma de WAF: parece filtro por rango de IP.")
                print("    Correr también --probe impersonate y --probe playwright para")
                print("    descartar que el bloqueo sea por fingerprint del cliente.")

    if "movil" in todo:
        movil_ok = [r for r in todo["movil"]
                    if r.get("status") and 200 <= r["status"] < 300]
        if movil_ok:
            print(f"\nHAY endpoint móvil que responde ({len(movil_ok)}):")
            for r in movil_ok:
                print(f"  - {r['url']}")
            print("  → Camino gratis y sin terceros. Priorizar sobre el relay.")
        else:
            print("\nNingún endpoint móvil candidato respondió.")

    if e_imp or e_pw:
        print("\nComparación de clientes desde la misma IP:")
        for etiqueta, estado in (("directo (urllib)", e_directo),
                                 ("impersonate (TLS de Chrome)", e_imp),
                                 ("playwright (Chromium real)", e_pw)):
            if estado is not None:
                print(f"  - {etiqueta}: {estado}")

    if e_imp == "sin_medir":
        print("\nLa sonda 'impersonate' no llegó a medir nada (dependencia ausente o")
        print("red caída). Sin ese dato no se puede descartar el fingerprint.")
    if e_pw == "sin_medir":
        print("\nLa sonda 'playwright' no llegó a medir nada (dependencia, browser o")
        print("red). Sin ese dato no se puede descartar el fingerprint.")

    if e_directo == "rechazo" and e_imp == "ok":
        print("\nCONCLUSIÓN: el bloqueo es por FINGERPRINT del cliente, NO por IP.")
        print("  → La IP de Azure sirve. Basta cambiar el cliente HTTP a curl_cffi")
        print("    con impersonate='chrome'. No hacen falta relay ni cuentas en terceros.")
    elif e_directo == "rechazo" and e_imp == "rechazo" and e_pw == "ok":
        print("\nCONCLUSIÓN: hace falta un NAVEGADOR REAL, pero la IP de Azure sirve.")
        print("  → Correr Playwright dentro de Actions (como ya hace el scraper en")
        print("    local). Sin relay ni cuentas en terceros.")
    elif e_directo == "rechazo" and e_imp == "rechazo" and e_pw == "rechazo":
        print("\nCONCLUSIÓN: es REPUTACIÓN DE IP — ni el fingerprint de Chrome ni un")
        print("Chromium real pasan desde aquí.")
        print("  → Hay que salir por otra IP (relay serverless). Y el relay debe")
        print("    además imitar fingerprint de navegador, porque un fetch plano")
        print("    tampoco bastó desde esta IP.")

    if "relay" in todo:
        relay = todo["relay"]
        if any(r.get("status_upstream") == 200 for r in relay):
            print("\nEl relay SÍ alcanza polla.cl. Hipótesis confirmada.")
        elif (relay[0].get("error") or "").startswith("RELAY_URL"):
            print("\nRelay no probado (falta desplegarlo y definir RELAY_URL).")
        else:
            print("\nEl relay NO alcanza polla.cl. Probar otra plataforma.")

    if "scrapingant" in todo:
        ant = todo["scrapingant"][0]
        status = ant.get("status")
        pais = ant.get("pais")

        def _salvedad_pais():
            """Advierte que el fallo puede ser del país elegido, si se eligió uno.

            Sin país configurado la sonda salió por el pool global y esta salvedad
            no aplica: imprimirla ahí sugeriría una causa que no existe.
            """
            if not pais:
                return
            print(f"  → OJO: la sonda salió con proxy_country={pais}. El resultado")
            print("    puede deberse a esa geografía y no a la vía residencial en sí.")
            print("    Reintentar SIN SCRAPINGANT_COUNTRY (pool global) o con otro país")
            print("    antes de dar por muerta la opción. Chile no está disponible.")

        pistas = sorted(set(_pistas_waf(ant)) | set(ant.get("pistas_extra") or []))
        ok_http = bool(status and 200 <= status < 300)
        con_browser = bool(ant.get("browser"))
        cuerpo_ant = (ant.get("body") or "").lower()

        if status is None:
            # Ni siquiera hubo respuesta: sin key, sin red o timeout. No dice nada
            # sobre polla.cl, así que no se opina sobre la vía residencial.
            print("\nScrapingAnt no llegó a medir nada.")
            print(f"  → {ant.get('error')}")
        elif ok_http and ant.get("tiene_csrf"):
            # El csrfToken manda sobre la firma de WAF, y no al revés: las páginas
            # legítimas de un sitio con Imperva suelen incluir igualmente scripts
            # `_Incapsula_Resource`. Lo que no puede falsificar una página de
            # bloqueo es el token CSRF de la página real.
            print("\nLa vía del PROXY RESIDENCIAL FUNCIONA: ScrapingAnt devolvió la")
            print("página real de polla.cl (con token CSRF).")
            print("  → Siguiente paso: enchufar scraper_polla.py a ScrapingAnt y")
            print("    activar scrape-loto.yml. Ojo con el presupuesto de créditos.")
        elif ok_http and pistas:
            print("\nScrapingAnt respondió 200 pero el contenido es una página de")
            print(f"BLOQUEO ({', '.join(pistas)}), no polla.cl. Esto es un FALLO.")
            print("  → El proxy residencial NO basta: el bloqueo mira algo más que")
            print("    la IP. Habría que probar el modo navegador de ScrapingAnt o")
            print("    replantear la vía entera.")
            _salvedad_pais()
        elif ok_http:
            print("\nScrapingAnt respondió 200 pero sin token CSRF ni firma de WAF")
            print("reconocible. No se puede concluir: revisar el body del informe.")
            _salvedad_pais()
        elif status == 423:
            # 423 NO es un fallo del servicio: ScrapingAnt lo usa para decir que
            # el sitio objetivo detectó a su cliente. La petición llegó a
            # polla.cl, así que este caso SÍ informa sobre polla.cl y meterlo en
            # el saco de "key/créditos/parámetros" perdería el dato.
            print("\nScrapingAnt devolvió 423: el objetivo DETECTÓ a su cliente.")
            print("  → La petición SÍ llegó a polla.cl; no es problema de key,")
            print("    créditos ni parámetros.")
            if con_browser:
                print("  → Se corrió CON navegador, que es la superficie más fácil de")
                print("    detectar. Reintentar con SCRAPINGANT_BROWSER=false: el HTML")
                print("    con el csrfToken no necesita JS y gasta menos créditos.")
            else:
                print("  → Se corrió SIN navegador: ni el modo HTTP plano por IP")
                print("    residencial pasa. Queda por separar reputación de IP de")
                print("    geobloqueo: probar SCRAPINGANT_COUNTRY=br (Chile no está")
                print("    disponible). Si br también da 423, la vía residencial de")
                print("    ScrapingAnt está muerta.")
            _salvedad_pais()
        elif status in (401, 403):
            print(f"\nScrapingAnt devolvió HTTP {status} — problema de CREDENCIALES o")
            print("permisos del propio servicio (API key inválida, revocada o sin")
            print("acceso al plan que se está pidiendo).")
            print("  → Revisar el secret SCRAPINGANT_API_KEY.")
            print("  → No dice nada sobre polla.cl.")
        elif status == 402 or "credit" in cuerpo_ant or "quota" in cuerpo_ant:
            print(f"\nScrapingAnt devolvió HTTP {status} — CUOTA AGOTADA: no quedan")
            print("créditos en el free tier de este mes.")
            print("  → Esperar la renovación mensual antes de volver a sondear.")
            print("  → No dice nada sobre polla.cl.")
        elif status == 422:
            print("\nScrapingAnt devolvió 422 — PARÁMETROS inválidos.")
            print("  → La API nombra el parámetro correcto en el body del informe;")
            print("    corregirlo ahí y reintentar.")
            print("  → No dice nada sobre polla.cl.")
        else:
            print(f"\nScrapingAnt devolvió HTTP {status} — fallo genérico del propio")
            print("servicio.")
            print("  → Revisar el body del informe: la API explica el motivo ahí.")
            print("  → No dice nada sobre polla.cl todavía.")
            _salvedad_pais()

    no_corridas = [p for p in PROBES if p not in todo]
    if no_corridas:
        print(f"\n(Sondas no ejecutadas, sin conclusión: {', '.join(no_corridas)})")


def main():
    ap = argparse.ArgumentParser(description="Diagnóstico de acceso a polla.cl")
    ap.add_argument("--probe", choices=list(PROBES), action="append",
                    help="Sonda a ejecutar (repetible). Por defecto, todas.")
    ap.add_argument("--json", metavar="RUTA",
                    help="Guardar el informe crudo como JSON")
    args = ap.parse_args()

    elegidas = args.probe or list(PROBES_POR_DEFECTO)
    print(f"Diagnóstico polla.cl — {datetime.now(timezone.utc).isoformat()}")
    print(f"Sondas: {', '.join(elegidas)}")

    todo = {}
    for nombre in elegidas:
        todo[nombre] = PROBES[nombre]()
        imprimir(nombre, todo[nombre])

    veredicto(todo)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(todo, f, ensure_ascii=False, indent=2)
        print(f"\nInforme JSON en {args.json}")

    # Siempre 0: un bloqueo detectado es información, no un fallo del script.
    return 0


if __name__ == "__main__":
    sys.exit(main())
