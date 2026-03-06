"""
notifier.py — The Matrix Lab
Cada usuario tiene sus propios tickers vigilados y canales de notificación.

Variables de entorno en Railway:
  TELEGRAM_TOKEN    → Token del bot (@BotFather)
  SUPABASE_URL      → https://xxxxx.supabase.co
  SUPABASE_KEY      → service_role key (empieza por eyJ...)
  MAIL_FROM         → tu@gmail.com  (opcional)
  MAIL_PASSWORD     → App Password de Gmail
  MAIL_SMTP         → smtp.gmail.com
  MAIL_PORT         → 587
"""

import os
import re
import asyncio
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx

logger = logging.getLogger("notifier")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or ""
SUPABASE_URL   = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY", "")
MAIL_FROM      = os.getenv("MAIL_FROM", "")
MAIL_PASSWORD  = os.getenv("MAIL_PASSWORD", "")
MAIL_SMTP      = os.getenv("MAIL_SMTP", "smtp.gmail.com")
MAIL_PORT      = int(os.getenv("MAIL_PORT", "587"))

NIVEL_EMOJI    = {"bullish": "🟢", "bearish": "🔴", "info": "🔵"}
NIVEL_LABEL    = {"bullish": "Favorable",  "bearish": "Atención",  "info": "Interesante"}
NIVEL_LABEL_EN = {"bullish": "Bullish",    "bearish": "Bearish",   "info": "Watch"}

def _translate_en(msg: str) -> str:
    msg = re.sub(r'Precio cruza (EMA\d+) al alza',  r'Price crosses \1 upward',   msg)
    msg = re.sub(r'Precio cruza (EMA\d+) a la baja', r'Price crosses \1 downward', msg)
    msg = re.sub(r'Precio tocando (EMA\d+)',          r'Price touching \1',          msg)
    msg = msg.replace('Vela toca fractal MAYOR SOPORTE',     'Candle touches MAJOR fractal SUPPORT')
    msg = msg.replace('Vela toca fractal MAYOR RESISTENCIA', 'Candle touches MAJOR fractal RESISTANCE')
    msg = msg.replace('Vela toca fractal SOPORTE',           'Candle touches fractal SUPPORT')
    msg = msg.replace('Vela toca fractal RESISTENCIA',       'Candle touches fractal RESISTANCE')
    return msg

ASSET_NAMES = {
    '^DJI':'US30 · Dow Jones','^NDX':'NAS100 · Nasdaq','^GSPC':'SPX · S&P 500',
    '^RUT':'RTY · Russell 2000','GC=F':'XAUUSD · Oro','SI=F':'XAGUSD · Plata',
    'CL=F':'WTI · Petróleo','USDJPY=X':'USD/JPY','GBPJPY=X':'GBP/JPY',
    'EURUSD=X':'EUR/USD','AUDUSD=X':'AUD/USD','^TNX':'US10Y · Bono',
    '^TYX':'US30Y · Bono','DX=F':'DXY · Dólar','BTC-USD':'BTC · Bitcoin',
    'ETH-USD':'ETH · Ethereum','SPY':'SPY','VOO':'VOO','QQQ':'QQQ',
    'QQQM':'QQQM','GLD':'GLD','IAU':'IAU','GDX':'GDX','IWM':'IWM',
    'SMH':'SMH','XLE':'XLE','AAPL':'AAPL · Apple',
}

def _strip_ticker(msg: str) -> str:
    return re.sub(r'^\[[^\]]+\]\s*', '', msg)

def _build_tg_grouped(alerts_by_ticker: dict, now_str: str, lang: str = "es") -> str:
    labels = NIVEL_LABEL_EN if lang == "en" else NIVEL_LABEL
    lines = [f"<b>⬡ Matrix Lab · {now_str}</b>"]
    for ticker, alertas in alerts_by_ticker.items():
        if not alertas:
            continue
        name = ASSET_NAMES.get(ticker.upper(), ticker)
        lines.append(f"\n<b>📊 {name}</b>")
        for a in alertas:
            nivel = a.get('nivel', 'info')
            emoji = NIVEL_EMOJI.get(nivel, '⚪')
            label = labels.get(nivel, '')
            msg   = _strip_ticker(a.get('msg', ''))
            if lang == "en":
                msg = _translate_en(msg)
            lines.append(f"{emoji} {label} · {msg}")
    return "\n".join(lines)

def _build_html_grouped(alerts_by_ticker: dict, now_str: str, lang: str = "es") -> str:
    color_map = {"bullish": "#00cc33", "bearish": "#ff3333", "info": "#4da6ff"}
    labels = NIVEL_LABEL_EN if lang == "en" else NIVEL_LABEL
    disclaimer = "Automated technical analysis · Not financial advice" if lang == "en" else "Análisis técnico automatizado · No es asesoría financiera"
    rows = ""
    for ticker, alertas in alerts_by_ticker.items():
        if not alertas:
            continue
        name = ASSET_NAMES.get(ticker.upper(), ticker)
        rows += (f'<tr><td style="padding:8px 10px 4px;font-family:monospace;font-size:12px;'
                 f'color:#00ff41;font-weight:bold;border-top:1px solid #0a1a0a">📊 {name}</td></tr>')
        for a in alertas:
            nivel = a.get("nivel", "info")
            c = color_map.get(nivel, "#888")
            e = NIVEL_EMOJI.get(nivel, "⚪")
            lbl = labels.get(nivel, "")
            msg = _strip_ticker(a.get("msg", ""))
            if lang == "en":
                msg = _translate_en(msg)
            rows += (f'<tr><td style="padding:3px 10px 3px 20px;border-bottom:1px solid #1a2a1a;'
                     f'color:{c};font-family:monospace;font-size:13px">'
                     f'{e} {lbl} · {msg}</td></tr>')
    return f"""<html><body style="background:#000;padding:20px;">
      <div style="max-width:600px;margin:auto;background:#010801;border:1px solid #00ff4120;border-radius:8px;overflow:hidden;">
        <div style="background:#010f01;padding:14px 20px;border-bottom:1px solid #00ff4115;">
          <span style="font-family:monospace;font-size:14px;color:#00ff41;font-weight:bold;">⬡ THE MATRIX LAB</span>
          <span style="font-family:monospace;font-size:11px;color:#666;margin-left:10px;">{now_str}</span>
        </div>
        <table style="width:100%;border-collapse:collapse;">{rows}</table>
        <div style="padding:10px 20px;font-size:10px;color:#333;font-family:monospace;border-top:1px solid #00ff4110;text-align:center;">
          {disclaimer}
        </div>
      </div></body></html>"""

print(f"[notifier] Telegram: {'OK' if TELEGRAM_TOKEN else 'FALTA TELEGRAM_TOKEN'} | "
      f"Supabase: {'OK' if SUPABASE_URL and SUPABASE_KEY else 'FALTA SUPABASE_URL/KEY'} | "
      f"Email: {'OK' if MAIL_FROM else 'no configurado'}")


def _headers():
    return {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
    }


async def _supa_get(path: str) -> list:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=_headers())
            if r.status_code == 200:
                return r.json()
            print(f"[notifier] Supabase GET error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[notifier] Supabase excepción: {e}")
    return []


async def _supa_post(path: str, payload: dict, prefer: str = "") -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    h = _headers()
    if prefer:
        h["Prefer"] = prefer
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{SUPABASE_URL}/rest/v1/{path}", headers=h, json=payload)
            if r.status_code == 409:
                print(f"[notifier] Supabase 409 en {path} — registro ya existe, se trata como éxito")
                return True
            return r.status_code in (200, 201, 204)
    except Exception as e:
        print(f"[notifier] Supabase POST excepción: {e}")
        return False


# ── Telegram subs (registro via /start) ─────────────────────

async def get_chat_ids() -> list[int]:
    rows = await _supa_get("telegram_subs?select=chat_id")
    return [r["chat_id"] for r in rows if r.get("chat_id")]


async def register_chat(chat_id: int, username: str = "") -> bool:
    return await _supa_post(
        "telegram_subs",
        {"chat_id": chat_id, "username": username or ""},
        prefer="resolution=merge-duplicates"
    )


# ── Preferencias por usuario ─────────────────────────────────

async def get_user_prefs(user_id: str) -> dict:
    rows = await _supa_get(f"notification_prefs?user_id=eq.{user_id}&select=*")
    return rows[0] if rows else {}


async def save_user_prefs(user_id: str, prefs: dict) -> bool:
    payload = {
        "user_id":          user_id,
        "telegram_chat_id": prefs.get("telegram_chat_id"),
        "telegram_enabled": prefs.get("telegram_enabled", False),
        "email_address":    prefs.get("email_address", ""),
        "email_enabled":    prefs.get("email_enabled", False),
        "tickers":          prefs.get("tickers", []),
        "language":         prefs.get("language", "es"),
    }
    return await _supa_post(
        "notification_prefs", payload,
        prefer="resolution=merge-duplicates"
    )


async def get_all_user_prefs() -> list[dict]:
    return await _supa_get(
        "notification_prefs"
        "?or=(telegram_enabled.eq.true,email_enabled.eq.true)"
        "&select=*"
    )


# ── Envío Telegram ───────────────────────────────────────────

async def send_telegram_to(chat_id: int, text: str) -> bool:
    if not TELEGRAM_TOKEN:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text,
                      "parse_mode": "HTML", "disable_web_page_preview": True}
            )
            d = r.json()
            if not d.get("ok"):
                print(f"[notifier] Telegram error {chat_id}: {d.get('description')}")
            return d.get("ok", False)
    except Exception as e:
        print(f"[notifier] Telegram excepción {chat_id}: {e}")
        return False


# ── Envío Email ──────────────────────────────────────────────

def _smtp_send(to_addr: str, subject: str, body_html: str) -> bool:
    if not MAIL_FROM or not MAIL_PASSWORD:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = MAIL_FROM
        msg["To"]      = to_addr
        msg.attach(MIMEText(body_html, "html"))
        port = int(MAIL_PORT)
        if port == 465:
            with smtplib.SMTP_SSL(MAIL_SMTP, port, timeout=10) as s:
                s.login(MAIL_FROM, MAIL_PASSWORD); s.sendmail(MAIL_FROM, to_addr, msg.as_string())
        else:
            with smtplib.SMTP(MAIL_SMTP, port, timeout=10) as s:
                s.starttls(); s.login(MAIL_FROM, MAIL_PASSWORD); s.sendmail(MAIL_FROM, to_addr, msg.as_string())
        return True
    except Exception as e:
        print(f"[notifier] Email error → {to_addr}: {e}")
        return False


def _build_html(alertas: list[dict], now_str: str) -> str:
    color_map = {"bullish": "#00cc33", "bearish": "#ff3333", "info": "#4da6ff"}
    filas = "".join(
        f'<tr><td style="padding:6px 10px;border-bottom:1px solid #1a2a1a;'
        f'color:{color_map.get(a.get("nivel","info"),"#888")};font-family:monospace;font-size:13px;">'
        f'{NIVEL_EMOJI.get(a.get("nivel","info"),"⚪")} {NIVEL_LABEL.get(a.get("nivel","info"),"")} · {a["msg"]}</td></tr>'
        for a in alertas
    )
    return f"""<html><body style="background:#000;padding:20px;">
      <div style="max-width:600px;margin:auto;background:#010801;border:1px solid #00ff4120;border-radius:8px;overflow:hidden;">
        <div style="background:#010f01;padding:14px 20px;border-bottom:1px solid #00ff4115;">
          <span style="font-family:monospace;font-size:14px;color:#00ff41;font-weight:bold;">⬡ THE MATRIX LAB</span>
          <span style="font-family:monospace;font-size:11px;color:#666;margin-left:10px;">{now_str}</span>
        </div>
        <table style="width:100%;border-collapse:collapse;">{filas}</table>
        <div style="padding:10px 20px;font-size:10px;color:#333;font-family:monospace;border-top:1px solid #00ff4110;text-align:center;">
          Análisis técnico automatizado · No es asesoría financiera
        </div>
      </div></body></html>"""


# ── Función principal — por usuario ─────────────────────────

async def notify_users_with_alerts(alerts_by_ticker: dict) -> None:
    """
    alerts_by_ticker = {"^DJI": [alertas], "GC=F": [alertas], ...}
    Envía a cada usuario solo las alertas de sus tickers elegidos.
    Incluye también a suscriptores básicos de Telegram (vía /start) sin preferencias configuradas.
    """
    if not alerts_by_ticker:
        return

    now_str          = datetime.now(ZoneInfo('Europe/Madrid')).strftime("%d/%m/%Y %H:%M")
    all_alertas_flat = [a for al in alerts_by_ticker.values() for a in al]

    # Obtener prefs completas y subs básicas en paralelo
    all_prefs, basic_chat_ids = await asyncio.gather(
        get_all_user_prefs(),
        get_chat_ids()
    )

    loop = asyncio.get_running_loop()
    covered_chat_ids: set = set()

    # 1 — Usuarios con preferencias configuradas (alertas personalizadas por ticker)
    if all_prefs:
        print(f"[notifier] {len(all_prefs)} usuario(s) con preferencias activas")
        for prefs in all_prefs:
            user_tickers = [t.upper() for t in (prefs.get("tickers") or [])]

            # Sin tickers configurados → recibe todos
            if not user_tickers:
                user_alertas = all_alertas_flat
            else:
                user_alertas = [a for t in user_tickers for a in alerts_by_ticker.get(t, [])]

            if not user_alertas:
                continue

            # Build grouped dict for this user's tickers
            if not user_tickers:
                user_by_ticker = alerts_by_ticker
            else:
                user_by_ticker = {t: alerts_by_ticker[t] for t in user_tickers if alerts_by_ticker.get(t)}

            if not user_by_ticker:
                continue

            lang = prefs.get("language", "es")

            if prefs.get("telegram_enabled") and prefs.get("telegram_chat_id"):
                cid = int(prefs["telegram_chat_id"])
                covered_chat_ids.add(cid)
                texto_tg = _build_tg_grouped(user_by_ticker, now_str, lang=lang)
                await send_telegram_to(cid, texto_tg)
                await asyncio.sleep(0.05)

            if prefs.get("email_enabled") and prefs.get("email_address"):
                html = _build_html_grouped(user_by_ticker, now_str, lang=lang)
                await loop.run_in_executor(
                    None, _smtp_send, prefs["email_address"],
                    f"⬡ Matrix Lab · {now_str}", html
                )

    # 2 — Suscriptores básicos de Telegram (/start) sin preferencias configuradas
    if TELEGRAM_TOKEN and all_alertas_flat and basic_chat_ids:
        texto_base = _build_tg_grouped(alerts_by_ticker, now_str)
        nuevos = 0
        for cid in basic_chat_ids:
            if int(cid) not in covered_chat_ids:
                await send_telegram_to(int(cid), texto_base)
                await asyncio.sleep(0.05)
                nuevos += 1
        if nuevos:
            print(f"[notifier] {nuevos} suscriptor(es) básico(s) notificados")

    if not all_prefs and not basic_chat_ids:
        print("[notifier] Sin usuarios con notificaciones activas")


# ── Compatibilidad con scheduler existente ───────────────────

async def notify_alertas(alertas: list[dict], source: str = "") -> None:
    """Broadcast a todos los chat_ids registrados."""
    if not alertas:
        return
    now_str = datetime.now(ZoneInfo('Europe/Madrid')).strftime("%d/%m/%Y %H:%M")
    # Group by ticker
    by_ticker: dict = {}
    for a in alertas:
        m = re.match(r'^\[([^\]]+)\]', a.get('msg', ''))
        tk = m.group(1) if m else 'GENERAL'
        by_ticker.setdefault(tk, []).append(a)
    texto = _build_tg_grouped(by_ticker, now_str)
    if TELEGRAM_TOKEN:
        for cid in await get_chat_ids():
            await send_telegram_to(cid, texto)
            await asyncio.sleep(0.05)
