import os
import asyncio
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import httpx

logger = logging.getLogger("notifier")

# Configuración desde variables de entorno
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or ""
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

MAIL_FROM = os.getenv("MAIL_FROM", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_SMTP = os.getenv("MAIL_SMTP", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))

NIVEL_EMOJI = {"bullish": "🟢", "bearish": "🔴", "info": "🔵"}

def _supa_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

async def get_subscribers() -> list[dict]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    url = f"{SUPABASE_URL}/rest/v1/telegram_subs?select=*"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=_supa_headers())
            if r.status_code == 200:
                return r.json()
            return []
    except Exception as e:
        print(f"[notifier] Error get_subscribers: {e}")
        return []

async def register_chat(chat_id: int, username: str = "", email: str = None) -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    url = f"{SUPABASE_URL}/rest/v1/telegram_subs"
    headers = {**_supa_headers(), "Prefer": "resolution=merge-duplicates"}
    payload = {
        "chat_id": chat_id, 
        "username": username or "", 
        "email": email, 
        "receive_email": bool(email)
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, headers=headers, json=payload)
            return r.status_code in (200, 201)
    except Exception as e:
        print(f"[notifier] Error register_chat: {e}")
        return False

async def unregister_chat(chat_id: int) -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    url = f"{SUPABASE_URL}/rest/v1/telegram_subs?chat_id=eq.{chat_id}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.delete(url, headers=_supa_headers())
            return r.status_code == 204
    except Exception as e:
        print(f"[notifier] Error unregister_chat: {e}")
        return False

async def send_telegram_to(chat_id: int, text: str) -> bool:
    if not TELEGRAM_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            return r.json().get("ok", False)
    except Exception:
        return False

def _send_smtp_sync(subject: str, body_html: str, mail_to: str) -> bool:
    if not all([MAIL_FROM, MAIL_PASSWORD, mail_to]):
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"], msg["From"], msg["To"] = subject, MAIL_FROM, mail_to
        msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP(MAIL_SMTP, MAIL_PORT, timeout=10) as s:
            s.starttls()
            s.login(MAIL_FROM, MAIL_PASSWORD)
            s.sendmail(MAIL_FROM, mail_to, msg.as_string())
        return True
    except Exception as e:
        print(f"[notifier] Email error a {mail_to}: {e}")
        return False

async def notify_alertas(alertas: list[dict], source: str = "", chat_id: int = None) -> None:
    if not alertas:
        return
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    titulo = f"⬡ Matrix Lab · {(source + ' · ') if source else ''}{now_str}"
    
    # Texto Telegram
    lines = [f"<b>{titulo}</b>\n"]
    for a in alertas:
        lines.append(f"{NIVEL_EMOJI.get(a.get('nivel', 'info'), '⚪')} {a['msg']}")
    text_tg = "\n".join(lines)

    # HTML Email
    rows_html = "".join([
        f'<tr><td style="padding:6px 10px;color:{"#00cc33" if a.get("nivel")=="bullish" else "#ff3333" if a.get("nivel")=="bearish" else "#4da6ff"}; font-family:monospace;">'
        f'{NIVEL_EMOJI.get(a.get("nivel", "info"), "⚪")} {a["msg"]}</td></tr>'
        for a in alertas
    ])
    body_html = f'<html><body style="background:#000;color:#c8ffd4;padding:20px;"><div style="max-width:600px;margin:auto;border:1px solid #00ff4120;padding:20px;"><h3>⬡ THE MATRIX LAB</h3><table style="width:100%">{rows_html}</table></div></body></html>'

    if chat_id:
        await send_telegram_to(chat_id, text_tg)
    else:
        subs = await get_subscribers()
        for s in subs:
            await send_telegram_to(s["chat_id"], text_tg)
            if s.get("receive_email") and s.get("email"):
                await asyncio.to_thread(_send_smtp_sync, titulo, body_html, s["email"])
            await asyncio.sleep(0.05)
