"""
sondeo_fuentes_loto.py
Sondea fuentes ALTERNATIVAS a polla.cl para los resultados de Loto. No escribe
datos del juego: solo mide y reporta.

Existe por el resultado del diagnóstico corrido en GitHub Actions: polla.cl
devuelve 403 de Imperva/Incapsula a las tres sondas (urllib, curl_cffi con
fingerprint de Chrome y Chromium real vía Playwright). Mismo bloqueo con
cualquier cliente => es reputación de IP y no se arregla cambiando de cliente.

Plan B: sacar al menos los NÚMEROS del sorteo desde un sitio que no esté detrás
de ese WAF, y dejar los premios para el backfill local
(`scripts/backfill_loto_premio.py`), que sí funciona desde la máquina del usuario.

Lo que decide si una fuente sirve no es que responda 200, sino que traiga los
datos CORRECTOS. Por eso cada candidato se contrasta contra la última fila de
`data/polla_historial.csv`, que es la verdad de referencia del propio repo.

Uso:
    python scripts/sondeo_fuentes_loto.py
    python scripts/sondeo_fuentes_loto.py --json sondeo.json
    python scripts/sondeo_fuentes_loto.py --sorteo 5476   # contrastar contra otro

El exit code es 0 siempre: un sitio caído o que no trae los datos es información
del sondeo, no un fallo de ejecución.
"""

import argparse
import csv
import html as html_mod
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

CSV_HISTORIAL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "polla_historial.csv",
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

TIMEOUT = 30
BODY_SNIPPET = 400
# Un request por candidato y una pausa entre ellos: el sondeo no debe parecer
# (ni ser) un scraping agresivo contra sitios de terceros.
DELAY_ENTRE_CANDIDATOS = 2.0

# Sitios que publican resultados de Loto chileno. Lista editable: añadir o quitar
# aquí es todo lo que hace falta para ampliar el sondeo.
CANDIDATOS_SITIOS = [
    "https://www.prensadigital.cl/resultados-loto",
    "https://lotero.cl/resultados-loto/",
    "https://resultadoslotohoy.com/",
    "https://resultados-de-loteria.com/loto-chile/resultados",
    "https://www.openloto.cl/resultados-del-loto.html",
    "https://resultadoslotochile.com/resultados-loto/",
    "https://www.chileinforma.cl/consultar-resultados-loto-hoy/",
]

# Feeds del propio polla.cl. Se sondean aparte porque son un caso distinto: si
# alguno responde, sería el MEJOR resultado posible (fuente oficial, sin
# terceros). Los feeds a veces se sirven desde otra ruta o regla del WAF que el
# HTML, así que vale la pena medirlo aunque el HTML dé 403. No está documentado
# que existan: un 404 aquí es un resultado informativo, no un error.
CANDIDATOS_FEEDS = [
    "https://www.polla.cl/rss",
    "https://www.polla.cl/es/rss",
    "https://www.polla.cl/feed",
    "https://www.polla.cl/es/view/resultados/rss",
]

TERMINOS_PREMIOS = [
    "recargado", "revancha", "desquite", "ganadores", "acertantes",
    "aciertos", "pozo", "premio",
]


# --------------------------------------------------------------------------
# Verdad de referencia
# --------------------------------------------------------------------------

def leer_referencia(ruta=CSV_HISTORIAL, sorteo=None):
    """Última fila (o la del sorteo pedido) de polla_historial.csv.

    Se lee del CSV y no se hardcodea para que el sondeo siga sirviendo cuando el
    historial avance: contrastar contra un sorteo viejo mediría si el sitio tiene
    archivo, no si publica el resultado más reciente.
    """
    if not os.path.exists(ruta):
        return None, f"No existe {ruta}"

    with open(ruta, "r", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    if not filas:
        return None, f"{ruta} está vacío"

    if sorteo is not None:
        elegidas = [r for r in filas if (r.get("sorteo") or "").strip() == str(sorteo)]
        if not elegidas:
            return None, f"El sorteo {sorteo} no está en {ruta}"
        fila = elegidas[-1]
    else:
        fila = filas[-1]

    try:
        numeros = [int(fila[f"LOTO_n{i}"]) for i in range(1, 7)]
    except (KeyError, ValueError) as e:
        return None, f"Fila sin números de Loto utilizables: {e}"

    comodin = None
    crudo = (fila.get("LOTO_comodin") or "").strip()
    if crudo:
        try:
            comodin = int(crudo)
        except ValueError:
            comodin = None

    fecha = (fila.get("fecha") or "").strip()
    return {
        "sorteo": (fila.get("sorteo") or "").strip(),
        "fecha": fecha,
        "fecha_dia": fecha.split(" ")[0] if fecha else "",
        "numeros": numeros,
        "comodin": comodin,
    }, None


# --------------------------------------------------------------------------
# Transporte
# --------------------------------------------------------------------------

def _resultado_error(url, tipo, error, ms=0):
    """Resultado con forma de sonda para fallos previos a cualquier respuesta.

    `status` None significa "no se midió el contenido", que el informe trata
    distinto de "respondió pero no trae los datos". Confundir esas dos cosas es
    justo el error que este sondeo existe para evitar.
    """
    return {
        "url": url,
        "tipo": tipo,
        "status": None,
        "headers": {},
        "body": "",
        "body_len": 0,
        "error": error,
        "ms": ms,
    }


def _pistas_waf(res):
    """Firma de WAF conocido en headers o cuerpo. Mismo criterio que
    diagnostico_polla.py: un 403 con firma de WAF y uno sin ella llevan a
    soluciones distintas."""
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


def pedir(url, tipo):
    """Un GET con fingerprint de Chrome. Devuelve siempre un dict.

    Se usa curl_cffi porque varios de estos sitios están tras Cloudflare y un
    cliente con fingerprint de Python se lleva un challenge que no dice nada
    sobre si el sitio tiene o no los datos.
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError as e:
        return _resultado_error(
            url, tipo,
            f"curl_cffi no está instalado ({e}) — 'pip install curl-cffi'",
        )

    inicio = datetime.now(timezone.utc)
    try:
        resp = cffi_requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-CL,es;q=0.9",
            },
            impersonate="chrome",
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except Exception as e:
        return _resultado_error(
            url, tipo, f"{type(e).__name__}: {e}",
            ms=int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000),
        )

    cuerpo = resp.text or ""
    return {
        "url": url,
        "url_final": str(getattr(resp, "url", url)),
        "tipo": tipo,
        "status": resp.status_code,
        "headers": dict(resp.headers),
        "body": cuerpo[:BODY_SNIPPET],
        "body_len": len(cuerpo),
        "error": None if 200 <= resp.status_code < 300 else f"HTTP {resp.status_code}",
        "ms": int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000),
        "_texto": cuerpo,
    }


# --------------------------------------------------------------------------
# Verificación de contenido
# --------------------------------------------------------------------------

def _a_texto(documento):
    """HTML/XML → texto plano aproximado. Sin dependencias: quita script/style,
    etiquetas y desescapa entidades. Es suficiente para buscar números y
    palabras clave; no pretende reconstruir la estructura."""
    txt = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", documento)
    txt = re.sub(r"(?s)<!--.*?-->", " ", txt)
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)
    txt = html_mod.unescape(txt)
    return re.sub(r"\s+", " ", txt)


# Heurística de números (tres filtros encadenados, cada uno tapa un falso
# positivo del anterior):
#
#  1. Se tokeniza el texto en enteros sueltos y se busca una VENTANA CORTA de
#     tokens consecutivos que contenga los 6 números del sorteo. Buscar cada
#     número por separado da falsos positivos garantizados: "4" o "18" aparecen
#     en cualquier página (fechas, precios, menús).
#  2. La ventana debe caber en pocos caracteres (SPAN_MAX_CHARS). Seis números
#     desperdigados en dos párrafos no son una fila de bolitas.
#  3. En el entorno de esa ventana debe aparecer la palabra "loto". Sin esto, un
#     texto cualquiera con "4 ... 18 ... 20 ... 21 ... 33 ... 41" seguidos (muy
#     posible en tablas, precios o listados) pasaría como si publicara el sorteo.
#
# Limitaciones conocidas y aceptadas:
#  - Si el sitio intercala mucho markup numérico entre las bolitas (ids, montos),
#    la ventana no los agrupa y da falso negativo. Por eso también se reporta
#    `numeros_presentes` (conteo suelto), que sirve de señal débil de respaldo.
#  - Un sitio que renderiza los números por JavaScript no los tiene en el HTML:
#    saldrá negativo aunque a ojo humano el sitio sí los muestre. Eso es correcto
#    para nuestro fin (queremos scrapearlo sin navegador), pero no es lo mismo
#    que "el sitio no publica el dato".
#  - El filtro 3 asume que la página menciona "loto" en castellano cerca de los
#    números. Una página que solo pinte las bolitas, sin texto, daría negativo.
VENTANA_TOKENS = 12
SPAN_MAX_CHARS = 200
CONTEXTO_CHARS = 400


def _tokens_enteros(texto):
    """[(valor, offset)] de los enteros de hasta 3 dígitos del texto."""
    return [(int(m.group()), m.start())
            for m in re.finditer(r"\d+", texto) if len(m.group()) <= 3]


def verificar_contenido(documento, ref):
    """Contrasta el documento servido contra el sorteo de referencia."""
    texto = _a_texto(documento)
    bajo = texto.lower()
    pares = _tokens_enteros(texto)
    valores = [v for v, _ in pares]
    objetivo = set(ref["numeros"])

    # Ventana deslizante + span acotado + contexto con "loto" (ver comentario arriba)
    secuencia = False
    for i in range(len(pares)):
        ventana = pares[i:i + VENTANA_TOKENS]
        if len(ventana) < len(objetivo):
            break
        if not objetivo.issubset({v for v, _ in ventana}):
            continue
        ini, fin = ventana[0][1], ventana[-1][1]
        if fin - ini > SPAN_MAX_CHARS:
            continue
        entorno = bajo[max(0, ini - CONTEXTO_CHARS):fin + CONTEXTO_CHARS]
        if "loto" in entorno:
            secuencia = True
            break

    presentes = sorted(objetivo & set(valores))

    # El número de sorteo se busca como token entero, no como substring: "5477"
    # dentro de "154778" no es una mención del sorteo.
    tiene_sorteo = False
    if ref["sorteo"]:
        tiene_sorteo = bool(re.search(rf"(?<!\d){re.escape(ref['sorteo'])}(?!\d)", texto))

    # El comodín solo se afirma si además los números cuadran: un "6" suelto en
    # una página cualquiera no es evidencia de nada.
    tiene_comodin = False
    if ref["comodin"] is not None and secuencia:
        tiene_comodin = ref["comodin"] in valores

    tiene_premios = sorted({t for t in TERMINOS_PREMIOS if t in bajo})
    hay_signo_peso = "$" in texto

    # Histórico: enlaces o menciones a OTROS números de sorteo cercanos al de
    # referencia, o paginación/selector explícitos.
    otros_sorteos = []
    if ref["sorteo"].isdigit():
        actual = int(ref["sorteo"])
        vecinos = {str(actual - k) for k in range(1, 26)}
        # Se busca en el documento CRUDO, no en el texto sin etiquetas: la
        # navegación a sorteos pasados vive en el href ("/sorteo/5476"), que
        # `_a_texto` descarta junto con el resto del markup. Buscar solo en el
        # texto visible haría que casi ninguna fuente pareciera tener histórico.
        # El riesgo inverso —un número de sorteo que aparezca por casualidad en
        # CSS o JS— es bajo: son cuatro dígitos concretos y contiguos.
        crudo = documento if isinstance(documento, str) else texto
        otros_sorteos = sorted(
            s for s in vecinos
            if re.search(rf"(?<!\d){s}(?!\d)", crudo)
        )
    marcas_historico = sorted({
        m for m in ["sorteos anteriores", "resultados anteriores", "histórico",
                    "historico", "sorteo anterior", "ver más", "paginación",
                    "archivo"]
        if m in bajo
    })

    return {
        "tiene_sorteo": tiene_sorteo,
        "tiene_numeros": secuencia,
        "numeros_presentes": presentes,
        "numeros_presentes_n": len(presentes),
        "tiene_comodin": tiene_comodin,
        "tiene_premios": bool(tiene_premios) and hay_signo_peso,
        "terminos_premios": tiene_premios,
        "signo_peso": hay_signo_peso,
        "tiene_historico": bool(otros_sorteos) or bool(marcas_historico),
        "otros_sorteos": otros_sorteos[:10],
        "marcas_historico": marcas_historico,
        "texto_len": len(texto),
    }


def puntuar(res):
    """Utilidad de un candidato, para ordenar el ranking.

    El peso está en `tiene_numeros`: sin los números correctos la fuente no
    sirve para nada, por muy completa que parezca. Sorteo, comodín, premios e
    histórico solo desempatan entre fuentes que ya sirven.
    """
    v = res.get("verificacion")
    if not v:
        return -1
    p = 0
    p += 100 if v["tiene_numeros"] else 0
    p += 25 if v["tiene_sorteo"] else 0
    p += 20 if v["tiene_comodin"] else 0
    p += 15 if v["tiene_premios"] else 0
    p += 10 if v["tiene_historico"] else 0
    p += v["numeros_presentes_n"]  # señal débil, solo para desempatar
    return p


# --------------------------------------------------------------------------
# Sondeo
# --------------------------------------------------------------------------

def sondear(urls, tipo, ref, delay=DELAY_ENTRE_CANDIDATOS):
    resultados = []
    for i, url in enumerate(urls):
        if i:
            time.sleep(delay)
        r = pedir(url, tipo)
        if r.get("status") and 200 <= r["status"] < 300:
            r["verificacion"] = verificar_contenido(r.pop("_texto", ""), ref)
        r.pop("_texto", None)
        resultados.append(r)
    return resultados


def imprimir(titulo, resultados):
    print(f"\n{'=' * 70}")
    print(titulo)
    print("=" * 70)
    for r in resultados:
        estado = r.get("status")
        marca = "OK " if estado and 200 <= estado < 300 else "XX "
        print(f"\n{marca}{r['url']}")
        print(f"    status: {estado}   ({r['ms']} ms)")
        if r.get("url_final") and r["url_final"] != r["url"]:
            print(f"    redirigió a: {r['url_final']}")
        if r.get("error"):
            print(f"    error:  {r['error']}")
        pistas = _pistas_waf(r)
        if pistas:
            print(f"    WAF:    {', '.join(pistas)}")
        ct = next((v for k, v in r.get("headers", {}).items()
                   if k.lower() == "content-type"), None)
        if ct:
            print(f"    content-type: {ct}")

        v = r.get("verificacion")
        if v:
            print(f"    numeros:   {'SÍ (los 6 agrupados)' if v['tiene_numeros'] else 'no'}"
                  f"   [sueltos: {v['numeros_presentes_n']}/6 {v['numeros_presentes']}]")
            print(f"    sorteo:    {'SÍ' if v['tiene_sorteo'] else 'no'}")
            print(f"    comodin:   {'SÍ' if v['tiene_comodin'] else 'no'}")
            print(f"    premios:   {'SÍ' if v['tiene_premios'] else 'no'}"
                  f"   {('términos: ' + ', '.join(v['terminos_premios'])) if v['terminos_premios'] else ''}")
            print(f"    historico: {'SÍ' if v['tiene_historico'] else 'no'}"
                  f"   {('otros sorteos: ' + ', '.join(v['otros_sorteos'])) if v['otros_sorteos'] else ''}")
            print(f"    texto: {v['texto_len']}b")
        elif estado is None:
            print("    (no se midió contenido: no hubo respuesta HTTP)")
        else:
            print("    (no se midió contenido: el sitio no respondió 200)")

        if r.get("body") and not v:
            print(f"    body ({r['body_len']}b): {r['body'].replace(chr(10), ' ')[:240]}")


def ranking(todo, ref):
    """Ordena por utilidad y recomienda. Solo opina sobre lo medido."""
    print(f"\n{'=' * 70}")
    print("RANKING Y RECOMENDACIÓN")
    print("=" * 70)
    com = (f" | comodín {ref['comodin']}" if ref["comodin"] is not None
           else " | sin comodín en el CSV")
    print(f"Contrastado contra sorteo {ref['sorteo']} ({ref['fecha_dia']}): "
          f"{', '.join(str(n) for n in ref['numeros'])}{com}")

    todos = todo["sitios"] + todo["feeds"]

    sin_respuesta = [r for r in todos if r.get("status") is None]
    rechazados = [r for r in todos
                  if r.get("status") is not None and not (200 <= r["status"] < 300)]
    utiles = sorted(
        [r for r in todos if r.get("verificacion")],
        key=puntuar, reverse=True,
    )

    if sin_respuesta:
        print(f"\nSin respuesta HTTP ({len(sin_respuesta)}) — fallo de TRANSPORTE, no")
        print("del contenido. No dice nada sobre si el sitio tiene los datos:")
        for r in sin_respuesta:
            print(f"  - {r['url']}")
            print(f"      {r['error']}")
        print("  → Si esto corrió en un entorno con proxy de egreso restringido")
        print("    (p. ej. la sesión del agente), repetir en GitHub Actions.")

    if rechazados:
        print(f"\nRespondieron pero sin 200 ({len(rechazados)}):")
        for r in rechazados:
            pistas = _pistas_waf(r)
            extra = f"  [WAF: {', '.join(pistas)}]" if pistas else ""
            print(f"  - {r['url']}  → {r['status']}{extra}")

    if not utiles:
        print("\nNINGÚN candidato entregó contenido verificable en esta corrida.")
        print("  → No hay base para recomendar una fuente. Volver a correr donde")
        print("    haya salida de red real antes de concluir nada.")
        return

    print(f"\nCandidatos con contenido medido ({len(utiles)}), mejor primero:")
    for i, r in enumerate(utiles, 1):
        v = r["verificacion"]
        tiene = [k for k, ok in (("números", v["tiene_numeros"]),
                                 ("sorteo", v["tiene_sorteo"]),
                                 ("comodín", v["tiene_comodin"]),
                                 ("premios", v["tiene_premios"]),
                                 ("histórico", v["tiene_historico"])) if ok]
        falta = [k for k, ok in (("números", v["tiene_numeros"]),
                                 ("sorteo", v["tiene_sorteo"]),
                                 ("comodín", v["tiene_comodin"]),
                                 ("premios", v["tiene_premios"]),
                                 ("histórico", v["tiene_historico"])) if not ok]
        print(f"\n  {i}. [{puntuar(r)} pts] {r['url']}  ({r['tipo']})")
        print(f"     trae:  {', '.join(tiene) or '(nada verificable)'}")
        print(f"     falta: {', '.join(falta) or '(nada)'}")

    servibles = [r for r in utiles if r["verificacion"]["tiene_numeros"]]
    feeds_ok = [r for r in servibles if r["tipo"] == "feed"]

    print("\n--- Recomendación ---")
    if feeds_ok:
        print(f"USAR el feed oficial: {feeds_ok[0]['url']}")
        print("  → Es polla.cl sin el WAF de por medio: fuente oficial, sin terceros")
        print("    y sin riesgo de que un sitio intermediario cambie de formato.")
    elif servibles:
        mejor = servibles[0]
        print(f"USAR {mejor['url']}")
        print("  → Es el único/mejor que publicó en HTML los 6 números del último")
        print("    sorteo, que es el requisito mínimo para automatizar en Actions.")
    else:
        print("NINGUNA fuente medida trae los 6 números del último sorteo en el HTML.")
        print("  → No se puede recomendar ninguna. Posibles causas a descartar antes")
        print("    de descartar el plan B: render por JavaScript, o que el sorteo aún")
        print("    no esté publicado en esos sitios.")

    con_premios = [r for r in servibles if r["verificacion"]["tiene_premios"]]
    con_historico = [r for r in servibles if r["verificacion"]["tiene_historico"]]
    con_comodin = [r for r in servibles if r["verificacion"]["tiene_comodin"]]

    print("\nCobertura entre las fuentes que sí traen los números:")
    if not servibles:
        print("  (ninguna; nada que reportar)")
    else:
        print(f"  - comodín:   {len(con_comodin)}/{len(servibles)}"
              + ("" if con_comodin else "  → NINGUNA. Las categorías SUPER_* de Loto"
                                        " quedarían sin calcular."))
        print(f"  - premios:   {len(con_premios)}/{len(servibles)}"
              + ("" if con_premios else "  → NINGUNA. Habría que seguir usando"
                                        " backfill_loto_premio.py en local."))
        print(f"  - histórico: {len(con_historico)}/{len(servibles)}"
              + ("" if con_historico else "  → NINGUNA. Solo serviría para el sorteo"
                                          " recién salido, sin recuperar atrasos."))

    print("\nOjo con los indicios de premios/histórico: se detectan por palabras")
    print("clave en el texto, no extrayendo el dato. Confirman que vale la pena")
    print("mirar la fuente, no que el dato sea parseable.")


def main():
    ap = argparse.ArgumentParser(
        description="Sondeo de fuentes alternativas de resultados de Loto")
    ap.add_argument("--json", metavar="RUTA", help="Guardar el informe crudo como JSON")
    ap.add_argument("--sorteo", type=int,
                    help="Contrastar contra este sorteo en vez del último del CSV")
    ap.add_argument("--delay", type=float, default=DELAY_ENTRE_CANDIDATOS,
                    help="Segundos entre candidatos (por cortesía con los sitios)")
    args = ap.parse_args()

    print(f"Sondeo de fuentes de Loto — {datetime.now(timezone.utc).isoformat()}")

    ref, err = leer_referencia(sorteo=args.sorteo)
    if ref is None:
        print(f"\nNo hay verdad de referencia: {err}")
        print("Sin ella no se puede verificar contenido, así que el sondeo no corre.")
        return 0

    print(f"Verdad de referencia (de data/polla_historial.csv):")
    print(f"  sorteo  : {ref['sorteo']}")
    print(f"  fecha   : {ref['fecha']}")
    print(f"  LOTO    : {', '.join(str(n) for n in ref['numeros'])}")
    print(f"  comodín : {ref['comodin'] if ref['comodin'] is not None else '(vacío)'}")

    todo = {
        "referencia": ref,
        "sitios": sondear(CANDIDATOS_SITIOS, "sitio", ref, args.delay),
        "feeds": sondear(CANDIDATOS_FEEDS, "feed", ref, args.delay),
    }

    imprimir("SITIOS DE TERCEROS", todo["sitios"])
    imprimir("FEEDS/RSS DE POLLA.CL (fuente oficial, sonda aparte)", todo["feeds"])
    ranking(todo, ref)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(todo, f, ensure_ascii=False, indent=2)
        print(f"\nInforme JSON en {args.json}")

    # Siempre 0: un sitio caído o inútil es información, no un fallo del script.
    return 0


if __name__ == "__main__":
    sys.exit(main())
