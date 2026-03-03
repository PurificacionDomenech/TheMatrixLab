"""
notifier.py — The Matrix Lab
Envía alertas a todos los chat_id registrados en Supabase (telegram_subs).

Variables de entorno necesarias:
  TELEGRAM_TOKEN    → Token del bot (@BotFather)
  SUPABASE_URL      → URL de tu proyecto Supabase
  SUPABASE_KEY      → service_role key (NO la anon/publishable — necesita leer la tabla)

Opcionales (email):
  MAIL_FROM         → tu@gmail.com
  MAIL_PASSWORD     → Contraseña de aplicación Gmail
  MAIL_TO           → destinatario del email
  MAIL_SMTP         → smtp.gmail.com (por defecto)
  MAIL_PORT         → 587 (por defecto)
"""

import os
import asyncio
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import httpx

logger = logging.getLogger("notifier")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
SUPABASE_URL   = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY", "")   # service_role key

MAIL_FROM     = os.getenv("MAIL_FROM", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_TO       = os.getenv("MAIL_TO", "")
MAIL_SMTP     = os.getenv("MAIL_SMTP", "smtp.gmail.com")
MAIL_PORT     = int(os.getenv("MAIL_PORT", "587"))

NIVEL_EMOJI = {"bullish": "🟢", "bearish": "🔴", "info": "🔵"}


# ════════════════════════════════════════════════════════════
# SUPABASE — obtener lista de chat_ids suscritos
# ════════════════════════════════════════════════════════════

async def get_chat_ids() -> list[int]:
    """Devuelve todos los chat_id de telegram_subs."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.warning("Supabase no configurado (SUPABASE_URL / SUPABASE_KEY)")
        return []
    url = f"{SUPABASE_URL}/rest/v1/telegram_subs?select=chat_id"
    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                data = r.json()
                ids  = [row["chat_id"] for row in data if row.get("chat_id")]
                logger.info(f"Supabase: {len(ids)} suscriptor(es)")
                return ids
            else:
                logger.error(f"Supabase error {r.status_code}: {r.text}")
                return []
    except Exception as e:
        logger.error(f"Supabase excepción: {e}")
        return []


async def register_chat(chat_id: int, username: str = "") -> bool:
    """Registra o actualiza un chat_id en telegram_subs (upsert)."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    url = f"{SUPABASE_URL}/rest/v1/telegram_subs"
    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "resolution=merge-duplicates",  # upsert
    }
    payload = {"chat_id": chat_id, "username": username}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, headers=headers, json=payload)
            return r.status_code in (200, 201)
    except Exception as e:
        logger.error(f"register_chat excepción: {e}")
        return False


# ════════════════════════════════════════════════════════════
# TELEGRAM — envío a un chat_id
# ════════════════════════════════════════════════════════════

async def send_telegram_to(chat_id: int, text: str) -> bool:
    if not TELEGRAM_TOKEN:
        return False
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            return r.status_code == 200
    except Exception as e:
        logger.error(f"Telegram excepción chat {chat_id}: {e}")
        return False


async def broadcast_telegram(text: str, chat_ids: list[int]) -> int:
    """Envía el mensaje a todos los chat_ids. Devuelve cuántos OK."""
    ok = 0
    for cid in chat_ids:
        if await send_telegram_to(cid, text):
            ok += 1
        await asyncio.sleep(0.05)   # respetar rate limit de Telegram
    return ok


# ════════════════════════════════════════════════════════════
# EMAIL (opcional)
# ════════════════════════════════════════════════════════════

def send_email(subject: str, body_html: str) -> bool:
    if not MAIL_FROM or not MAIL_PASSWORD or not MAIL_TO:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = MAIL_FROM
        msg["To"]      = MAIL_TO
        msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP(MAIL_SMTP, MAIL_PORT) as server:
            server.starttls()
            server.login(MAIL_FROM, MAIL_PASSWORD)
            server.sendmail(MAIL_FROM, MAIL_TO, msg.as_string())
        logger.info("Email OK")
        return True
    except Exception as e:
        logger.error(f"Email excepción: {e}")
        return False


# ════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL
# ════════════════════════════════════════════════════════════

async def notify_alertas(alertas: list[dict], source: str = "") -> None:
    if not alertas:
        return

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    titulo  = f"⬡ Matrix Lab · {source + ' · ' if source else ''}{now_str}"

    # ── Texto Telegram ───────────────────────────────────────
    lineas = [f"<b>{titulo}</b>\n"]
    for a in alertas:
        emoji = NIVEL_EMOJI.get(a.get("nivel", "info"), "⚪")
        lineas.append(f"{emoji} {a['msg']}")
    texto_tg = "\n".join(lineas)

    # ── Obtener suscriptores y hacer broadcast ───────────────
    if TELEGRAM_TOKEN:
        chat_ids = await get_chat_ids()
        if chat_ids:
            ok = await broadcast_telegram(texto_tg, chat_ids)
            logger.info(f"Telegram broadcast: {ok}/{len(chat_ids)} enviados")
        else:
            logger.warning("Telegram: sin suscriptores en telegram_subs")

    # ── Email ────────────────────────────────────────────────
    if MAIL_FROM and MAIL_PASSWORD and MAIL_TO:
        color_map  = {"bullish": "#00cc33", "bearish": "#ff3333", "info": "#4da6ff"}
        filas_html = ""
        for a in alertas:
            color = color_map.get(a.get("nivel", "info"), "#888")
            emoji = NIVEL_EMOJI.get(a.get("nivel", "info"), "⚪")
            filas_html += f"""
            <tr><td style="padding:6px 10px;border-bottom:1px solid #1a2a1a;
                           color:{color};font-family:monospace;font-size:13px;">
              {emoji} {a['msg']}
            </td></tr>"""

        body_html = f"""
        <html><body style="background:#000;color:#c8ffd4;font-family:sans-serif;padding:20px;">
          <div style="max-width:600px;margin:auto;background:#010801;
                      border:1px solid #00ff4120;border-radius:8px;overflow:hidden;">
            <div style="background:#010f01;padding:14px 20px;border-bottom:1px solid #00ff4115;">
              <span style="font-family:monospace;font-size:14px;color:#00ff41;font-weight:bold;">
                ⬡ THE MATRIX LAB
              </span>
              <span style="font-family:monospace;font-size:11px;color:#666;margin-left:10px;">
                {now_str}
              </span>
            </div>
            <table style="width:100%;border-collapse:collapse;">{filas_html}</table>
            <div style="padding:10px 20px;font-size:10px;color:#333;font-family:monospace;
                        border-top:1px solid #00ff4110;text-align:center;">
              Análisis técnico automatizado · No es asesoría financiera
            </div>
          </div>
        </body></html>"""

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, send_email, titulo, body_html)
