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

`directo`, `impersonate` y `playwright` salen por la MISMA IP y solo cambian el
cliente: comparándolas se separa "me bloquean por reputación de IP" de "me
bloquean por cómo me veo", que llevan a soluciones completamente distintas.

Uso:
    python scripts/diagnostico_polla.py                 # todas las sondas
    python scripts/diagnostico_polla.py --probe directo

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


def _request(url, method="GET", data=None, headers=None, timeout=TIMEOUT):
    """Ejecuta una petición y devuelve siempre un dict, incluso si falla.

    urllib levanta HTTPError para 4xx/5xx, pero aquí un 403 es justamente el dato
    que buscamos, así que se captura y se reporta como resultado normal.
    """
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)

    payload = data.encode() if isinstance(data, str) else data
    req = urllib.request.Request(url, data=payload, headers=hdrs, method=method)

    inicio = datetime.now(timezone.utc)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cuerpo = resp.read(BODY_SNIPPET * 4).decode("utf-8", errors="replace")
            return {
                "url": url,
                "status": resp.status,
                "headers": dict(resp.headers),
                "body": cuerpo[:BODY_SNIPPET],
                "body_len": len(cuerpo),
                "error": None,
                "ms": int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000),
            }
    except urllib.error.HTTPError as e:
        cuerpo = e.read(BODY_SNIPPET * 4).decode("utf-8", errors="replace")
        return {
            "url": url,
            "status": e.code,
            "headers": dict(e.headers or {}),
            "body": cuerpo[:BODY_SNIPPET],
            "body_len": len(cuerpo),
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
}


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
        pistas = _pistas_waf(r)
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

    elegidas = args.probe or list(PROBES)
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
