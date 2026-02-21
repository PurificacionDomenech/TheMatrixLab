import yfinance as yf
import pandas as pd
import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="The Matrix Lab")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ─────────────────────────────────────────────
# MAPEO DE INTERVALOS
# 1d  → vela diaria   → descarga MAX histórico
# 1wk → vela semanal  → descarga max
# 1mo → vela mensual  → descarga max
# ─────────────────────────────────────────────
INTERVAL_MAP = {
    "4h":  ("4h",  "1y"),
    "1d":  ("1d",  "max"),
    "1wk": ("1wk", "max"),
    "1mo": ("1mo", "max"),
    "3mo": ("3mo", "max"),
}


def clean_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


# ─────────────────────────────────────────────
# CONFIGURACIÓN POR ACTIVO (MATRIX)
# ─────────────────────────────────────────────

def get_asset_config(ticker: str):
    t = ticker.upper()

    if t == "US30":
        return {
            "ema_short": 200,
            "ema_long": 800,
            "key_spacing": 500,
            "major_spacing": 1000,
            "zone_size": 100,
            "swing_lookback": 40,
        }

    if t == "XAUUSD":
        return {
            "ema_short": 20,
            "ema_long": 80,
            "key_spacing": 50,
            "major_spacing": 100,
            "zone_size": 10,
            "swing_lookback": 40,
        }

    # Por defecto
    return {
        "ema_short": 200,
        "ema_long": 800,
        "key_spacing": 500,
        "major_spacing": 1000,
        "zone_size": 100,
        "swing_lookback": 40,
    }


# ─────────────────────────────────────────────
# INDICADORES
# ─────────────────────────────────────────────

def calcular_indicadores(df):
    df["SMA20"]  = df["Close"].rolling(20).mean()
    df["SMA50"]  = df["Close"].rolling(50).mean()
    df["SMA100"] = df["Close"].rolling(100).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()

    delta = df["Close"].diff()
    gain  = delta.where(delta > 0, 0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df["RSI"] = 100 - (100 / (1 + gain / loss))

    # Supertrend
    df["TR"] = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift()).abs(),
        (df["Low"]  - df["Close"].shift()).abs()
    ], axis=1).max(axis=1)
    df["ATR"] = df["TR"].rolling(7).mean()
    hl2 = (df["High"] + df["Low"]) / 2
    df["UB"] = hl2 + 3.0 * df["ATR"]
    df["LB"] = hl2 - 3.0 * df["ATR"]
    df["ST"]  = np.nan
    df["Dir"] = 0
    for i in range(1, len(df)):
        ps = df.iloc[i-1]["ST"]
        pd_ = df.iloc[i-1]["Dir"]
        cl = float(df.iloc[i]["LB"])
        cu = float(df.iloc[i]["UB"])
        cc = float(df.iloc[i]["Close"])
        if np.isnan(ps):
            df.iloc[i, df.columns.get_loc("ST")]  = cl
            df.iloc[i, df.columns.get_loc("Dir")] = 1
            continue
        st = max(cl, ps) if pd_ == 1 else min(cu, ps)
        df.iloc[i, df.columns.get_loc("ST")]  = st
        df.iloc[i, df.columns.get_loc("Dir")] = 1 if cc > st else -1
    return df


# ─────────────────────────────────────────────
# ALERTAS (SMA CLÁSICAS)
# ─────────────────────────────────────────────

def detectar_alertas(df_daily, ticker=""):
    alertas = []
    n = len(df_daily) - 1
    if n < 2:
        return alertas

    precio_now  = float(df_daily["Close"].iloc[n])
    precio_prev = float(df_daily["Close"].iloc[n - 1])
    prefix = f"[{ticker}] " if ticker else ""

    smas = {
        "SMA20":  (df_daily["SMA20"].iloc[n],  df_daily["SMA20"].iloc[n-1]),
        "SMA50":  (df_daily["SMA50"].iloc[n],  df_daily["SMA50"].iloc[n-1]),
        "SMA100": (df_daily["SMA100"].iloc[n], df_daily["SMA100"].iloc[n-1]),
        "SMA200": (df_daily["SMA200"].iloc[n], df_daily["SMA200"].iloc[n-1]),
    }

    for nombre, (sma_now, sma_prev) in smas.items():
        if not (pd.notna(sma_now) and pd.notna(sma_prev)):
            continue
        if precio_prev < sma_prev and precio_now >= sma_now:
            alertas.append({
                "nivel": "bullish",
                "msg": f"📈 {prefix}Precio cruza {nombre} al alza — ${precio_now:,.2f}"
            })
        elif precio_prev > sma_prev and precio_now <= sma_now:
            alertas.append({
                "nivel": "bearish",
                "msg": f"📉 {prefix}Precio cruza {nombre} a la baja — ${precio_now:,.2f}"
            })
        elif abs(precio_now - sma_now) / sma_now * 100 <= 0.4:
            alertas.append({
                "nivel": "info",
                "msg": f"⚠️ {prefix}Precio tocando {nombre} — ${precio_now:,.2f}"
            })

    # Cruces entre medias
    s100_n, s100_p = smas["SMA100"]
    s200_n, s200_p = smas["SMA200"]
    if pd.notna(s100_n) and pd.notna(s200_n):
        if s100_p < s200_p and s100_n >= s200_n:
            alertas.append({"nivel": "bullish", "msg": f"🟢 {prefix}Golden Cross — SMA100 sobre SMA200"})
        elif s100_p > s200_p and s100_n <= s200_n:
            alertas.append({"nivel": "bearish", "msg": f"🔴 {prefix}Death Cross — SMA100 bajo SMA200"})

    s20_n, s20_p = smas["SMA20"]
    s50_n, s50_p = smas["SMA50"]
    if pd.notna(s20_n) and pd.notna(s50_n):
        if s20_p < s50_p and s20_n >= s50_n:
            alertas.append({"nivel": "bullish", "msg": f"🟡 {prefix}SMA20 cruza sobre SMA50"})
        elif s20_p > s50_p and s20_n <= s50_n:
            alertas.append({"nivel": "bearish", "msg": f"🟠 {prefix}SMA20 cruza bajo SMA50"})

    return alertas


def get_daily_df(ticker):
    df = yf.download(ticker.upper(), period="max", interval="1d", progress=False)
    if df.empty:
        return None
    df = clean_df(df)
    df = calcular_indicadores(df)
    return df


def ts_ms(idx):
    return [int(t.timestamp() * 1000) for t in idx]


def safe(v):
    return float(v) if pd.notna(v) else None


# ─────────────────────────────────────────────
# TARJETA MATRIX PARA FAVORITOS
# ─────────────────────────────────────────────

def calcular_tarjeta_matrix(df_daily: pd.DataFrame, ticker: str):
    cfg = get_asset_config(ticker)
    last_row = df_daily.iloc[-1]

    precio = float(last_row["Close"])
    first = float(df_daily["Close"].iloc[0])
    cambio_pct = (precio - first) / first * 100 if first != 0 else 0.0

    rsi = float(last_row["RSI"]) if pd.notna(last_row["RSI"]) else None

    # EMAs Matrix
    ema_short_series = df_daily["Close"].ewm(span=cfg["ema_short"]).mean()
    ema_long_series  = df_daily["Close"].ewm(span=cfg["ema_long"]).mean()
    ema_short = float(ema_short_series.iloc[-1])
    ema_long  = float(ema_long_series.iloc[-1])
    ema_trend = "bullish" if ema_short > ema_long else "bearish"

    # Fibonacci 55.9%
    lookback = cfg["swing_lookback"]
    if len(df_daily) >= lookback:
        swing_high = df_daily["High"].rolling(lookback).max().iloc[-1]
        swing_low  = df_daily["Low"].rolling(lookback).min().iloc[-1]
        price_range = swing_high - swing_low
        fib_559 = swing_low + price_range * 0.559 if price_range > 0 else None
    else:
        fib_559 = None

    # Aperturas anual y semanal
    try:
        year_open = df_daily.resample("12M").first()["Open"].iloc[-1]
    except Exception:
        year_open = None
    try:
        week_open = df_daily.resample("W").first()["Open"].iloc[-1]
    except Exception:
        week_open = None

    # Nivel clave (fractales)
    key_spacing = cfg["key_spacing"]
    zone_size = cfg["zone_size"]
    nearest_key = round(precio / key_spacing) * key_spacing

    # Confluencias (3 de 5)
    confluencias = 0

    # 1) RSI sobrevendido
    if rsi is not None and rsi <= 30:
        confluencias += 1

    # 2) Cruce/relación EMAs (alcista)
    if ema_trend == "bullish":
        confluencias += 1

    # 3) Nivel clave respetado (precio cerca de nivel clave)
    if abs(precio - nearest_key) <= zone_size:
        confluencias += 1

    # 4) Aperturas (precio cerca de apertura anual o semanal)
    apertura_confluencia = False
    for lvl in [year_open, week_open]:
        if lvl is not None and lvl != 0:
            if abs(precio - lvl) / lvl * 100 <= 0.5:
                apertura_confluencia = True
                break
    if apertura_confluencia:
        confluencias += 1

    # 5) Fibonacci 55.9% cerca del precio
    if fib_559 is not None and precio != 0:
        if abs(precio - fib_559) / precio * 100 <= 0.5:
            confluencias += 1

    # Estado según confluencias
    if confluencias >= 4:
        estado = "favorable"
    elif confluencias == 3:
        estado = "interesante"
    elif confluencias == 2:
        estado = "considerar"
    else:
        estado = "no_favorable"

    return {
        "ticker": ticker.upper(),
        "precio": round(precio, 2),
        "cambio_pct": round(cambio_pct, 2),
        "rsi": round(rsi, 2) if rsi is not None else None,
        "ema_short": cfg["ema_short"],
        "ema_long": cfg["ema_long"],
        "ema_trend": ema_trend,
        "fib_559": round(fib_559, 2) if fib_559 is not None else None,
        "apertura_anual": round(float(year_open), 2) if year_open is not None else None,
        "apertura_semanal": round(float(week_open), 2) if week_open is not None else None,
        "confluencias": int(confluencias),
        "estado": estado,
    }


# ─────────────────────────────────────────────
# RUTAS
# ─────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse("templates/index.html")


@app.get("/api/chart/{ticker}")
async def get_chart(ticker: str, interval: str = "1d"):
    try:
        yf_interval, yf_period = INTERVAL_MAP.get(interval, ("1d", "max"))

        df_candles = yf.download(ticker.upper(), period=yf_period,
                                 interval=yf_interval, progress=False)
        if df_candles.empty:
            return {"error": f"Símbolo no encontrado: {ticker}"}
        df_candles = clean_df(df_candles)

        if interval == "1d":
            df_daily = df_candles.copy()
            df_daily = calcular_indicadores(df_daily)
        else:
            df_daily = get_daily_df(ticker)
            if df_daily is None:
                df_daily = df_candles.copy()
                df_daily = calcular_indicadores(df_daily)

        timestamps = ts_ms(df_candles.index)
        candles = [
            {
                "x": timestamps[i],
                "o": safe(df_candles["Open"].iloc[i]),
                "h": safe(df_candles["High"].iloc[i]),
                "l": safe(df_candles["Low"].iloc[i]),
                "c": safe(df_candles["Close"].iloc[i])
            }
            for i in range(len(df_candles))
        ]

        def sma_series(col):
            series = []
            for i in range(len(df_daily)):
                v = df_daily[col].iloc[i]
                if pd.notna(v):
                    series.append({
                        "x": int(df_daily.index[i].timestamp() * 1000),
                        "y": float(v)
                    })
            return series

        rsi_vals   = df_daily["RSI"].values
        close_vals = df_daily["Close"].values
        daily_ts   = ts_ms(df_daily.index)

        rsi_os = [
            {"x": daily_ts[i], "y": float(close_vals[i])}
            for i in range(len(df_daily))
            if pd.notna(rsi_vals[i]) and rsi_vals[i] < 30
        ]

        rsi_ob = [
            {"x": daily_ts[i], "y": float(close_vals[i])}
            for i in range(len(df_daily))
            if pd.notna(rsi_vals[i]) and rsi_vals[i] > 70
        ]

        st_buy  = [
            {"x": daily_ts[i], "y": float(df_daily["ST"].iloc[i])}
            for i in range(len(df_daily))
            if pd.notna(df_daily["ST"].iloc[i]) and df_daily["Dir"].iloc[i] == 1
        ]
        st_sell = [
            {"x": daily_ts[i], "y": float(df_daily["ST"].iloc[i])}
            for i in range(len(df_daily))
            if pd.notna(df_daily["ST"].iloc[i]) and df_daily["Dir"].iloc[i] == -1
        ]

        chart_data = {
            "candles":  candles,
            "sma20":    sma_series("SMA20"),
            "sma50":    sma_series("SMA50"),
            "sma100":   sma_series("SMA100"),
            "sma200":   sma_series("SMA200"),
            "rsi_os":   rsi_os,
            "rsi_ob":   rsi_ob,
            "st_buy":   st_buy,
            "st_sell":  st_sell,
        }

        alertas = detectar_alertas(df_daily)

        last  = float(df_candles["Close"].iloc[-1])
        first = float(df_candles["Close"].iloc[0])
        rsi_c = float(df_daily["RSI"].dropna().iloc[-1]) if not df_daily["RSI"].dropna().empty else 50

        return {
            "chart":       chart_data,
            "last_price":  last,
            "change":      last - first,
            "change_pct":  (last - first) / first * 100,
            "rsi_current": rsi_c,
            "alertas":     alertas,
        }

    except Exception as e:
        return {"error": str(e)}


@app.get("/api/watch")
async def watch_favorites(tickers: str = ""):
    favoritos = []
    for t in tickers.split(","):
        t = t.strip()
        if not t:
            continue
        try:
            df = get_daily_df(t)
            if df is not None and not df.empty:
                info = calcular_tarjeta_matrix(df, t)
                favoritos.append(info)
        except Exception:
            pass
    return {"favoritos": favoritos}


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
    import uvicorn, os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)