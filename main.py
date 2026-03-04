import yfinance as yf
import pandas as pd
import numpy as np
import asyncio
import time
import os
import re

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Importaciones opcionales ─────────────────────────────────
try:
    from contextlib import asynccontextmanager
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    HAS_SCHEDULER = True
except ImportError:
    HAS_SCHEDULER = False
    print("[WARN] apscheduler no instalado — scheduler desactivado")

try:
    from notifier import notify_alertas, register_chat, unregister_chat, send_telegram_to
    HAS_NOTIFIER = True
except Exception as e:
    HAS_NOTIFIER = False
    print(f"[WARN] notifier no disponible: {e}")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# ─── TICKERS VIGILADOS ───────────────────────────────────────
WATCH_TICKERS = [
    "^DJI", "GC=F", "^NDX", "USDJPY=X", "GBPJPY=X",
    "EURUSD=X", "AUDUSD=X", "SI=F", "CL=F", "^TYX", "^TNX", "DX=F",
]
_sent_cache: dict = {}
_DEDUP_SECONDS = 1 * 3600

ASSET_CONFIG = {
    "^DJI":    {"key_spacing": 500,   "major_spacing": 1000, "zone_size": 100,   "ema_short": 200, "ema_long": 800},
    "^NDX":    {"key_spacing": 500,   "major_spacing": 1000, "zone_size": 100,   "ema_short": 200, "ema_long": 800},
    "GC=F":    {"key_spacing": 50,    "major_spacing": 100,  "zone_size": 10,    "ema_short": 200, "ema_long": 800},
    "GLD":     {"key_spacing": 5,     "major_spacing": 10,   "zone_size": 1,     "ema_short": 200, "ema_long": 800},
    "IAU":     {"key_spacing": 5,     "major_spacing": 10,   "zone_size": 1,     "ema_short": 200, "ema_long": 800},
    "SI=F":    {"key_spacing": 1,     "major_spacing": 5,    "zone_size": 0.25,  "ema_short": 200, "ema_long": 800},
    "CL=F":    {"key_spacing": 2,     "major_spacing": 5,    "zone_size": 0.5,   "ema_short": 200, "ema_long": 800},
    "USDJPY=X":{"key_spacing": 1,     "major_spacing": 5,    "zone_size": 0.25,  "ema_short": 200, "ema_long": 800},
    "GBPJPY=X":{"key_spacing": 1,     "major_spacing": 5,    "zone_size": 0.25,  "ema_short": 200, "ema_long": 800},
    "EURUSD=X":{"key_spacing": 0.005, "major_spacing": 0.01, "zone_size": 0.001, "ema_short": 200, "ema_long": 800},
    "AUDUSD=X":{"key_spacing": 0.005, "major_spacing": 0.01, "zone_size": 0.001, "ema_short": 200, "ema_long": 800},
    "^TNX":    {"key_spacing": 0.1,   "major_spacing": 0.5,  "zone_size": 0.05,  "ema_short": 200, "ema_long": 800},
    "^TYX":    {"key_spacing": 0.1,   "major_spacing": 0.5,  "zone_size": 0.05,  "ema_short": 200, "ema_long": 800},
    "DX=F":    {"key_spacing": 1,     "major_spacing": 5,    "zone_size": 0.25,  "ema_short": 200, "ema_long": 800},
    "^GSPC":   {"key_spacing": 50,    "major_spacing": 100,  "zone_size": 10,    "ema_short": 200, "ema_long": 800},
    "SPY":     {"key_spacing": 10,    "major_spacing": 50,   "zone_size": 2,     "ema_short": 200, "ema_long": 800},
    "VOO":     {"key_spacing": 10,    "major_spacing": 50,   "zone_size": 2,     "ema_short": 200, "ema_long": 800},
    "^RUT":    {"key_spacing": 25,    "major_spacing": 50,   "zone_size": 5,     "ema_short": 200, "ema_long": 800},
    "IWM":     {"key_spacing": 5,     "major_spacing": 10,   "zone_size": 1,     "ema_short": 200, "ema_long": 800},
    "BTC-USD": {"key_spacing": 1000,  "major_spacing": 5000, "zone_size": 250,   "ema_short": 200, "ema_long": 800},
    "ETH-USD": {"key_spacing": 50,    "major_spacing": 200,  "zone_size": 25,    "ema_short": 200, "ema_long": 800},
    "QQQ":     {"key_spacing": 10,    "major_spacing": 20,   "zone_size": 2,     "ema_short": 200, "ema_long": 800},
    "QQQM":    {"key_spacing": 5,     "major_spacing": 20,   "zone_size": 1,     "ema_short": 200, "ema_long": 800},
    "GDX":     {"key_spacing": 2,     "major_spacing": 5,    "zone_size": 0.5,   "ema_short": 200, "ema_long": 800},
    "SMH":     {"key_spacing": 10,    "major_spacing": 50,   "zone_size": 2,     "ema_short": 200, "ema_long": 800},
    "XLE":     {"key_spacing": 2,     "major_spacing": 10,   "zone_size": 0.5,   "ema_short": 200, "ema_long": 800},
    "AAPL":    {"key_spacing": 5,     "major_spacing": 20,   "zone_size": 1,     "ema_short": 200, "ema_long": 800},
    "_default":{"key_spacing": 50,    "major_spacing": 100,  "zone_size": 10,    "ema_short": 200, "ema_long": 800},
}

def get_cfg(ticker):
    return ASSET_CONFIG.get(ticker.upper(), ASSET_CONFIG["_default"])

def clean_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

def calc_indicators(df, ema_short=200, ema_long=800):
    df[f"EMA{ema_short}"] = df["Close"].ewm(span=ema_short, adjust=False).mean()
    df[f"EMA{ema_long}"]  = df["Close"].ewm(span=ema_long,  adjust=False).mean()
    delta = df["Close"].diff()
    gain  = delta.where(delta > 0, 0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df["RSI"] = 100 - (100 / (1 + gain / loss))
    return df

def calc_fractales(precio, cfg, n_above=30, n_below=30):
    ks, ms, zs = cfg["key_spacing"], cfg["major_spacing"], cfg["zone_size"]
    base = round(precio / ks) * ks
    levels = []
    for i in range(-n_below, n_above + 1):
        p = base + i * ks
        levels.append({
            "price":    p,
            "is_major": round(p % ms) == 0,
            "zone_top": p + zs,
            "zone_bot": p - zs,
        })
    return {"levels": levels, "key_spacing": ks, "major_spacing": ms, "zone_size": zs}

def detect_fractal_touch(high, low, close, fractales):
    zs   = fractales["zone_size"]
    best = None
    for level in fractales["levels"]:
        lp      = level["price"]
        crosses = high >= (lp - zs) and low <= (lp + zs)
        in_zone = abs(close - lp) <= zs * 1.5
        if crosses or in_zone:
            tipo      = "soporte" if close >= lp else "resistencia"
            candidate = {"touch": True, "price": lp, "is_major": level["is_major"],
                         "tipo": tipo, "crosses": crosses}
            if best is None or (not best["is_major"] and level["is_major"]):
                best = candidate
    return best or {"touch": False, "price": None, "is_major": False, "tipo": None, "crosses": False}

def calc_opens(df):
    result = {"year_open": None, "week_open": None}
    if df.empty:
        return result
    now        = df.index[-1]
    year_start = pd.Timestamp(year=now.year, month=1, day=1, tz=now.tz if now.tz else None)
    year_df    = df[df.index >= year_start]
    if not year_df.empty:
        result["year_open"] = float(year_df["Open"].iloc[0])
    week_start = now - pd.Timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0)
    week_df    = df[df.index >= week_start]
    if not week_df.empty:
        result["week_open"] = float(week_df["Open"].iloc[0])
    return result

def detect_alerts(df, ticker="", ema_short=200, ema_long=800, cfg=None):
    alertas = []
    n = len(df) - 1
    if n < 2:
        return alertas
    precio_now  = float(df["Close"].iloc[n])
    precio_prev = float(df["Close"].iloc[n - 1])
    prefix      = f"[{ticker}] " if ticker else ""
    col_s, col_l = f"EMA{ema_short}", f"EMA{ema_long}"

    for col, nombre in [(col_s, f"EMA{ema_short}"), (col_l, f"EMA{ema_long}")]:
        if col not in df.columns: continue
        ema_now  = df[col].iloc[n]
        ema_prev = df[col].iloc[n - 1]
        if not (pd.notna(ema_now) and pd.notna(ema_prev)): continue
        if precio_prev < ema_prev and precio_now >= ema_now:
            alertas.append({"nivel": "bullish", "msg": prefix + f"Precio cruza {nombre} al alza ${precio_now:.2f}"})
        elif precio_prev > ema_prev and precio_now <= ema_now:
            alertas.append({"nivel": "bearish", "msg": prefix + f"Precio cruza {nombre} a la baja ${precio_now:.2f}"})
        elif ema_now > 0 and abs(precio_now - ema_now) / ema_now * 100 <= 0.4:
            alertas.append({"nivel": "info", "msg": prefix + f"Precio tocando {nombre} ${precio_now:.2f}"})

    es_now  = df[col_s].iloc[n]   if col_s in df.columns else None
    es_prev = df[col_s].iloc[n-1] if col_s in df.columns else None
    el_now  = df[col_l].iloc[n]   if col_l in df.columns else None
    el_prev = df[col_l].iloc[n-1] if col_l in df.columns else None
    if all(pd.notna(x) for x in [es_now, es_prev, el_now, el_prev] if x is not None):
        if es_prev < el_prev and es_now >= el_now:
            alertas.append({"nivel": "bullish", "msg": prefix + f"Golden Cross EMA{ema_short}/{ema_long}"})
        elif es_prev > el_prev and es_now <= el_now:
            alertas.append({"nivel": "bearish", "msg": prefix + f"Death Cross EMA{ema_short}/{ema_long}"})

    if cfg is not None:
        last_high = float(df["High"].iloc[n])
        last_low  = float(df["Low"].iloc[n])
        fractales = calc_fractales(precio_now, cfg)
        ft        = detect_fractal_touch(last_high, last_low, precio_now, fractales)
        if ft["touch"]:
            mayor_str  = "MAYOR " if ft["is_major"] else ""
            nivel_tipo = "bullish" if ft["tipo"] == "soporte" else "bearish"
            alertas.append({"nivel": nivel_tipo,
                             "msg": prefix + f"⬡ Vela toca fractal {mayor_str}{ft['tipo'].upper()} ${ft['price']:.2f}"})
    return alertas

def safe(v):
    return float(v) if pd.notna(v) else None

def ts_ms(idx):
    return [int(t.timestamp() * 1000) for t in idx]

# ─── SCHEDULER ───────────────────────────────────────────────

async def scheduled_watch():
    if not HAS_NOTIFIER:
        return
    now    = time.time()
    nuevas = []
    for t in WATCH_TICKERS:
        try:
            cfg = get_cfg(t)
            df  = yf.download(t.upper(), period="6mo", interval="1h", progress=False)
            if df.empty: continue
            df      = clean_df(df)
            df      = calc_indicators(df, cfg["ema_short"], cfg["ema_long"])
            alertas = detect_alerts(df, ticker=t.upper(), ema_short=cfg["ema_short"], ema_long=cfg["ema_long"], cfg=cfg)
            for a in alertas:
                key = a["msg"]
                if now - _sent_cache.get(key, 0) > _DEDUP_SECONDS:
                    nuevas.append(a)
                    _sent_cache[key] = now
        except Exception as e:
            print(f"[scheduler] Error en {t}: {e}")

    if nuevas:
        await notify_alertas(nuevas, source="Auto 1H")

async def get_past_alerts(period: str) -> list[dict]:
    all_alerts = []
    for t in WATCH_TICKERS:
        try:
            cfg = get_cfg(t)
            df  = yf.download(t.upper(), period=period, interval="1h", progress=False)
            if df.empty: continue
            df = clean_df(df)
            df = calc_indicators(df, cfg["ema_short"], cfg["ema_long"])
            for i in range(1, len(df)):
                temp_df = df.iloc[:i+1]
                alerts_for_candle = detect_alerts(temp_df, ticker=t.upper(), ema_short=cfg["ema_short"], ema_long=cfg["ema_long"], cfg=cfg)
                for alert in alerts_for_candle:
                    alert_time = temp_df.index[-1].strftime("%d/%m/%Y %H:%M")
                    alert["msg"] = f"{alert_time} - {alert['msg']}"
                    all_alerts.append(alert)
        except Exception: pass
    return all_alerts

# ─── APP ──────────────────────────────────────────────────

if HAS_SCHEDULER:
    @asynccontextmanager
    async def lifespan(app):
        scheduler = AsyncIOScheduler()
        scheduler.add_job(scheduled_watch, "interval", hours=1, id="watch_1h")
        scheduler.start()
        yield
        scheduler.shutdown()
    app = FastAPI(lifespan=lifespan)
else:
    app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    if not HAS_NOTIFIER: return JSONResponse({"ok": False})
    try:
        body = await request.json()
        message = body.get("message") or body.get("edited_message", {})
        if not message: return JSONResponse({"ok": True})
        chat_id = message.get("chat", {}).get("id")
        username = message.get("from", {}).get("username", "")
        text = message.get("text", "").strip()

        if text.startswith("/start"):
            ok = await register_chat(chat_id, username)
            reply = "✅ <b>¡Suscrito!</b> Recibirás alertas cada 1H.\nEnvía /email tu@email.com para correo.\nEnvía /stop para cancelar."
            await send_telegram_to(chat_id, reply)
            past = await get_past_alerts("1d")
            if past: await notify_alertas(past, source="Resumen 24H", chat_id=chat_id)
        elif text.startswith("/email "):
            email = text.split(" ", 1)[1].strip()
            if re.match(r"[^@]+@[^@]+\.[^@]+", email):
                if await register_chat(chat_id, username, email=email):
                    await send_telegram_to(chat_id, f"✅ Email {email} registrado.")
            else: await send_telegram_to(chat_id, "⚠️ Formato inválido.")
        elif text.startswith("/stop"):
            if await unregister_chat(chat_id):
                await send_telegram_to(chat_id, "🔕 Suscripción cancelada.")
    except Exception as e: print(f"[webhook] Error: {e}")
    return JSONResponse({"ok": True})

@app.get("/")
async def splash():
    return FileResponse("templates/Splash.html")

@app.get("/app")
async def dashboard():
    return FileResponse("templates/index.html")

@app.get("/api/notify")
async def force_notify():
    await scheduled_watch()
    return {"ok": True}

@app.get("/api/subs")
async def list_subs():
    from notifier import get_subscribers
    subs = await get_subscribers()
    return {"ok": True, "subs": len(subs)}

@app.get("/api/bot-info")
async def bot_info():
    token = os.getenv("TELEGRAM_TOKEN", "")
    if not token: return {"ok": False}
    import httpx
    async with httpx.AsyncClient() as client:
        r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        return {"ok": True, "username": r.json()["result"]["username"]} if r.json().get("ok") else {"ok": False}

@app.get("/api/mail-status")
async def mail_status():
    return {"configured": bool(os.getenv("MAIL_FROM") and os.getenv("MAIL_PASSWORD"))}

@app.get("/api/notifier-status")
async def notifier_status():
    return {"ok": True, "scheduler": HAS_SCHEDULER, "next_run": "1h"}

@app.get("/api/chart/{ticker}")
async def get_chart(ticker: str):
    try:
        cfg = get_cfg(ticker)
        df = yf.download(ticker.upper(), period="2y", interval="1h", progress=False)
        df = clean_df(df)
        df = calc_indicators(df, cfg["ema_short"], cfg["ema_long"])
        last = float(df["Close"].iloc[-1])
        return {
            "chart": {"candles": [{"x": int(t.timestamp()*1000), "o": safe(df["Open"].loc[t]), "h": safe(df["High"].loc[t]), "l": safe(df["Low"].loc[t]), "c": safe(df["Close"].loc[t])} for t in df.index], f"ema{cfg['ema_short']}": [{"x": int(t.timestamp()*1000), "y": float(df[f'EMA{cfg["ema_short"]}'].loc[t])} for t in df.index], f"ema{cfg['ema_long']}": [{"x": int(t.timestamp()*1000), "y": float(df[f'EMA{cfg["ema_long"]}'].loc[t])} for t in df.index]},
            "fractales": calc_fractales(last, cfg), "opens": calc_opens(df), "last_price": last, "change": last - float(df["Close"].iloc[0]), "change_pct": (last - float(df["Close"].iloc[0])) / float(df["Close"].iloc[0]) * 100, "rsi_current": float(df["RSI"].iloc[-1]), "alertas": detect_alerts(df, ticker=ticker.upper(), cfg=cfg), "asset_config": cfg
        }
    except Exception as e: return {"error": str(e)}

@app.get("/api/row/{ticker}")
async def get_row(ticker: str):
    try:
        cfg = get_cfg(ticker)
        df = yf.download(ticker.upper(), period="1y", interval="1h", progress=False)
        df = clean_df(df); df = calc_indicators(df, cfg["ema_short"], cfg["ema_long"])
        last = float(df["Close"].iloc[-1]); first = float(df["Close"].iloc[0])
        ft = detect_fractal_touch(float(df["High"].iloc[-1]), float(df["Low"].iloc[-1]), last, calc_fractales(last, cfg))
        return {"ticker": ticker.upper(), "price": last, "change_pct": (last-first)/first*100, "rsi": float(df["RSI"].iloc[-1]), "ema_short": float(df[f'EMA{cfg["ema_short"]}'].iloc[-1]), "ema_long": float(df[f'EMA{cfg["ema_long"]}'].iloc[-1]), "ema_short_name": f"EMA{cfg['ema_short']}", "ema_long_name": f"EMA{cfg['ema_long']}", "fractal_touch": ft["touch"], "fractal_price": ft["price"], "fractal_is_major": ft["is_major"], "fractal_tipo": ft["tipo"], "fractal_crosses": ft["crosses"]}
    except Exception: return {"error": "err"}

@app.get("/api/watch")
async def watch(tickers: str = ""):
    als = []
    for t in tickers.split(","):
        try:
            cfg = get_cfg(t)
            df = yf.download(t.upper(), period="1mo", interval="1h", progress=False)
            df = clean_df(df); df = calc_indicators(df, cfg["ema_short"], cfg["ema_long"])
            als.extend(detect_alerts(df, ticker=t.upper(), cfg=cfg))
        except: pass
    return {"alertas": als}

@app.get("/api/sparkline/{ticker}")
async def sparkline(ticker: str):
    try:
        df = yf.download(ticker.upper(), period="1mo", interval="1d", progress=False)
        cl = clean_df(df)["Close"].dropna().tolist()
        return {"closes": [float(c) for c in cl], "pct": (cl[-1]-cl[0])/cl[0]*100}
    except: return {"closes": [], "pct": 0}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
