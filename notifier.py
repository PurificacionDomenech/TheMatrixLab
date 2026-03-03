"""
notifier.py — The Matrix Lab
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Variables de entorno en Railway:

  TELEGRAM_TOKEN    → 8612499365:AAHSIfREZkEmfQE24tIdo6C2fCkZhXz2mcY
  SUPABASE_URL      → https://mscvlzxxuawwmltsdxxb.supabase.co
  SUPABASE_KEY      →eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1zY3Zsenh4dWF3d21sdHNkeHhiIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MjQ0ODc5OCwiZXhwIjoyMDg4MDI0Nzk4fQ.cpqxKZFYT2ld6LXNe0ImM9AQse9QSdwIltc412V0LWE

Opcionales (email):
  MAIL_FROM         → tu@gmail.com
  MAIL_PASSWORD     → Contraseña de aplicación Gmail
  MAIL_TO           → destinatario@email.com
  MAIL_SMTP         → smtp.gmail.com  (por defecto)
  MAIL_PORT         → 587             (por defecto)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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

# ── Leer variables de entorno ────────────────────────────────
# Acepta tanto TELEGRAM_TOKEN como TELEGRAM_BOT_TOKEN por compatibilidad
TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_TOKEN") or
    os.getenv("TELEGRAM_BOT_TOKEN") or
    ""
)
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")   # service_role key

MAIL_FROM     = os.getenv("MAIL_FROM", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_TO       = os.getenv("MAIL_TO", "")
MAIL_SMTP     = os.getenv("MAIL_SMTP", "smtp.gmail.com")
MAIL_PORT     = int(os.getenv("MAIL_PORT", "587"))

NIVEL_EMOJI = {"bullish": "🟢", "bearish": "🔴", "info": "🔵"}


# ════════════════════════════════════════════════════════════
# DIAGNÓSTICO — imprime estado al importar
# ════════════════════════════════════════════════════════════

def _log_config():
    ok_tg   = bool(TELEGRAM_TOKEN)
    ok_supa = bool(SUPABASE_URL and SUPABASE_KEY)
    ok_mail = bool(MAIL_FROM and MAIL_PASSWORD and MAIL_TO)
    logger.info(f"[notifier] Telegram token: {'✅' if ok_tg else '❌ FALTA TELEGRAM_TOKEN (o TELEGRAM_BOT_TOKEN)'}")
    logger.info(f"[notifier] Supabase:       {'✅' if ok_supa else '❌ FALTA SUPABASE_URL o SUPABASE_KEY'}")
    logger.info(f"[notifier] Email:          {'✅' if ok_mail else '⚠️  EMAIL NO CONFIGURADO (MAIL_FROM, MAIL_PASSWORD, MAIL_TO)'}")
    # También a stdout para que aparezca en logs de Railway
    print(f"[notifier] Telegram: {'OK' if ok_tg else 'FALTA TELEGRAM_TOKEN'} | "
          f"Supabase: {'OK' if ok_supa else 'FALTA SUPABASE_URL/KEY'} | "
          f"Email: {'OK' if ok_mail else 'NO CONFIGURADO'}")

_log_config()


# ════════════════════════════════════════════════════════════
# SUPABASE — suscriptores
# ════════════════════════════════════════════════════════════

def _supa_headers():
    return {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
    }

async def get_chat_ids() -> list[int]:
    """Devuelve todos los chat_id registrados en telegram_subs."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[notifier] get_chat_ids: Supabase no configurado")
        return []
    url = f"{SUPABASE_URL}/rest/v1/telegram_subs?select=chat_id"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=_supa_headers())
            if r.status_code == 200:
                data = r.json()
                ids  = [row["chat_id"] for row in data if row.get("chat_id")]
                print(f"[notifier] Supabase: {len(ids)} suscriptor(es)")
                return ids
            else:
                print(f"[notifier] Supabase error {r.status_code}: {r.text[:200]}")
                return []
    except Exception as e:
        print(f"[notifier] Supabase excepción: {e}")
        return []


async def register_chat(chat_id: int, username: str = "") -> bool:
    """Upsert de un chat_id en telegram_subs."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    url     = f"{SUPABASE_URL}/rest/v1/telegram_subs"
    headers = {**_supa_headers(), "Prefer": "resolution=merge-duplicates"}
    payload = {"chat_id": chat_id, "username": username or ""}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, headers=headers, json=payload)
            ok = r.status_code in (200, 201)
            print(f"[notifier] register_chat {chat_id}: {'OK' if ok else r.status_code + ' ' + r.text[:100]}")
            return ok
    except Exception as e:
        print(f"[notifier] register_chat excepción: {e}")
        return False


# ════════════════════════════════════════════════════════════
# TELEGRAM
# ════════════════════════════════════════════════════════════

async def send_telegram_to(chat_id: int, text: str) -> bool:
    if not TELEGRAM_TOKEN:
        print("[notifier] send_telegram_to: TELEGRAM_TOKEN vacío")
        return False
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            d = r.json()
            if not d.get("ok"):
                print(f"[notifier] Telegram error chat {chat_id}: {d.get('description')}")
            return d.get("ok", False)
    except Exception as e:
        print(f"[notifier] Telegram excepción chat {chat_id}: {e}")
        return False


async def broadcast_telegram(text: str, chat_ids: list[int]) -> int:
    """Envía a todos los suscriptores. Devuelve cuántos OK."""
    ok = 0
    for cid in chat_ids:
        if await send_telegram_to(cid, text):
            ok += 1
        await asyncio.sleep(0.05)
    return ok


# ════════════════════════════════════════════════════════════
# EMAIL (opcional)
# ════════════════════════════════════════════════════════════

def _send_smtp_sync(subject: str, body_html: str) -> bool:
    try:
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = MAIL_FROM
        msg["To"]      = MAIL_TO
        msg.attach(MIMEText(body_html, "html"))
        port = int(MAIL_PORT)
        if port == 465:
            with smtplib.SMTP_SSL(MAIL_SMTP, port, timeout=10) as s:
                s.login(MAIL_FROM, MAIL_PASSWORD)
                s.sendmail(MAIL_FROM, MAIL_TO, msg.as_string())
        else:
            with smtplib.SMTP(MAIL_SMTP, port, timeout=10) as s:
                s.starttls()
                s.login(MAIL_FROM, MAIL_PASSWORD)
                s.sendmail(MAIL_FROM, MAIL_TO, msg.as_string())
        print("[notifier] Email enviado OK")
        return True
    except Exception as e:
        print(f"[notifier] Email error: {e}")
        return False


# ════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL
# ════════════════════════════════════════════════════════════

async def notify_alertas(alertas: list[dict], source: str = "") -> None:
    if not alertas:
        return

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    titulo  = f"⬡ Matrix Lab · {(source + ' · ') if source else ''}{now_str}"

    # ── Texto para Telegram ──────────────────────────────────
    lineas = [f"<b>{titulo}</b>\n"]
    for a in alertas:
        emoji = NIVEL_EMOJI.get(a.get("nivel", "info"), "⚪")
        lineas.append(f"{emoji} {a['msg']}")
    texto_tg = "\n".join(lineas)

    # ── Broadcast Telegram ───────────────────────────────────
    if TELEGRAM_TOKEN:
        chat_ids = await get_chat_ids()
        if chat_ids:
            enviados = await broadcast_telegram(texto_tg, chat_ids)
            print(f"[notifier] Broadcast: {enviados}/{len(chat_ids)} enviados")
        else:
            print("[notifier] Sin suscriptores en telegram_subs — nadie recibe el mensaje")
    else:
        print("[notifier] TELEGRAM_TOKEN no configurado — skip Telegram")

    # ── Email ────────────────────────────────────────────────
    if MAIL_FROM and MAIL_PASSWORD and MAIL_TO:
        color_map  = {"bullish": "#00cc33", "bearish": "#ff3333", "info": "#4da6ff"}
        filas_html = ""
        for a in alertas:
            color = color_map.get(a.get("nivel", "info"), "#888")
            emoji = NIVEL_EMOJI.get(a.get("nivel", "info"), "⚪")
            filas_html += (
                f'<tr><td style="padding:6px 10px;border-bottom:1px solid #1a2a1a;'
                f'color:{color};font-family:monospace;font-size:13px;">'
                f'{emoji} {a["msg"]}</td></tr>'
            )
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
        await loop.run_in_executor(None, _send_smtp_sync, titulo, body_html)
