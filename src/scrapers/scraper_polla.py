"""
scraper_polla.py
Descarga resultados de Loto, Recargado, Revancha y Desquite desde polla.cl.
Solo registra n° de sorteo, fecha, día de la semana y los números de cada juego.

Basado en scraper_puro.py. Cambios:
  - Solo juego LOTO (ID 5271); Recargado/Revancha/Desquite vienen incluidos
    en additionalGameResults de la misma respuesta.
  - Salida filtrada a COLUMNS_POLLA (sin premios ni montos).
  - Rutas relativas al repositorio.
"""

import asyncio
import csv
import os
import json
import requests
import time
import re
import sys
import logging
import random
import uuid
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from zoneinfo import ZoneInfo
from playwright.async_api import async_playwright

CL_TZ = ZoneInfo("America/Santiago")

# ==============================================================================
# RUTAS
# ==============================================================================
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR  = REPO_ROOT / "data"
LOGS_DIR  = REPO_ROOT / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

CSV_OUT = DATA_DIR / "polla_historial.csv"

# ==============================================================================
# LOGGING
# ==============================================================================
logger = logging.getLogger("scraper_polla")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    fh = logging.FileHandler(
        LOGS_DIR / f"scraper_polla_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
        encoding="utf-8"
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

# ==============================================================================
# PARSERS
# ==============================================================================
sys.path.insert(0, str(REPO_ROOT / "src" / "parsers"))
try:
    from loto_parser_v3 import parse_loto_rich
    logger.info("Parser loto_parser_v3 cargado OK.")
except ImportError as e:
    logger.error(f"No se pudo importar el parser: {e}")
    raise SystemExit(1)

# ==============================================================================
# COLUMNAS DE SALIDA
# Solo guardamos sorteo, fecha, día y los números — sin premios ni montos.
# ==============================================================================
COLUMNS_POLLA = [
    "sorteo", "fecha", "dia_semana",
    # Loto principal (6 números, sin comodín)
    "LOTO_n1", "LOTO_n2", "LOTO_n3", "LOTO_n4", "LOTO_n5", "LOTO_n6",
    # Recargado
    "RECARGADO_n1", "RECARGADO_n2", "RECARGADO_n3", "RECARGADO_n4",
    "RECARGADO_n5", "RECARGADO_n6",
    # Revancha
    "REVANCHA_n1", "REVANCHA_n2", "REVANCHA_n3", "REVANCHA_n4",
    "REVANCHA_n5", "REVANCHA_n6",
    # Desquite
    "DESQUITE_n1", "DESQUITE_n2", "DESQUITE_n3", "DESQUITE_n4",
    "DESQUITE_n5", "DESQUITE_n6",
]

# ==============================================================================
# CONSTANTES
# ==============================================================================
API_URL  = "https://www.polla.cl/es/get/draw/results"
BASE_URL = "https://www.polla.cl/es/view/resultados"

SCRAPEDO_TOKENS_RAW  = os.environ.get("SCRAPEDO_TOKEN", "")
SCRAPEDO_TOKENS_LIST = [t.strip() for t in SCRAPEDO_TOKENS_RAW.split(",") if t.strip()]
USE_SCRAPEDO         = os.environ.get("USE_SCRAPEDO", "false").lower() == "true"

REQUEST_DELAY_SECONDS  = 0.5
TOKEN_REFRESH_MINUTES  = 20
MAX_CONSECUTIVE_ERRORS = 5

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Solo el juego LOTO. Recargado/Revancha/Desquite se extraen de additionalGameResults.
GAME_CONFIG = {
    "name":        "LOTO",
    "id":          "5271",
    "start_draw":  3803,
}

# ==============================================================================
# HELPERS
# ==============================================================================

def get_start_id() -> int:
    """Lee el último sorteo grabado en el CSV y devuelve el siguiente."""
    if not CSV_OUT.exists():
        return GAME_CONFIG["start_draw"]
    max_id = 0
    try:
        with open(CSV_OUT, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("sorteo", "").isdigit():
                    max_id = max(max_id, int(row["sorteo"]))
    except (IOError, csv.Error) as e:
        logger.warning(f"Error leyendo CSV: {e}")
    return max_id + 1 if max_id > 0 else GAME_CONFIG["start_draw"]


def guardar_fila(raw_row: dict):
    """Filtra a COLUMNS_POLLA y escribe al CSV (append)."""
    file_exists = CSV_OUT.exists() and CSV_OUT.stat().st_size > 10
    row = {col: raw_row.get(col, "") for col in COLUMNS_POLLA}
    with open(CSV_OUT, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS_POLLA)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


# ==============================================================================
# TOKEN CSRF
# ==============================================================================

async def obtener_token_csrf(page) -> str:
    logger.info("Obteniendo token CSRF de polla.cl...")
    await page.goto(BASE_URL, wait_until="domcontentloaded")
    await asyncio.sleep(3)

    token = await page.evaluate(
        "document.querySelector('input[name=\"csrfToken\"]')?.value"
    )
    if not token:
        content = await page.content()
        for pattern in [
            r'csrfToken["\']\s*[:=]\s*["\']([a-zA-Z0-9]+)["\']',
            r'"csrfToken"\s*:\s*"([^"]+)"',
        ]:
            m = re.search(pattern, content)
            if m:
                token = m.group(1)
                break

    if not token:
        raise RuntimeError("No se encontró token CSRF por ningún método.")
    logger.info("Token CSRF obtenido.")
    return token


def obtener_token_scrapedo() -> tuple[str, str, str]:
    """Obtiene token CSRF vía Scrape.do (modo nube)."""
    import urllib.parse
    logger.info("Obteniendo token vía Scrape.do...")
    current_token = random.choice(SCRAPEDO_TOKENS_LIST)
    encoded_url = urllib.parse.quote(BASE_URL)
    target = (
        f"http://api.scrape.do?token={current_token}"
        f"&url={encoded_url}&super=true&geoCode=cl"
    )
    resp = requests.get(target, headers={"User-Agent": USER_AGENT}, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Scrape.do error {resp.status_code}")
    content = resp.text
    token = None
    for pattern in [r'"csrfToken"\s*:\s*"([^"]+)"', r'name="csrfToken"\s+value="([^"]+)"']:
        m = re.search(pattern, content)
        if m:
            token = m.group(1)
            break
    if not token:
        raise RuntimeError("HTML descargado pero sin token visible.")
    cookies_raw = ""
    if "scrape.do-cookies" in resp.headers:
        try:
            c = SimpleCookie()
            c.load(resp.headers["scrape.do-cookies"])
            cookies_raw = "; ".join(f"{k}={v.value}" for k, v in c.items())
        except Exception:
            cookies_raw = resp.headers["scrape.do-cookies"]
    elif resp.cookies:
        cookies_raw = "; ".join(f"{c.name}={c.value}" for c in resp.cookies)
    logger.info(f"Token Scrape.do obtenido: {token[:10]}...")
    return token, current_token, cookies_raw


# ==============================================================================
# MOTOR DE SCRAPING
# ==============================================================================

async def scrape_polla(proxy_config: dict | None = None) -> bool:
    """
    Descarga todos los sorteos nuevos de Loto desde polla.cl.
    Retorna True si se guardó al menos un sorteo nuevo.
    """
    mode = "Proxy/Nube" if proxy_config else "Local"
    logger.info(f"Iniciando scraping polla.cl ({mode})...")

    current_id   = get_start_id()
    saved_any    = False
    consec_errors = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, proxy=proxy_config)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            ignore_https_errors=True,
        )
        page = await context.new_page()
        timeout_val = 90_000 if proxy_config else 30_000
        page.set_default_timeout(timeout_val)

        try:
            token = await obtener_token_csrf(page)
            token_ts = datetime.now()
        except Exception as e:
            logger.error(f"No se pudo obtener token CSRF: {e}")
            await browser.close()
            return False

        logger.info(f"Buscando sorteos desde #{current_id}...")

        while consec_errors < MAX_CONSECUTIVE_ERRORS:
            try:
                # Refrescar token si expiró
                if datetime.now() - token_ts > timedelta(minutes=TOKEN_REFRESH_MINUTES):
                    logger.info("Token expirado. Revalidando...")
                    token = await obtener_token_csrf(page)
                    token_ts = datetime.now()

                await asyncio.sleep(REQUEST_DELAY_SECONDS)

                response = await page.request.post(
                    API_URL,
                    data={
                        "gameId":    GAME_CONFIG["id"],
                        "drawId":    current_id,
                        "csrfToken": token,
                    },
                    headers={
                        "x-requested-with": "XMLHttpRequest",
                        "Origin":  "https://www.polla.cl",
                        "Referer": BASE_URL,
                    },
                )

                if response.status != 200:
                    logger.warning(f"HTTP {response.status} en sorteo #{current_id}")
                    consec_errors += 1
                    await asyncio.sleep(1)
                    continue

                try:
                    json_data = await response.json()
                except json.JSONDecodeError:
                    logger.warning(f"JSON inválido en sorteo #{current_id}")
                    consec_errors += 1
                    continue

                if not json_data or not json_data.get("results"):
                    ts = json_data.get("drawDate") if json_data else None
                    if ts and datetime.fromtimestamp(ts / 1000, tz=CL_TZ) > datetime.now(CL_TZ):
                        logger.info(f"Sorteo #{current_id} es futuro. Fin de descarga.")
                        break
                    consec_errors += 1
                    continue

                try:
                    raw_row = parse_loto_rich(json_data)
                except Exception as e:
                    logger.warning(f"Error parseando #{current_id}: {e}")
                    consec_errors += 1
                    continue

                # Agregar dia_semana si el parser no lo incluyó con ese nombre exacto
                if "dia_semana" not in raw_row and "fecha" in raw_row:
                    try:
                        dt = datetime.strptime(raw_row["fecha"][:10], "%Y-%m-%d")
                        raw_row["dia_semana"] = dt.strftime("%A")
                    except Exception:
                        raw_row["dia_semana"] = ""

                guardar_fila(raw_row)
                logger.info(
                    f"#{raw_row.get('sorteo')} guardado — "
                    f"{raw_row.get('fecha','?')} ({raw_row.get('dia_semana','?')})"
                )
                saved_any    = True
                current_id  += 1
                consec_errors = 0

            except Exception as e:
                logger.error(f"Excepción en sorteo #{current_id}: {e}")
                consec_errors += 1
                await asyncio.sleep(1)

        await browser.close()

    if saved_any:
        logger.info("✓ Scraping completado con sorteos nuevos.")
    else:
        logger.info("Sin sorteos nuevos.")
    return saved_any


# ==============================================================================
# ENTRADA PRINCIPAL
# ==============================================================================

async def main():
    if USE_SCRAPEDO:
        if not SCRAPEDO_TOKENS_LIST:
            logger.error("USE_SCRAPEDO=true pero SCRAPEDO_TOKEN no está configurado.")
            return
        token = random.choice(SCRAPEDO_TOKENS_LIST)
        session_id = str(uuid.uuid4())[:8]
        proxy_config = {
            "server":   "http://proxy.scrape.do:8080",
            "username": f"{token}-session={session_id}-super=true",
            "password": "",
        }
        logger.info(f"Modo Nube | session={session_id}")
    else:
        proxy_config = None
        logger.info("Modo Local (sin proxy)")

    await scrape_polla(proxy_config=proxy_config)


if __name__ == "__main__":
    asyncio.run(main())
