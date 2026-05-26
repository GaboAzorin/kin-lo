"""
tg_notify.py
Envía mensajes al bot @LotusGaboBot via variables de entorno.

Variables requeridas (en .env local o en el entorno CI):
    TELEGRAM_BOT_TOKEN  — token del bot
    TELEGRAM_CHAT_ID    — chat_id del destinatario
"""
import json
import os
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

# Cargar .env para desarrollo local (ignorado si no existe)
_env_path = Path(__file__).resolve().parents[2] / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


def _creds() -> tuple[str | None, str | None]:
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return (token, chat_id) if (token and chat_id) else (None, None)


def send(text: str, parse_mode: str = "HTML") -> bool:
    """
    Envía un mensaje al chat configurado.
    - Retorna True si fue exitoso.
    - Retorna False silenciosamente si no hay credenciales o hay error de red.
    - No lanza excepciones (el pipeline no debe romperse por esto).
    """
    token, chat_id = _creds()
    if not token:
        return False

    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ok = r.status == 200
            if ok:
                print("  [Telegram] OK mensaje enviado")
            return ok
    except Exception as e:
        print(f"  [Telegram] Error: {e}")
        return False
