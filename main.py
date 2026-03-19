import yfinance as yf
import pandas as pd
import numpy as np
import asyncio
import time
import os
import httpx

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    from contextlib import asynccontextmanager
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    HAS_SCHEDULER = True
except ImportError:
    HAS_SCHEDULER = False
    print("[WARN] apscheduler no instalado")

try:
    from notifier import (
        notify_alertas,
        notify_users_with_alerts,
        register_chat,
        send_telegram_to,
        get_user_prefs,
        save_user_prefs,
    )

    HAS_NOTIFIER = True
except Exception as e:
    HAS_NOTIFIER = False
    print(f"[WARN] notifier no disponible: {e}")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
WATCH_TICKERS = [
    "^DJI",
    "GC=F",
    "^NDX",
    "USDJPY=X",
    "GBPJPY=X",
    "EURUSD=X",
    "AUDUSD=X",
    "SI=F",
    "CL=F",
]

_sent_cache: dict = {}
_DEDUP_SECONDS = 4 * 3600

ASSET_CONFIG = {
    "^DJI": {
        "key_spacing": 500,
        "major_spacing": 1000,
        "zone_size": 100,
        "ema_short": 200,
        "ema_long": 800,
    },
    "^NDX": {
        "key_spacing": 500,
        "major_spacing": 1000,
        "zone_size": 100,
        "ema_short": 200,
        "ema_long": 800,
    },
    "GC=F": {
        "key_spacing": 50,
        "major_spacing": 100,
        "zone_size": 10,
        "ema_short": 200,
        "ema_long": 800,
    },
    "GLD": {
        "key_spacing": 5,
        "major_spacing": 10,
        "zone_size": 1,
        "ema_short": 200,
        "ema_long": 800,
    },
    "IAU": {
        "key_spacing": 5,
        "major_spacing": 10,
        "zone_size": 1,
        "ema_short": 200,
        "ema_long": 800,
    },
    "SI=F": {
        "key_spacing": 1,
        "major_spacing": 5,
        "zone_size": 0.25,
        "ema_short": 200,
        "ema_long": 800,
    },
    "CL=F": {
        "key_spacing": 2,
        "major_spacing": 5,
        "zone_size": 0.5,
        "ema_short": 200,
        "ema_long": 800,
    },
    "USDJPY=X": {
        "key_spacing": 1,
        "major_spacing": 5,
        "zone_size": 0.25,
        "ema_short": 200,
        "ema_long": 800,
    },
    "GBPJPY=X": {
        "key_spacing": 1,
        "major_spacing": 5,
        "zone_size": 0.25,
        "ema_short": 200,
        "ema_long": 800,
    },
    "EURUSD=X": {
        "key_spacing": 0.005,
        "major_spacing": 0.01,
        "zone_size": 0.001,
        "ema_short": 200,
        "ema_long": 800,
    },
    "AUDUSD=X": {
        "key_spacing": 0.005,
        "major_spacing": 0.01,
        "zone_size": 0.001,
        "ema_short": 200,
        "ema_long": 800,
    },
    "^TNX": {
        "key_spacing": 0.1,
        "major_spacing": 0.5,
        "zone_size": 0.05,
        "ema_short": 200,
        "ema_long": 800,
    },
    "^TYX": {
        "key_spacing": 0.1,
        "major_spacing": 0.5,
        "zone_size": 0.05,
        "ema_short": 200,
        "ema_long": 800,
    },
    "DX=F": {
        "key_spacing": 1,
        "major_spacing": 5,
        "zone_size": 0.25,
        "ema_short": 200,
        "ema_long": 800,
    },
    "^GSPC": {
        "key_spacing": 50,
        "major_spacing": 100,
        "zone_size": 10,
        "ema_short": 200,
        "ema_long": 800,
    },
    "SPY": {
        "key_spacing": 10,
        "major_spacing": 50,
        "zone_size": 2,
        "ema_short": 200,
        "ema_long": 800,
    },
    "VOO": {
        "key_spacing": 10,
        "major_spacing": 50,
        "zone_size": 2,
        "ema_short": 200,
        "ema_long": 800,
    },
    "^RUT": {
        "key_spacing": 25,
        "major_spacing": 50,
        "zone_size": 5,
        "ema_short": 200,
        "ema_long": 800,
    },
    "IWM": {
        "key_spacing": 5,
        "major_spacing": 10,
        "zone_size": 1,
        "ema_short": 200,
        "ema_long": 800,
    },
    "BTC-USD": {
        "key_spacing": 1000,
        "major_spacing": 5000,
        "zone_size": 250,
        "ema_short": 200,
        "ema_long": 800,
    },
    "ETH-USD": {
        "key_spacing": 50,
        "major_spacing": 200,
        "zone_size": 25,
        "ema_short": 200,
        "ema_long": 800,
    },
    "QQQ": {
        "key_spacing": 10,
        "major_spacing": 20,
        "zone_size": 2,
        "ema_short": 200,
        "ema_long": 800,
    },
    "QQQM": {
        "key_spacing": 5,
        "major_spacing": 20,
        "zone_size": 1,
        "ema_short": 200,
        "ema_long": 800,
    },
    "GDX": {
        "key_spacing": 2,
        "major_spacing": 5,
        "zone_size": 0.5,
        "ema_short": 200,
        "ema_long": 800,
    },
    "SMH": {
        "key_spacing": 10,
        "major_spacing": 50,
        "zone_size": 2,
        "ema_short": 200,
        "ema_long": 800,
    },
    "XLE": {
        "key_spacing": 2,
        "major_spacing": 10,
        "zone_size": 0.5,
        "ema_short": 200,
        "ema_long": 800,
    },
    "AAPL": {
        "key_spacing": 5,
        "major_spacing": 20,
        "zone_size": 1,
        "ema_short": 200,
        "ema_long": 800,
    },
    "_default": {
        "key_spacing": 50,
        "major_spacing": 100,
        "zone_size": 10,
        "ema_short": 200,
        "ema_long": 800,
    },
}


async def async_download(ticker, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: yf.download(ticker, **kwargs))


def get_cfg(t):
    return ASSET_CONFIG.get(t.upper(), ASSET_CONFIG["_default"])


def clean_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def safe(v):
    return float(v) if pd.notna(v) else None


def ts_ms(idx):
    return [int(t.timestamp() * 1000) for t in idx]


def calc_indicators(df, es=200, el=800):
    df[f"EMA{es}"] = df["Close"].ewm(span=es, adjust=False).mean()
    df[f"EMA{el}"] = df["Close"].ewm(span=el, adjust=False).mean()
    d = df["Close"].diff()
    losses = (-d.where(d < 0, 0)).rolling(14).mean().replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + d.where(d > 0, 0).rolling(14).mean() / losses))
    return df


def calc_fractales(precio, cfg, n_above=30, n_below=30):
    ks, ms, zs = cfg["key_spacing"], cfg["major_spacing"], cfg["zone_size"]
    base = round(precio / ks) * ks
    levels = []
    for i in range(-n_below, n_above + 1):
        p = base + i * ks
        levels.append(
            {
                "price": p,
                "is_major": round(p % ms) == 0,
                "zone_top": p + zs,
                "zone_bot": p - zs,
            }
        )
    return {"levels": levels, "key_spacing": ks, "major_spacing": ms, "zone_size": zs}


def detect_fractal_touch(high, low, close, fractales):
    zs, best = fractales["zone_size"], None
    for level in fractales["levels"]:
        lp = level["price"]
        crosses = high >= (lp - zs) and low <= (lp + zs)
        in_zone = abs(close - lp) <= zs * 1.5
        if crosses or in_zone:
            tipo = "soporte" if close >= lp else "resistencia"
            c = {
                "touch": True,
                "price": lp,
                "is_major": level["is_major"],
                "tipo": tipo,
                "crosses": crosses,
            }
            if best is None or (not best["is_major"] and level["is_major"]):
                best = c
    return best or {
        "touch": False,
        "price": None,
        "is_major": False,
        "tipo": None,
        "crosses": False,
    }


def calc_opens(df):
    result = {"year_open": None, "week_open": None}
    if df.empty:
        return result
    now = df.index[-1]
    ys = pd.Timestamp(year=now.year, month=1, day=1, tz=now.tz if now.tz else None)
    ydf = df[df.index >= ys]
    if not ydf.empty:
        result["year_open"] = float(ydf["Open"].iloc[0])
    ws = (now - pd.Timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
    wdf = df[df.index >= ws]
    if not wdf.empty:
        result["week_open"] = float(wdf["Open"].iloc[0])
    return result


def detect_alerts(df, ticker="", ema_short=200, ema_long=800, cfg=None):
    alertas = []
    n = len(df) - 1
    if n < 2:
        return alertas
    pn, pp = float(df["Close"].iloc[n]), float(df["Close"].iloc[n - 1])
    prefix = f"[{ticker}] " if ticker else ""
    cs, cl = f"EMA{ema_short}", f"EMA{ema_long}"

    # RSI actual
    rsi_val = None
    if "RSI" in df.columns:
        r = df["RSI"].iloc[n]
        if pd.notna(r):
            rsi_val = float(r)

    # ── EMA crosses / touches ──────────────────────────────────
    for col, nombre, pts in [(cs, f"EMA{ema_short}", 2), (cl, f"EMA{ema_long}", 4)]:
        if col not in df.columns:
            continue
        en, ep = df[col].iloc[n], df[col].iloc[n - 1]
        if not (pd.notna(en) and pd.notna(ep)):
            continue
        en_f = float(en)
        if pp < ep and pn >= en_f:
            alertas.append({
                "nivel": "bullish",
                "tipo": "ema_cross_up",
                "ema_nombre": nombre,
                "ema_val": en_f,
                "close": pn,
                "rsi": rsi_val,
                "pts": pts,
                "msg": prefix + f"Precio cruza {nombre} al alza ${pn:.5g}",
            })
        elif pp > ep and pn <= en_f:
            alertas.append({
                "nivel": "bearish",
                "tipo": "ema_cross_down",
                "ema_nombre": nombre,
                "ema_val": en_f,
                "close": pn,
                "rsi": rsi_val,
                "pts": pts,
                "msg": prefix + f"Precio cruza {nombre} a la baja ${pn:.5g}",
            })
        elif en_f > 0 and abs(pn - en_f) / en_f * 100 <= 0.4:
            alertas.append({
                "nivel": "info",
                "tipo": "ema_touch",
                "ema_nombre": nombre,
                "ema_val": en_f,
                "close": pn,
                "rsi": rsi_val,
                "pts": pts,
                "msg": prefix + f"Precio tocando {nombre} ${pn:.5g}",
            })

    # ── Golden / Death Cross ───────────────────────────────────
    esn = df[cs].iloc[n] if cs in df.columns else None
    esp = df[cs].iloc[n - 1] if cs in df.columns else None
    eln = df[cl].iloc[n] if cl in df.columns else None
    elp = df[cl].iloc[n - 1] if cl in df.columns else None
    if all(pd.notna(x) for x in [esn, esp, eln, elp] if x is not None):
        if esp < elp and esn >= eln:
            alertas.append({
                "nivel": "bullish",
                "tipo": "golden_cross",
                "close": pn,
                "rsi": rsi_val,
                "pts": 3,
                "msg": prefix + f"Golden Cross EMA{ema_short}/{ema_long}",
            })
        elif esp > elp and esn <= eln:
            alertas.append({
                "nivel": "bearish",
                "tipo": "death_cross",
                "close": pn,
                "rsi": rsi_val,
                "pts": 3,
                "msg": prefix + f"Death Cross EMA{ema_short}/{ema_long}",
            })

    # ── Fractales ─────────────────────────────────────────────
    if cfg is not None:
        fr = calc_fractales(pn, cfg)
        ft = detect_fractal_touch(
            float(df["High"].iloc[n]), float(df["Low"].iloc[n]), pn, fr
        )
        if ft["touch"]:
            alertas.append({
                "nivel": "bullish" if ft["tipo"] == "soporte" else "bearish",
                "tipo": "fractal",
                "fractal_precio": ft["price"],
                "fractal_tipo": ft["tipo"],
                "fractal_mayor": ft["is_major"],
                "close": pn,
                "rsi": rsi_val,
                "pts": 3 if ft["is_major"] else 1,
                "msg": prefix + f"⬡ Vela toca fractal {'MAYOR ' if ft['is_major'] else ''}{ft['tipo'].upper()} ${ft['price']:.5g}",
            })
    return alertas


# ─── CONFLUENCIAS ────────────────────────────────────────────


def evaluate_confluencias(df, ticker="", cfg=None, opens=None):
    """
    Evalúa las 5 confluencias de la matriz y devuelve resultado estructurado.
    Devuelve alerta solo si se cumplen >= 3 de 5.
    """
    if len(df) < 14:
        return None

    n     = len(df) - 1
    price = float(df["Close"].iloc[n])
    es    = cfg["ema_short"] if cfg else 200
    el    = cfg["ema_long"]  if cfg else 800

    rsi_raw = df["RSI"].iloc[n] if "RSI" in df.columns else None
    rsi = float(rsi_raw) if pd.notna(rsi_raw) else 50.0

    ema_s_val = None
    if f"EMA{es}" in df.columns and pd.notna(df[f"EMA{es}"].iloc[n]):
        ema_s_val = float(df[f"EMA{es}"].iloc[n])
    ema_l_val = None
    if f"EMA{el}" in df.columns and pd.notna(df[f"EMA{el}"].iloc[n]):
        ema_l_val = float(df[f"EMA{el}"].iloc[n])

    confluencias = []
    puntos = 0

    # ① RSI sobrevendido (<30) o sobrecomprado (>70)
    if rsi < 30:
        confluencias.append({"id": 1, "ok": True,
            "texto": f"RSI sobrevendido ({rsi:.1f})", "tipo": "bullish"})
        puntos += 1
    elif rsi > 70:
        confluencias.append({"id": 1, "ok": True,
            "texto": f"RSI sobrecomprado ({rsi:.1f})", "tipo": "bearish"})
        puntos += 1
    else:
        confluencias.append({"id": 1, "ok": False,
            "texto": f"RSI neutro ({rsi:.1f})", "tipo": "info"})

    # ② EMA200 > EMA800 — tendencia alcista
    if ema_s_val and ema_l_val:
        if ema_s_val > ema_l_val:
            confluencias.append({"id": 2, "ok": True,
                "texto": f"EMA{es} ({ema_s_val:.5g}) > EMA{el} ({ema_l_val:.5g}) — tendencia alcista",
                "tipo": "bullish"})
            puntos += 1
        else:
            confluencias.append({"id": 2, "ok": False,
                "texto": f"EMA{es} < EMA{el} — tendencia bajista", "tipo": "bearish"})

    # ③ Precio respetando nivel clave fractal como soporte
    if cfg:
        fr = calc_fractales(price, cfg)
        ft = detect_fractal_touch(
            float(df["High"].iloc[n]), float(df["Low"].iloc[n]), price, fr)
        if ft["touch"] and ft["tipo"] == "soporte":
            tag = "MAYOR" if ft["is_major"] else "menor"
            confluencias.append({"id": 3, "ok": True,
                "texto": f"Nivel clave {tag} como soporte en {ft['price']:.5g}",
                "tipo": "bullish"})
            puntos += 1
        else:
            confluencias.append({"id": 3, "ok": False,
                "texto": "Sin nivel clave fractal relevante", "tipo": "info"})

    # ④ Precio en zona de apertura anual o semanal (±0.3%)
    if opens:
        yo  = opens.get("year_open")
        wo  = opens.get("week_open")
        tol = price * 0.003
        if yo and abs(price - yo) <= tol:
            confluencias.append({"id": 4, "ok": True,
                "texto": f"Precio en apertura anual ({yo:.5g})", "tipo": "bullish"})
            puntos += 1
        elif wo and abs(price - wo) <= tol:
            confluencias.append({"id": 4, "ok": True,
                "texto": f"Precio en apertura semanal ({wo:.5g})", "tipo": "bullish"})
            puntos += 1
        else:
            confluencias.append({"id": 4, "ok": False,
                "texto": "Lejos de apertura anual/semanal", "tipo": "info"})
    else:
        confluencias.append({"id": 4, "ok": False,
            "texto": "Datos de apertura no disponibles", "tipo": "info"})

    # ⑤ Retroceso Fibonacci 55.9% del rango del período
    high_p = float(df["High"].max())
    low_p  = float(df["Low"].min())
    fib559 = high_p - (high_p - low_p) * 0.559
    tol_f  = (high_p - low_p) * 0.015
    if abs(price - fib559) <= tol_f:
        confluencias.append({"id": 5, "ok": True,
            "texto": f"Fibonacci 55.9% en {fib559:.5g} (rango {low_p:.5g}–{high_p:.5g})",
            "tipo": "bullish"})
        puntos += 1
    else:
        pct_dist = (price - fib559) / fib559 * 100
        confluencias.append({"id": 5, "ok": False,
            "texto": f"Fib 55.9% en {fib559:.5g} ({pct_dist:+.1f}% de distancia)",
            "tipo": "info"})

    # Determinar estado
    if puntos >= 4:
        estado = "FAVORABLE"
        nivel  = "bullish"
    elif puntos == 3:
        estado = "INTERESANTE"
        nivel  = "bullish"
    elif puntos == 2:
        estado = "CONSIDERAR"
        nivel  = "info"
    else:
        estado = "NO AHORA"
        nivel  = "info"

    return {
        "ticker":       ticker.upper(),
        "precio":       price,
        "rsi":          rsi,
        "puntos":       puntos,
        "estado":       estado,
        "nivel":        nivel,
        "confluencias": confluencias,
        "alert":        puntos >= 3,   # True = enviar notificación
    }


# ─── SCHEDULER ───────────────────────────────────────────────


async def _check_tickers(tickers: list, num_candles: int = 1, label: str = "") -> dict:
    """
    Revisa los tickers dados. num_candles controla cuántas velas recientes analizar.
    Retorna alerts_by_ticker con las alertas nuevas (sin duplicados en cache).
    """
    now = time.time()
    alerts_by_ticker: dict = {}
    for t in tickers:
        try:
            cfg = get_cfg(t)
            df = await async_download(
                t.upper(), period="6mo", interval="4h", progress=False
            )
            if df.empty:
                continue
            df = clean_df(df)
            df = calc_indicators(df, cfg["ema_short"], cfg["ema_long"])
            opens_data = calc_opens(df)
            nuevas = []
            # Analizar las últimas num_candles velas
            for i in range(min(num_candles, len(df))):
                fila = len(df) - 1 - i
                df_slice = df.iloc[: fila + 1]
                ts = df.index[fila]
                try:
                    hora = pd.Timestamp(ts).strftime("%d/%m %H:%M")
                    ts_parsed = pd.Timestamp(ts)
                    dia_num  = ts_parsed.weekday()
                    dia_name = ts_parsed.strftime("%A")
                except Exception:
                    hora     = ""
                    dia_num  = -1
                    dia_name = ""

                resultado = evaluate_confluencias(
                    df_slice,
                    ticker=t.upper(),
                    cfg=cfg,
                    opens=opens_data,
                )

                if resultado and resultado.get("alert"):
                    # Clave de deduplicación: ticker + estado + precio redondeado
                    key = f"{t}_{resultado['estado']}_{round(resultado['precio'], -1)}"
                    if now - _sent_cache.get(key, 0) > _DEDUP_SECONDS:
                        nuevas.append({
                            "nivel":     resultado["nivel"],
                            "msg":       f"[{t.upper()}] {resultado['estado']} {hora}".strip(),
                            "hora":      hora,
                            "dia_num":   dia_num,
                            "dia_name":  dia_name,
                            "resultado": resultado,
                        })
                        _sent_cache[key] = now
            if nuevas:
                alerts_by_ticker[t.upper()] = nuevas
        except Exception as e:
            print(f"[{label or 'scheduler'}] Error en {t}: {e}")
    return alerts_by_ticker


async def scheduled_watch():
    """Revisión periódica — analiza la última vela de cada ticker vigilado."""
    if not HAS_NOTIFIER:
        return
    alerts_by_ticker = await _check_tickers(
        WATCH_TICKERS, num_candles=1, label="scheduler"
    )
    if alerts_by_ticker:
        total = sum(len(v) for v in alerts_by_ticker.values())
        print(
            f"[scheduler] {total} alertas nuevas en {len(alerts_by_ticker)} ticker(s)"
        )
        await notify_users_with_alerts(alerts_by_ticker)
    else:
        print("[scheduler] Sin alertas nuevas")


async def daily_catchup():
    """Catch-up al arrancar: revisa las últimas 6 velas (≈24h) y envía lo pendiente."""
    if not HAS_NOTIFIER:
        return
    print("[catchup] Revisando últimas 24h de alertas…")
    alerts_by_ticker = await _check_tickers(
        WATCH_TICKERS, num_candles=6, label="catchup"
    )
    if alerts_by_ticker:
        total = sum(len(v) for v in alerts_by_ticker.values())
        print(f"[catchup] {total} alertas del día enviadas")
        await notify_users_with_alerts(alerts_by_ticker)
    else:
        print("[catchup] Sin alertas nuevas en las últimas 24h")


# ─── APP ─────────────────────────────────────────────────────

if HAS_SCHEDULER:
    from contextlib import asynccontextmanager

    async def _process_tg_message(message: dict):
        if not HAS_NOTIFIER or not message:
            return
        try:
            chat_id = message.get("chat", {}).get("id")
            username = message.get("from", {}).get("username", "")
            text = message.get("text", "").strip()
            if not chat_id:
                return
            if text.startswith("/start"):
                print(f"[telegram] /start de @{username or '?'} (chat_id={chat_id})")
                ok = await register_chat(chat_id, username)
                print(f"[telegram] register_chat → {'OK' if ok else 'FALLO'}")
                sent = await send_telegram_to(
                    chat_id,
                    f"✅ <b>¡Suscrito a The Matrix Lab!</b>\n\n"
                    f"⬡ Recibirás alertas automáticas cada 4H de tus activos favoritos.\n\n"
                    f"📋 <b>Tu Chat ID es:</b> <code>{chat_id}</code>\n"
                    f"Cópialo y pégalo en el panel de Notificaciones de la app para personalizar tus alertas.\n\n"
                    f"Comandos disponibles:\n"
                    f"/status — estado del sistema\n"
                    f"/test — prueba de alertas\n"
                    f"/stop — cancelar suscripción"
                    if ok
                    else "⚠️ No se pudo registrar. Inténtalo de nuevo.",
                )
                print(f"[telegram] Respuesta enviada → {'OK' if sent else 'FALLO'}")
            elif text.startswith("/stop"):
                await send_telegram_to(
                    chat_id, "🔕 Suscripción cancelada. Envía /start para reactivar."
                )
            elif text.startswith("/status"):
                await send_telegram_to(
                    chat_id, "✅ <b>The Matrix Lab activo</b>\nRevisión cada 4 horas."
                )
            elif text.startswith("/test"):
                await send_telegram_to(
                    chat_id,
                    "🟢 <b>[TEST]</b> El sistema funciona correctamente.\n"
                    "⬡ Recibirás mensajes cuando haya señales reales.",
                )
        except Exception as e:
            print(f"[telegram] Error procesando mensaje: {e}")

    async def _tg_polling(token: str):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(
                    f"https://api.telegram.org/bot{token}/deleteWebhook",
                    json={"drop_pending_updates": False},
                )
            print(
                "[telegram] Polling iniciado (webhook eliminado, mensajes pendientes conservados)"
            )
        except Exception as e:
            print(f"[telegram] No se pudo eliminar webhook: {e}")
        offset = 0
        while True:
            try:
                async with httpx.AsyncClient(timeout=35) as c:
                    r = await c.get(
                        f"https://api.telegram.org/bot{token}/getUpdates",
                        params={
                            "offset": offset,
                            "timeout": 30,
                            "allowed_updates": ["message"],
                        },
                    )
                    if r.status_code == 200:
                        for upd in r.json().get("result", []):
                            offset = upd["update_id"] + 1
                            await _process_tg_message(upd.get("message", {}))
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[telegram] Polling error: {e}")
                await asyncio.sleep(5)

    @asynccontextmanager
    async def lifespan(app):
        scheduler = None
        polling_task = None
        token = os.getenv("TELEGRAM_TOKEN", "")
        if token:
            polling_task = asyncio.create_task(_tg_polling(token))
        try:
            scheduler = AsyncIOScheduler()
            # Revisión cada 30 min para alertas en tiempo real
            scheduler.add_job(scheduled_watch, "interval", minutes=30, id="watch_30m")
            scheduler.start()
            print("[scheduler] Iniciado · revisión cada 30 min")
            # Catch-up: enviar alertas de las últimas 24h al arrancar
            asyncio.create_task(daily_catchup())
        except Exception as e:
            print(f"[scheduler] Error al iniciar: {e}")
        yield
        if polling_task:
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                pass
        if scheduler:
            try:
                scheduler.shutdown()
            except:
                pass

    app = FastAPI(lifespan=lifespan)
else:
    app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── WEBHOOK TELEGRAM (fallback) ─────────────────────────────


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        body = await request.json()
        message = body.get("message") or body.get("edited_message", {})
        if HAS_SCHEDULER and message:
            await _process_tg_message(message)
    except Exception as e:
        print(f"[webhook] Error: {e}")
    return JSONResponse({"ok": True})


# ─── RUTAS ───────────────────────────────────────────────────


@app.get("/")
async def splash():
    for name in ("Splash.html", "splash.html"):
        if os.path.exists(f"templates/{name}"):
            return FileResponse(f"templates/{name}")
    return FileResponse("templates/index.html")


@app.get("/app")
async def dashboard():
    return FileResponse("templates/index.html")


@app.get("/confirm")
async def confirm_email():
    return FileResponse("templates/confirm.html")


@app.get("/en")
async def splash_en():
    return FileResponse("templates/Splash_en.html")


@app.get("/en/app")
async def dashboard_en():
    return FileResponse("templates/index_en.html")


# ─── NOTIFICACIONES ──────────────────────────────────────────


@app.get("/api/notify")
async def force_notify():
    if not HAS_NOTIFIER:
        return {"ok": False, "msg": "Notifier no configurado."}
    await daily_catchup()
    return {"ok": True, "msg": "Revisión de las últimas 24h completada."}


@app.get("/api/subs")
async def list_subs():
    if not HAS_NOTIFIER:
        return {"ok": False, "subs": 0}
    from notifier import get_chat_ids

    ids = await get_chat_ids()
    return {"ok": True, "subs": len(ids), "chat_ids": ids}


@app.get("/api/bot-info")
async def bot_info():
    token = os.getenv("TELEGRAM_TOKEN", "")
    if not token:
        return {"ok": False, "username": None}
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"https://api.telegram.org/bot{token}/getMe")
            d = r.json()
            if d.get("ok"):
                return {
                    "ok": True,
                    "username": d["result"].get("username"),
                    "name": d["result"].get("first_name"),
                }
    except:
        pass
    return {"ok": False, "username": None}


@app.get("/api/mail-status")
async def mail_status():
    mf = os.getenv("MAIL_FROM", "")
    mp = os.getenv("MAIL_PASSWORD", "")
    mt = os.getenv("MAIL_TO", "")
    ok = bool(mf and mp and mt)
    return {"configured": ok, "mail_to": mt if ok else None}


@app.get("/api/notifier-status")
async def notifier_status():
    tg = bool(
        os.getenv("TELEGRAM_TOKEN")
        and os.getenv("SUPABASE_URL")
        and os.getenv("SUPABASE_KEY")
    )
    em = bool(
        os.getenv("MAIL_FROM") and os.getenv("MAIL_PASSWORD") and os.getenv("MAIL_TO")
    )
    return {
        "ok": tg or em,
        "telegram": tg,
        "email": em,
        "scheduler": HAS_SCHEDULER,
        "notifier": HAS_NOTIFIER,
        "next_run": "~4h desde el último ciclo",
    }


# ─── PREFERENCIAS DE USUARIO ─────────────────────────────────


@app.get("/api/user/notif-prefs")
async def get_notif_prefs(request: Request):
    """Obtiene las preferencias del usuario autenticado."""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        return JSONResponse({"ok": False, "msg": "No autenticado"}, status_code=401)
    if not HAS_NOTIFIER:
        return {"ok": False, "prefs": {}}
    prefs = await get_user_prefs(user_id)
    return {"ok": True, "prefs": prefs}


@app.post("/api/user/notif-prefs")
async def save_notif_prefs(request: Request):
    """Guarda las preferencias de notificación del usuario."""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        return JSONResponse({"ok": False, "msg": "No autenticado"}, status_code=401)
    if not HAS_NOTIFIER:
        return {"ok": False, "msg": "Notifier no disponible"}
    try:
        body = await request.json()
        ok = await save_user_prefs(user_id, body)
        return {"ok": ok, "msg": "Guardado" if ok else "Error al guardar"}
    except Exception as e:
        return JSONResponse({"ok": False, "msg": str(e)}, status_code=400)


# ─── DATOS DE MERCADO ────────────────────────────────────────


@app.get("/api/chart/{ticker}")
async def get_chart(ticker: str):
    try:
        cfg = get_cfg(ticker)
        es, el = cfg["ema_short"], cfg["ema_long"]
        df = await async_download(
            ticker.upper(), period="2y", interval="4h", progress=False
        )
        if df.empty:
            return {"error": "Simbolo no encontrado: " + ticker}
        df = clean_df(df)
        df = calc_indicators(df, es, el)
        ult = float(df["Close"].iloc[-1])
        fr = calc_fractales(ult, cfg)
        ts = ts_ms(df.index)
        candles = [
            {
                "x": ts[i],
                "o": safe(df["Open"].iloc[i]),
                "h": safe(df["High"].iloc[i]),
                "l": safe(df["Low"].iloc[i]),
                "c": safe(df["Close"].iloc[i]),
            }
            for i in range(len(df))
        ]

        def ema_s(col):
            if col not in df.columns:
                return []
            return [
                {"x": ts[i], "y": float(df[col].iloc[i])}
                for i in range(len(df))
                if pd.notna(df[col].iloc[i])
            ]

        ros, rob = [], []
        for i in range(len(df)):
            r = df["RSI"].iloc[i]
            if pd.notna(r):
                if r < 30:
                    ros.append({"x": ts[i], "y": float(df["Close"].iloc[i])})
                elif r > 70:
                    rob.append({"x": ts[i], "y": float(df["Close"].iloc[i])})
        ftc = []
        for i in range(len(df)):
            h, l, c = (
                safe(df["High"].iloc[i]),
                safe(df["Low"].iloc[i]),
                safe(df["Close"].iloc[i]),
            )
            if None in (h, l, c):
                continue
            ft = detect_fractal_touch(h, l, c, fr)
            if ft["touch"] and ft["is_major"]:
                ftc.append(
                    {"x": ts[i], "y": c, "tipo": ft["tipo"], "price": ft["price"]}
                )
        opens = calc_opens(df)
        rsi_s = df["RSI"].dropna()
        first = float(df["Close"].iloc[0])
        return {
            "chart": {
                "candles": candles,
                f"ema{es}": ema_s(f"EMA{es}"),
                f"ema{el}": ema_s(f"EMA{el}"),
                "rsi_os": ros,
                "rsi_ob": rob,
                "fractal_touch_candles": ftc,
            },
            "fractales": fr,
            "opens": opens,
            "last_price": ult,
            "change": ult - first,
            "change_pct": (ult - first) / first * 100,
            "rsi_current": float(rsi_s.iloc[-1]) if not rsi_s.empty else 50,
            "alertas": detect_alerts(
                df, ticker=ticker.upper(), ema_short=es, ema_long=el, cfg=cfg
            ),
            "asset_config": {"ema_short": es, "ema_long": el},
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/row/{ticker}")
async def get_row(ticker: str):
    try:
        cfg = get_cfg(ticker)
        es, el = cfg["ema_short"], cfg["ema_long"]
        df = await async_download(
            ticker.upper(), period="1y", interval="4h", progress=False
        )
        if df.empty:
            return {"error": "not found"}
        df = clean_df(df)
        df = calc_indicators(df, es, el)
        last, first = float(df["Close"].iloc[-1]), float(df["Close"].iloc[0])
        rsi_s = df["RSI"].dropna()
        rsi = float(rsi_s.iloc[-1]) if not rsi_s.empty else None

        def lv(col):
            if col not in df.columns:
                return None
            s = df[col].dropna()
            return float(s.iloc[-1]) if not s.empty else None

        fr = calc_fractales(last, cfg)
        ft = detect_fractal_touch(
            float(df["High"].iloc[-1]), float(df["Low"].iloc[-1]), last, fr
        )
        opens = calc_opens(df)
        confl = evaluate_confluencias(df, ticker=ticker.upper(), cfg=cfg, opens=opens)
        return {
            "ticker": ticker.upper(),
            "price": last,
            "change_pct": round((last - first) / first * 100, 2),
            "rsi": round(rsi, 1) if rsi else None,
            "ema_short": lv(f"EMA{es}"),
            "ema_long": lv(f"EMA{el}"),
            "ema_short_name": f"EMA{es}",
            "ema_long_name": f"EMA{el}",
            "fractal_touch": ft["touch"],
            "fractal_price": ft["price"],
            "fractal_is_major": ft["is_major"],
            "fractal_tipo": ft["tipo"],
            "fractal_crosses": ft["crosses"],
            "confluencias_puntos": confl["puntos"] if confl else 0,
            "confluencias_estado": confl["estado"] if confl else "NO AHORA",
            "confluencias": confl["confluencias"] if confl else [],
            "confluencias_rsi": confl["rsi"] if confl else None,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/watch")
async def watch(tickers: str = ""):
    all_alertas = []
    for t in tickers.split(","):
        t = t.strip()
        if not t:
            continue
        try:
            cfg = get_cfg(t)
            df = await async_download(
                t.upper(), period="6mo", interval="4h", progress=False
            )
            if not df.empty:
                df = clean_df(df)
                df = calc_indicators(df, cfg["ema_short"], cfg["ema_long"])
                all_alertas.extend(
                    detect_alerts(
                        df,
                        ticker=t.upper(),
                        ema_short=cfg["ema_short"],
                        ema_long=cfg["ema_long"],
                        cfg=cfg,
                    )
                )
        except:
            pass
    return {"alertas": all_alertas}


@app.get("/api/sparkline/{ticker}")
async def sparkline(ticker: str):
    try:
        df = await async_download(
            ticker.upper(), period="1mo", interval="1d", progress=False
        )
        if df.empty:
            return {"closes": [], "pct": 0}
        df = clean_df(df)
        closes = df["Close"].dropna().tolist()
        pct = (closes[-1] - closes[0]) / closes[0] * 100 if len(closes) > 1 else 0
        return {"closes": [float(c) for c in closes], "pct": round(pct, 2)}
    except:
        return {"closes": [], "pct": 0}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
