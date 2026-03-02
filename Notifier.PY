
"""
notifier.py — The Matrix Lab
Envío de alertas a Telegram y Email.

Variables de entorno necesarias (.env o panel de tu hosting):
  TELEGRAM_TOKEN   → Token del bot (BotFather)
  TELEGRAM_CHAT_ID → Tu chat_id o el de un canal/grupo
  MAIL_FROM        → Email remitente (p.ej. tu Gmail)
  MAIL_PASSWORD    → Contraseña de aplicación (Gmail: App Passwords)
  MAIL_TO          → Email destinatario
  MAIL_SMTP        → Servidor SMTP (por defecto: smtp.gmail.com)
  MAIL_PORT        → Puerto SMTP     (por defecto: 587)
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

# ── CONFIGURACIÓN DESDE VARIABLES DE ENTORNO ────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

MAIL_FROM     = os.getenv("MAIL_FROM", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_TO       = os.getenv("MAIL_TO", "")
MAIL_SMTP     = os.getenv("MAIL_SMTP", "smtp.gmail.com")
MAIL_PORT     = int(os.getenv("MAIL_PORT", "587"))


# ── EMOJI POR NIVEL ─────────────────────────────────────────
NIVEL_EMOJI = {
    "bullish": "🟢",
    "bearish": "🔴",
    "info":    "🔵",
}


# ════════════════════════════════════════════════════════════
# TELEGRAM
# ════════════════════════════════════════════════════════════

async def send_telegram(text: str) -> bool:
    """Envía un mensaje a Telegram. Devuelve True si tuvo éxito."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram no configurado (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID)")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            if r.status_code == 200:
                logger.info("Telegram OK")
                return True
            else:
                logger.error(f"Telegram error {r.status_code}: {r.text}")
                return False
    except Exception as e:
        logger.error(f"Telegram excepción: {e}")
        return False


# ════════════════════════════════════════════════════════════
# EMAIL
# ════════════════════════════════════════════════════════════

def send_email(subject: str, body_html: str) -> bool:
    """Envía un email. Devuelve True si tuvo éxito."""
    if not MAIL_FROM or not MAIL_PASSWORD or not MAIL_TO:
        logger.warning("Email no configurado (MAIL_FROM / MAIL_PASSWORD / MAIL_TO)")
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
# FUNCIÓN PRINCIPAL — envía una lista de alertas
# ════════════════════════════════════════════════════════════

async def notify_alertas(alertas: list[dict], source: str = "") -> None:
    """
    Recibe la lista de alertas del formato:
      [{"nivel": "bullish"|"bearish"|"info", "msg": "..."}]
    y las envía a Telegram y Email si están configurados.
    """
    if not alertas:
        return

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    titulo  = f"⬡ Matrix Lab · Alertas{' · ' + source if source else ''} · {now_str}"

    # ── Armar texto plano para Telegram ──────────────────────
    lineas_tg = [f"<b>{titulo}</b>\n"]
    for a in alertas:
        emoji = NIVEL_EMOJI.get(a.get("nivel", "info"), "⚪")
        lineas_tg.append(f"{emoji} {a['msg']}")
    texto_tg = "\n".join(lineas_tg)

    # ── Armar HTML para email ────────────────────────────────
    color_map = {"bullish": "#00cc33", "bearish": "#ff3333", "info": "#4da6ff"}
    filas_html = ""
    for a in alertas:
        color = color_map.get(a.get("nivel", "info"), "#888")
        emoji = NIVEL_EMOJI.get(a.get("nivel", "info"), "⚪")
        filas_html += f"""
        <tr>
          <td style="padding:6px 10px;border-bottom:1px solid #1a2a1a;
                     color:{color};font-family:monospace;font-size:13px;">
            {emoji} {a['msg']}
          </td>
        </tr>"""

    body_html = f"""
    <html><body style="background:#000;color:#c8ffd4;font-family:sans-serif;padding:20px;">
      <div style="max-width:600px;margin:auto;background:#010801;border:1px solid #00ff4120;
                  border-radius:8px;overflow:hidden;">
        <div style="background:#010f01;padding:14px 20px;border-bottom:1px solid #00ff4115;">
          <span style="font-family:monospace;font-size:14px;color:#00ff41;font-weight:bold;">
            ⬡ THE MATRIX LAB
          </span>
          <span style="font-family:monospace;font-size:11px;color:#666;margin-left:10px;">
            {now_str}
          </span>
        </div>
        <table style="width:100%;border-collapse:collapse;">
          {filas_html}
        </table>
        <div style="padding:10px 20px;font-size:10px;color:#333;font-family:monospace;
                    border-top:1px solid #00ff4110;text-align:center;">
          Análisis técnico automatizado · No es asesoría financiera
        </div>
      </div>
    </body></html>
    """

    # ── Enviar ───────────────────────────────────────────────
    await send_telegram(texto_tg)

    # Email se ejecuta en hilo separado para no bloquear el event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        send_email,
        titulo,
        body_html,
    )
