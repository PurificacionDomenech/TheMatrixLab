import yfinance as yf
import pandas as pd
import numpy as np
import asyncio
import time
import os

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
    from notifier import notify_alertas, register_chat, send_telegram_to
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
_DEDUP_SECONDS = 4 * 3600

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
        print("[scheduler] notifier no disponible, saltando")
        return
    now    = time.time()
    nuevas = []
    for t in WATCH_TICKERS:
        try:
            cfg = get_cfg(t)
            df  = yf.download(t.upper(), period="6mo", interval="4h", progress=False)
            if df.empty:
                continue
            df      = clean_df(df)
            df      = calc_indicators(df, cfg["ema_short"], cfg["ema_long"])
            alertas = detect_alerts(df, ticker=t.upper(),
                                    ema_short=cfg["ema_short"],
                                    ema_long=cfg["ema_long"], cfg=cfg)
            for a in alertas:
                key = a["msg"]
                if now - _sent_cache.get(key, 0) > _DEDUP_SECONDS:
                    nuevas.append(a)
                    _sent_cache[key] = now
        except Exception as e:
            print(f"[scheduler] Error en {t}: {e}")

    if nuevas:
        print(f"[scheduler] Enviando {len(nuevas)} alertas…")
        await notify_alertas(nuevas, source="Auto 4H")
    else:
        print("[scheduler] Sin alertas nuevas.")


# ─── APP ─────────────────────────────────────────────────────

if HAS_SCHEDULER:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        scheduler = None
        try:
            scheduler = AsyncIOScheduler()
            scheduler.add_job(scheduled_watch, "interval", hours=4, id="watch_4h")
            scheduler.start()
            print("[scheduler] Iniciado · revisión cada 4h")
        except Exception as e:
            print(f"[scheduler] Error al iniciar: {e}")
        yield
        if scheduler:
            try:
                scheduler.shutdown()
            except Exception:
                pass

    app = FastAPI(lifespan=lifespan)
else:
    app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")


# ════════════════════════════════════════════════════════════
# WEBHOOK DEL BOT DE TELEGRAM
# ════════════════════════════════════════════════════════════

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    if not HAS_NOTIFIER:
        return JSONResponse({"ok": False})
    try:
        body    = await request.json()
        message = body.get("message") or body.get("edited_message", {})
        if not message:
            return JSONResponse({"ok": True})

        chat_id  = message.get("chat", {}).get("id")
        username = message.get("from", {}).get("username", "")
        text     = message.get("text", "").strip()

        if not chat_id:
            return JSONResponse({"ok": True})

        if text.startswith("/start"):
            ok = await register_chat(chat_id, username)
            reply = (
                "✅ <b>¡Suscrito a The Matrix Lab!</b>\n\n"
                "⬡ Recibirás alertas automáticas cada 4H sobre:\n"
                "· Cruces de EMA 200/800\n"
                "· Golden Cross / Death Cross\n"
                "· Toques de niveles fractales\n"
                "· RSI extremo\n\n"
                "Activos vigilados: ^DJI, GC=F, ^NDX, USDJPY, GBPJPY, EURUSD, "
                "AUDUSD, SI=F, CL=F, Bonos y DXY.\n\n"
                "Envía /stop para cancelar las alertas."
                if ok else
                "⚠️ No se pudo registrar. Inténtalo de nuevo."
            )
            await send_telegram_to(chat_id, reply)

        elif text.startswith("/stop"):
            await send_telegram_to(chat_id,
                "🔕 Para cancelar tu suscripción, contacta con el administrador.")

        elif text.startswith("/status"):
            await send_telegram_to(chat_id,
                "✅ <b>The Matrix Lab activo</b>\n"
                "Revisión de mercados cada 4 horas.")

        elif text.startswith("/test"):
            await send_telegram_to(chat_id,
                "🟢 <b>[TEST]</b> El sistema de alertas funciona correctamente.\n"
                "⬡ Recibirás mensajes cuando haya señales reales.")

    except Exception as e:
        print(f"[webhook] Error: {e}")

    return JSONResponse({"ok": True})


# ────────────────────────────────────────────────────────────
# RUTAS PRINCIPALES
# ────────────────────────────────────────────────────────────

@app.get("/")
async def splash():
    for name in ("Splash.html", "splash.html"):
        path = f"templates/{name}"
        if os.path.exists(path):
            return FileResponse(path)
    return FileResponse("templates/index.html")

@app.get("/app")
async def dashboard():
    return FileResponse("templates/index.html")


# ────────────────────────────────────────────────────────────
# ENDPOINTS DE NOTIFICACIONES
# ────────────────────────────────────────────────────────────

@app.get("/api/notify")
async def force_notify():
    """Fuerza revisión y envío inmediato (testing y botón del panel)."""
    if not HAS_NOTIFIER:
        return {"ok": False, "msg": "Notifier no configurado. Revisa TELEGRAM_TOKEN, SUPABASE_URL y SUPABASE_KEY."}
    await scheduled_watch()
    return {"ok": True, "msg": "Revisión completada. Alertas enviadas si había señales nuevas."}


@app.get("/api/subs")
async def list_subs():
    """Número de suscriptores en Supabase (para el panel de notificaciones)."""
    if not HAS_NOTIFIER:
        return {"ok": False, "subs": 0, "msg": "Notifier no disponible"}
    from notifier import get_chat_ids
    ids = await get_chat_ids()
    return {"ok": True, "subs": len(ids), "chat_ids": ids}


@app.get("/api/bot-info")
async def bot_info():
    """Devuelve el username del bot de Telegram para mostrar el link de suscripción."""
    token = os.getenv("TELEGRAM_TOKEN", "")
    if not token:
        return {"ok": False, "username": None, "msg": "TELEGRAM_TOKEN no configurado"}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            d = r.json()
            if d.get("ok"):
                return {
                    "ok":       True,
                    "username": d["result"].get("username"),
                    "name":     d["result"].get("first_name"),
                }
    except Exception as e:
        print(f"[bot-info] {e}")
    return {"ok": False, "username": None}


@app.get("/api/mail-status")
async def mail_status():
    """Comprueba si el email está configurado en las variables de entorno."""
    mail_from = os.getenv("MAIL_FROM", "")
    mail_pass = os.getenv("MAIL_PASSWORD", "")
    mail_to   = os.getenv("MAIL_TO", "")
    configured = bool(mail_from and mail_pass and mail_to)
    return {
        "configured": configured,
        "mail_to":    mail_to if configured else None,
    }

@app.get("/api/notifier-status")
async def notifier_status():
    """Estado completo del sistema de notificaciones."""
    token    = os.getenv("TELEGRAM_TOKEN", "")
    supa_url = os.getenv("SUPABASE_URL", "")
    supa_key = os.getenv("SUPABASE_KEY", "")
    mail_ok  = bool(os.getenv("MAIL_FROM") and os.getenv("MAIL_PASSWORD") and os.getenv("MAIL_TO"))
    tg_ok    = bool(token and supa_url and supa_key)

    return {
        "ok":        tg_ok or mail_ok,
        "telegram":  tg_ok,
        "email":     mail_ok,
        "scheduler": HAS_SCHEDULER,
        "notifier":  HAS_NOTIFIER,
        "next_run":  "~4h desde el último ciclo automático",
    }


# ────────────────────────────────────────────────────────────
# ENDPOINTS DE DATOS DE MERCADO
# ────────────────────────────────────────────────────────────

@app.get("/api/chart/{ticker}")
async def get_chart(ticker: str):
    try:
        cfg = get_cfg(ticker)
        es, el = cfg["ema_short"], cfg["ema_long"]
        df = yf.download(ticker.upper(), period="2y", interval="4h", progress=False)
        if df.empty:
            return {"error": "Simbolo no encontrado: " + ticker}
        df = clean_df(df)
        df = calc_indicators(df, es, el)

        ultimo     = float(df["Close"].iloc[-1])
        fractales  = calc_fractales(ultimo, cfg)
        timestamps = ts_ms(df.index)

        candles = [
            {"x": timestamps[i], "o": safe(df["Open"].iloc[i]),
             "h": safe(df["High"].iloc[i]), "l": safe(df["Low"].iloc[i]),
             "c": safe(df["Close"].iloc[i])}
            for i in range(len(df))
        ]

        def ema_series(col):
            if col not in df.columns: return []
            return [{"x": timestamps[i], "y": float(df[col].iloc[i])}
                    for i in range(len(df)) if pd.notna(df[col].iloc[i])]

        rsi_os, rsi_ob = [], []
        for i in range(len(df)):
            r = df["RSI"].iloc[i]
            if pd.notna(r):
                if r < 30:   rsi_os.append({"x": timestamps[i], "y": float(df["Close"].iloc[i])})
                elif r > 70: rsi_ob.append({"x": timestamps[i], "y": float(df["Close"].iloc[i])})

        fractal_touch_candles = []
        for i in range(len(df)):
            h = safe(df["High"].iloc[i]); l = safe(df["Low"].iloc[i]); c = safe(df["Close"].iloc[i])
            if h is None or l is None or c is None: continue
            ft = detect_fractal_touch(h, l, c, fractales)
            if ft["touch"] and ft["is_major"]:
                fractal_touch_candles.append({"x": timestamps[i], "y": c,
                                              "tipo": ft["tipo"], "price": ft["price"]})

        opens   = calc_opens(df)
        rsi_s   = df["RSI"].dropna()
        rsi_c   = float(rsi_s.iloc[-1]) if not rsi_s.empty else 50
        first   = float(df["Close"].iloc[0])
        alertas = detect_alerts(df, ticker=ticker.upper(), ema_short=es, ema_long=el, cfg=cfg)

        return {
            "chart": {
                "candles": candles,
                f"ema{es}": ema_series(f"EMA{es}"),
                f"ema{el}": ema_series(f"EMA{el}"),
                "rsi_os":  rsi_os,
                "rsi_ob":  rsi_ob,
                "fractal_touch_candles": fractal_touch_candles,
            },
            "fractales":    fractales,
            "opens":        opens,
            "last_price":   ultimo,
            "change":       ultimo - first,
            "change_pct":   (ultimo - first) / first * 100,
            "rsi_current":  rsi_c,
            "alertas":      alertas,
            "asset_config": {"ema_short": es, "ema_long": el},
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/row/{ticker}")
async def get_row(ticker: str):
    try:
        cfg = get_cfg(ticker)
        es, el = cfg["ema_short"], cfg["ema_long"]
        df = yf.download(ticker.upper(), period="1y", interval="4h", progress=False)
        if df.empty:
            return {"error": "not found"}
        df    = clean_df(df)
        df    = calc_indicators(df, es, el)
        last  = float(df["Close"].iloc[-1])
        first = float(df["Close"].iloc[0])
        rsi_s = df["RSI"].dropna()
        rsi   = float(rsi_s.iloc[-1]) if not rsi_s.empty else None

        def last_val(col):
            if col not in df.columns: return None
            s = df[col].dropna()
            return float(s.iloc[-1]) if not s.empty else None

        last_high = float(df["High"].iloc[-1])
        last_low  = float(df["Low"].iloc[-1])
        fractales = calc_fractales(last, cfg)
        ft        = detect_fractal_touch(last_high, last_low, last, fractales)

        return {
            "ticker":           ticker.upper(),
            "price":            last,
            "change_pct":       round((last - first) / first * 100, 2),
            "rsi":              round(rsi, 1) if rsi is not None else None,
            "ema_short":        last_val(f"EMA{es}"),
            "ema_long":         last_val(f"EMA{el}"),
            "ema_short_name":   f"EMA{es}",
            "ema_long_name":    f"EMA{el}",
            "fractal_touch":    ft["touch"],
            "fractal_price":    ft["price"],
            "fractal_is_major": ft["is_major"],
            "fractal_tipo":     ft["tipo"],
            "fractal_crosses":  ft["crosses"],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/watch")
async def watch(tickers: str = ""):
    all_alertas = []
    for t in tickers.split(","):
        t = t.strip()
        if not t: continue
        try:
            cfg = get_cfg(t)
            df  = yf.download(t.upper(), period="6mo", interval="4h", progress=False)
            if not df.empty:
                df = clean_df(df)
                df = calc_indicators(df, cfg["ema_short"], cfg["ema_long"])
                all_alertas.extend(detect_alerts(df, ticker=t.upper(),
                    ema_short=cfg["ema_short"], ema_long=cfg["ema_long"], cfg=cfg))
        except Exception:
            pass
    return {"alertas": all_alertas}


@app.get("/api/sparkline/{ticker}")
async def sparkline(ticker: str):
    try:
        df = yf.download(ticker.upper(), period="1mo", interval="1d", progress=False)
        if df.empty: return {"closes": [], "pct": 0}
        df     = clean_df(df)
        closes = df["Close"].dropna().tolist()
        pct    = (closes[-1] - closes[0]) / closes[0] * 100 if len(closes) > 1 else 0
        return {"closes": [float(c) for c in closes], "pct": round(pct, 2)}
    except Exception:
        return {"closes": [], "pct": 0}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
