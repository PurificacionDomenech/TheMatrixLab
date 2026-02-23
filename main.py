
import yfinance as yf
import pandas as pd
import numpy as np
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime, timedelta
import pytz

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Configuración por activo ──────────────────────────────────
# key_spacing:   distancia entre líneas fractales menores (amarillo)
# major_spacing: distancia entre líneas fractales mayores (negro, con zona)
# zone_size:     semiancho de la zona sombreada en niveles mayores
# ema_short/long: periodos de las EMAs

ASSET_CONFIG = {
    # ── US30 / Dow Jones ──────────────────────────────────────
    "^DJI":   {"key_spacing": 500,  "major_spacing": 1000, "zone_size": 100, "ema_short": 200, "ema_long": 800},
    "YM=F":   {"key_spacing": 500,  "major_spacing": 1000, "zone_size": 100, "ema_short": 200, "ema_long": 800},

    # ── NAS100 / Nasdaq ───────────────────────────────────────
    "^NDX":   {"key_spacing": 500,  "major_spacing": 1000, "zone_size": 100, "ema_short": 200, "ema_long": 800},
    "NQ=F":   {"key_spacing": 500,  "major_spacing": 1000, "zone_size": 100, "ema_short": 200, "ema_long": 800},
    "QQQ":    {"key_spacing": 10,   "major_spacing": 20,   "zone_size": 2,   "ema_short": 200, "ema_long": 800},

    # ── XAUUSD / Oro ──────────────────────────────────────────
    "GC=F":   {"key_spacing": 50,   "major_spacing": 100,  "zone_size": 10,  "ema_short": 200,  "ema_long": 800},
    "GLD":    {"key_spacing": 5,    "major_spacing": 10,   "zone_size": 1,   "ema_short": 200,  "ema_long": 800},
    "IAU":    {"key_spacing": 5,    "major_spacing": 10,   "zone_size": 1,   "ema_short": 200,  "ema_long": 800},

    # ── XAGUSD / Plata ────────────────────────────────────────
    "SI=F":   {"key_spacing": 1,    "major_spacing": 5,    "zone_size": 0.25,"ema_short": 200,  "ema_long": 800},
    "SLV":    {"key_spacing": 1,    "major_spacing": 5,    "zone_size": 0.25,"ema_short": 200,  "ema_long": 800},

    # ── WTI / Petróleo ────────────────────────────────────────
    "CL=F":   {"key_spacing": 2,    "major_spacing": 5,    "zone_size": 0.5, "ema_short": 200,  "ema_long": 800},
    "USO":    {"key_spacing": 2,    "major_spacing": 5,    "zone_size": 0.5, "ema_short": 200,  "ema_long": 800},

    # ── FOREX ─────────────────────────────────────────────────
    "USDJPY=X": {"key_spacing": 1,  "major_spacing": 5,    "zone_size": 0.25,"ema_short": 200,  "ema_long": 800},
    "GBPJPY=X": {"key_spacing": 1,  "major_spacing": 5,    "zone_size": 0.25,"ema_short": 200,  "ema_long": 800},
    "EURUSD=X": {"key_spacing": 0.005,"major_spacing":0.01,"zone_size":0.001,"ema_short": 200,  "ema_long": 800},
    "AUDUSD=X": {"key_spacing": 0.005,"major_spacing":0.01,"zone_size":0.001,"ema_short": 200,  "ema_long": 800},

    # ── Bonos / Dollar ────────────────────────────────────────
    "^TNX":   {"key_spacing": 0.1,  "major_spacing": 0.5,  "zone_size": 0.05,"ema_short": 200,  "ema_long": 800},  # US10Y
    "^TYX":   {"key_spacing": 0.1,  "major_spacing": 0.5,  "zone_size": 0.05,"ema_short": 200,  "ema_long": 800},  # US20/30Y
    "DX=F":   {"key_spacing": 1,    "major_spacing": 5,    "zone_size": 0.25,"ema_short": 200,  "ema_long": 800},  # DXY

    # ── S&P 500 ───────────────────────────────────────────────
    "^GSPC":  {"key_spacing": 50,   "major_spacing": 100,  "zone_size": 10,  "ema_short": 200, "ema_long": 800},
    "SPY":    {"key_spacing": 10,   "major_spacing": 50,   "zone_size": 2,   "ema_short": 200, "ema_long": 800},
    "VOO":    {"key_spacing": 10,   "major_spacing": 50,   "zone_size": 2,   "ema_short": 200, "ema_long": 800},

    # ── Russell 2000 ──────────────────────────────────────────
    "^RUT":   {"key_spacing": 25,   "major_spacing": 50,   "zone_size": 5,   "ema_short": 200, "ema_long": 800},
    "IWM":    {"key_spacing": 5,    "major_spacing": 10,   "zone_size": 1,   "ema_short": 200, "ema_long": 800},

    # ── Cripto ────────────────────────────────────────────────
    "BTC-USD":{"key_spacing": 1000, "major_spacing": 5000, "zone_size": 250, "ema_short": 200,  "ema_long": 800},
    "ETH-USD":{"key_spacing": 50,   "major_spacing": 200,  "zone_size": 25,  "ema_short": 200,  "ema_long": 800},

    # ── ETFs varios ───────────────────────────────────────────
    "VTI":    {"key_spacing": 10,   "major_spacing": 50,   "zone_size": 2,   "ema_short": 200, "ema_long": 800},
    "QQQM":   {"key_spacing": 5,    "major_spacing": 20,   "zone_size": 1,   "ema_short": 200, "ema_long": 800},
    "GDX":    {"key_spacing": 2,    "major_spacing": 5,    "zone_size": 0.5, "ema_short": 200,  "ema_long": 800},
    "SMH":    {"key_spacing": 10,   "major_spacing": 50,   "zone_size": 2,   "ema_short": 200, "ema_long": 800},
    "XLE":    {"key_spacing": 2,    "major_spacing": 10,   "zone_size": 0.5, "ema_short": 200, "ema_long": 800},
    "AAPL":   {"key_spacing": 5,    "major_spacing": 20,   "zone_size": 1,   "ema_short": 200, "ema_long": 800},

    # ── Default ───────────────────────────────────────────────
    "_default": {"key_spacing": 50, "major_spacing": 100,  "zone_size": 10,  "ema_short": 200, "ema_long": 800},
}

def get_asset_config(ticker: str) -> dict:
    t = ticker.upper()
    if t in ASSET_CONFIG:
        return ASSET_CONFIG[t]
    # Heurística: si precio > 5000 → US30-like
    return ASSET_CONFIG["_default"]

def clean_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

def calcular_indicadores(df, ema_short=200, ema_long=800):
    df[f"EMA{ema_short}"] = df["Close"].ewm(span=ema_short, adjust=False).mean()
    df[f"EMA{ema_long}"]  = df["Close"].ewm(span=ema_long,  adjust=False).mean()

    # RSI 14
    delta = df["Close"].diff()
    gain  = delta.where(delta > 0, 0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df["RSI"] = 100 - (100 / (1 + gain / loss))

    return df

def calcular_fractales(precio_actual: float, cfg: dict, n_above=30, n_below=30) -> dict:
    """Genera niveles fractales alrededor del precio actual."""
    key_sp    = cfg["key_spacing"]
    major_sp  = cfg["major_spacing"]
    zone_size = cfg["zone_size"]

    base = round(precio_actual / key_sp) * key_sp
    levels = []

    for i in range(-n_below, n_above + 1):
        nivel = base + i * key_sp
        is_major = round(nivel % major_sp) == 0
        levels.append({
            "price":    nivel,
            "is_major": is_major,
            "zone_top": nivel + zone_size,
            "zone_bot": nivel - zone_size,
        })

    return {"levels": levels, "key_spacing": key_sp, "major_spacing": major_sp, "zone_size": zone_size}

def calcular_year_week_open(df: pd.DataFrame) -> dict:
    """Calcula apertura del año y semana actuales desde datos 4h."""
    result = {"year_open": None, "week_open": None}
    if df.empty:
        return result

    now = df.index[-1]
    # Apertura del año: primer open del año en curso
    year_start = pd.Timestamp(year=now.year, month=1, day=1, tz=now.tz if now.tz else None)
    year_df = df[df.index >= year_start]
    if not year_df.empty:
        result["year_open"] = float(year_df["Open"].iloc[0])

    # Apertura de la semana: primer open del lunes de esta semana
    week_start = now - pd.Timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0)
    week_df = df[df.index >= week_start]
    if not week_df.empty:
        result["week_open"] = float(week_df["Open"].iloc[0])

    return result

def detectar_alertas(df, ticker="", ema_short=200, ema_long=800):
    alertas = []
    n = len(df) - 1
    if n < 2:
        return alertas

    precio_now  = float(df["Close"].iloc[n])
    precio_prev = float(df["Close"].iloc[n - 1])
    prefix = f"[{ticker}] " if ticker else ""

    col_s = f"EMA{ema_short}"
    col_l = f"EMA{ema_long}"

    for col, nombre in [(col_s, f"EMA{ema_short}"), (col_l, f"EMA{ema_long}")]:
        if col not in df.columns:
            continue
        ema_now  = df[col].iloc[n]
        ema_prev = df[col].iloc[n-1]
        if not (pd.notna(ema_now) and pd.notna(ema_prev)):
            continue
        if precio_prev < ema_prev and precio_now >= ema_now:
            alertas.append({"nivel": "bullish", "msg": prefix + f"Precio cruza {nombre} al alza ${precio_now:.2f}"})
        elif precio_prev > ema_prev and precio_now <= ema_now:
            alertas.append({"nivel": "bearish", "msg": prefix + f"Precio cruza {nombre} a la baja ${precio_now:.2f}"})
        elif ema_now > 0 and abs(precio_now - ema_now) / ema_now * 100 <= 0.4:
            alertas.append({"nivel": "info", "msg": prefix + f"Precio tocando {nombre} ${precio_now:.2f}"})

    # Cruce EMAs entre sí
    es_now  = df[col_s].iloc[n]  if col_s in df.columns else None
    es_prev = df[col_s].iloc[n-1] if col_s in df.columns else None
    el_now  = df[col_l].iloc[n]  if col_l in df.columns else None
    el_prev = df[col_l].iloc[n-1] if col_l in df.columns else None

    if all(pd.notna(x) for x in [es_now, es_prev, el_now, el_prev] if x is not None):
        if es_prev < el_prev and es_now >= el_now:
            alertas.append({"nivel": "bullish", "msg": prefix + f"Golden Cross EMA{ema_short}/{ema_long}"})
        elif es_prev > el_prev and es_now <= el_now:
            alertas.append({"nivel": "bearish", "msg": prefix + f"Death Cross EMA{ema_short}/{ema_long}"})

    return alertas

def safe(v):
    return float(v) if pd.notna(v) else None

def ts_ms(idx):
    return [int(t.timestamp() * 1000) for t in idx]

@app.get("/")
async def index():
    return FileResponse("templates/index.html")

@app.get("/api/chart/{ticker}")
async def get_chart(ticker: str):
    try:
        cfg = get_asset_config(ticker)
        ema_short = cfg["ema_short"]
        ema_long  = cfg["ema_long"]

        # Descargamos ~2 años en 4h para tener suficientes datos para EMA800
        df = yf.download(ticker.upper(), period="2y", interval="4h", progress=False)
        if df.empty:
            return {"error": "Simbolo no encontrado: " + ticker}

        df = clean_df(df)
        df = calcular_indicadores(df, ema_short, ema_long)

        # Ajuste config por precio real (heurística si no está en ASSET_CONFIG)
        ultimo_precio = float(df["Close"].iloc[-1])
        if ticker.upper() not in ASSET_CONFIG:
            if ultimo_precio > 5000:
                cfg = ASSET_CONFIG["^DJI"]
            elif ultimo_precio > 500:
                cfg = ASSET_CONFIG["_default"]
            else:
                cfg = {"key_spacing": round(ultimo_precio * 0.01, 2),
                       "major_spacing": round(ultimo_precio * 0.02, 2),
                       "zone_size": round(ultimo_precio * 0.002, 2),
                       "ema_short": ema_short, "ema_long": ema_long}

        timestamps = ts_ms(df.index)

        candles = [
            {"x": timestamps[i], "o": safe(df["Open"].iloc[i]),
             "h": safe(df["High"].iloc[i]), "l": safe(df["Low"].iloc[i]),
             "c": safe(df["Close"].iloc[i])}
            for i in range(len(df))
        ]

        def ema_series(col):
            if col not in df.columns:
                return []
            return [{"x": timestamps[i], "y": float(df[col].iloc[i])}
                    for i in range(len(df)) if pd.notna(df[col].iloc[i])]

        # RSI markers
        rsi_os, rsi_ob = [], []
        for i in range(len(df)):
            r = df["RSI"].iloc[i]
            if pd.notna(r):
                if r < 30:
                    rsi_os.append({"x": timestamps[i], "y": float(df["Close"].iloc[i])})
                elif r > 70:
                    rsi_ob.append({"x": timestamps[i], "y": float(df["Close"].iloc[i])})

        # Fractales
        fractales = calcular_fractales(ultimo_precio, cfg)

        # Aperturas año/semana
        opens = calcular_year_week_open(df)

        rsi_series = df["RSI"].dropna()
        rsi_c = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50

        first = float(df["Close"].iloc[0])
        alertas = detectar_alertas(df, ticker=ticker.upper(), ema_short=ema_short, ema_long=ema_long)

        return {
            "chart": {
                "candles":   candles,
                f"ema{ema_short}": ema_series(f"EMA{ema_short}"),
                f"ema{ema_long}":  ema_series(f"EMA{ema_long}"),
                "rsi_os":    rsi_os,
                "rsi_ob":    rsi_ob,
            },
            "fractales":    fractales,
            "opens":        opens,
            "last_price":   ultimo_precio,
            "change":       ultimo_precio - first,
            "change_pct":   (ultimo_precio - first) / first * 100,
            "rsi_current":  rsi_c,
            "alertas":      alertas,
            "asset_config": {"ema_short": ema_short, "ema_long": ema_long},
        }

    except Exception as e:
        return {"error": str(e)}

@app.get("/api/row/{ticker}")
async def get_row(ticker: str):
    try:
        cfg = get_asset_config(ticker)
        ema_short = cfg["ema_short"]
        ema_long  = cfg["ema_long"]

        df = yf.download(ticker.upper(), period="1y", interval="4h", progress=False)
        if df.empty:
            return {"error": "not found"}

        df = clean_df(df)
        df = calcular_indicadores(df, ema_short, ema_long)

        last  = float(df["Close"].iloc[-1])
        first = float(df["Close"].iloc[0])

        rsi_s = df["RSI"].dropna()
        rsi   = float(rsi_s.iloc[-1]) if not rsi_s.empty else None

        col_s = f"EMA{ema_short}"
        col_l = f"EMA{ema_long}"

        def last_val(col):
            if col not in df.columns:
                return None
            s = df[col].dropna()
            return float(s.iloc[-1]) if not s.empty else None

        return {
            "ticker":     ticker.upper(),
            "price":      last,
            "change_pct": round((last - first) / first * 100, 2),
            "rsi":        round(rsi, 1) if rsi is not None else None,
            "ema_short":  last_val(col_s),
            "ema_long":   last_val(col_l),
            "ema_short_name": f"EMA{ema_short}",
            "ema_long_name":  f"EMA{ema_long}",
        }

    except Exception as e:
        return {"error": str(e)}

@app.get("/api/watch")
async def watch_favorites(tickers: str = ""):
    all_alertas = []
    for t in tickers.split(","):
        t = t.strip()
        if not t:
            continue
        try:
            cfg = get_asset_config(t)
            df = yf.download(t.upper(), period="6mo", interval="4h", progress=False)
            if not df.empty:
                df = clean_df(df)
                df = calcular_indicadores(df, cfg["ema_short"], cfg["ema_long"])
                all_alertas.extend(detectar_alertas(df, ticker=t.upper(),
                                                    ema_short=cfg["ema_short"],
                                                    ema_long=cfg["ema_long"]))
        except Exception:
            pass
    return {"alertas": all_alertas}

@app.get("/api/sparkline/{ticker}")
async def sparkline(ticker: str):
    try:
        df = yf.download(ticker.upper(), period="1mo", interval="1d", progress=False)
        if df.empty:
            return {"closes": [], "pct": 0}
        df = clean_df(df)
        closes = df["Close"].dropna().tolist()
        pct = (closes[-1] - closes[0]) / closes[0] * 100 if len(closes) > 1 else 0
        return {"closes": [float(c) for c in closes], "pct": round(pct, 2)}
    except Exception:
        return {"closes": [], "pct": 0}

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
