import yfinance as yf
import pandas as pd
import numpy as np
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

INTERVAL_MAP = {
    "1d":  ("1d",  "max"),
    "1wk": ("1wk", "max"),
    "1mo": ("1mo", "max"),
}

# ─────────────────────────────────────────────────────────────────────────────
# VERSIÓN A/B: detección automática por ticker o precio
# ─────────────────────────────────────────────────────────────────────────────

VERSION_A_TICKERS = {
    "^GSPC", "^NDX", "^DJI", "^RUT", "^IBEX", "^FTSE", "^GDAXI", "^FCHI",
    "NAS100", "US30", "GER40", "UK100", "JP225", "HK50", "SPX500", "US2000",
    "DIA", "SPY", "QQQ", "IWM", "VOO", "VTI",
}

def detectar_version(ticker: str, df: pd.DataFrame) -> str:
    """Devuelve 'A' o 'B' según el ticker y el precio medio."""
    t = ticker.upper()
    if t in VERSION_A_TICKERS:
        return "A"
    # Forex / metales / crypto → B
    for kw in ["USD", "EUR", "GBP", "JPY", "XAU", "XAG", "BTC", "ETH", "OIL", "WTI", "BRT"]:
        if kw in t:
            return "B"
    # Fallback por precio
    precio_medio = float(df["Close"].median()) if not df.empty else 0
    return "A" if precio_medio > 1000 else "B"


def get_version_params(version: str) -> dict:
    """Parámetros de indicadores según versión."""
    if version == "A":
        return {
            "ema_short": 200, "ema_long": 800,
            "frac_minor": 500, "frac_major": 1000,
            "zone_size": 100, "key_mult": 1000,
            "fib_lookback": 300,
        }
    return {
        "ema_short": 20,  "ema_long": 80,
        "frac_minor": 50, "frac_major": 100,
        "zone_size": 10,  "key_mult": 100,
        "fib_lookback": 100,
    }


# ─────────────────────────────────────────────────────────────────────────────
# LIMPIEZA DE DATAFRAME
# ─────────────────────────────────────────────────────────────────────────────

def clean_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# CÁLCULO DE INDICADORES (siempre calcula las 4 SMAs + EMAs de versión)
# ─────────────────────────────────────────────────────────────────────────────

def calcular_indicadores(df, version="B"):
    p = get_version_params(version)

    # ── SMAs fijas (para la tabla general) ──
    df["SMA20"]  = df["Close"].rolling(20).mean()
    df["SMA80"]  = df["Close"].rolling(80).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["SMA800"] = df["Close"].rolling(800).mean()

    # ── EMAs de versión (para alertas A/B) ──
    df["EMA_S"] = df["Close"].ewm(span=p["ema_short"], adjust=False).mean()
    df["EMA_L"] = df["Close"].ewm(span=p["ema_long"],  adjust=False).mean()

    # ── RSI ──
    delta = df["Close"].diff()
    gain  = delta.where(delta > 0, 0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df["RSI"] = 100 - (100 / (1 + gain / loss))

    # ── SuperTrend ──
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
        ps  = df.iloc[i-1]["ST"]
        pd_ = df.iloc[i-1]["Dir"]
        cl  = float(df.iloc[i]["LB"])
        cu  = float(df.iloc[i]["UB"])
        cc  = float(df.iloc[i]["Close"])
        if np.isnan(ps):
            df.iloc[i, df.columns.get_loc("ST")]  = cl
            df.iloc[i, df.columns.get_loc("Dir")] = 1
            continue
        st = max(cl, ps) if pd_ == 1 else min(cu, ps)
        df.iloc[i, df.columns.get_loc("ST")]  = st
        df.iloc[i, df.columns.get_loc("Dir")] = 1 if cc > st else -1

    # ── Fibonacci 55.9% dinámico ──
    lb = p["fib_lookback"]
    roll_hi = df["High"].rolling(lb).max()
    roll_lo = df["Low"].rolling(lb).min()
    df["FIB559"] = roll_lo + (roll_hi - roll_lo) * 0.559

    return df


# ─────────────────────────────────────────────────────────────────────────────
# ALERTAS CON LÓGICA A/B
# ─────────────────────────────────────────────────────────────────────────────

def detectar_alertas(df, ticker="", version="B"):
    alertas = []
    n = len(df) - 1
    if n < 2:
        return alertas

    p = get_version_params(version)
    precio_now  = float(df["Close"].iloc[n])
    precio_prev = float(df["Close"].iloc[n - 1])
    prefix = f"[{ticker}] " if ticker else ""
    ver_tag = f"(v{version})"

    # ── 1. EMAs de versión ──────────────────────────────────────────────────
    ema_s_now  = df["EMA_S"].iloc[n]
    ema_s_prev = df["EMA_S"].iloc[n - 1]
    ema_l_now  = df["EMA_L"].iloc[n]
    ema_l_prev = df["EMA_L"].iloc[n - 1]

    if pd.notna(ema_s_now) and pd.notna(ema_l_now):
        if ema_s_prev < ema_l_prev and ema_s_now >= ema_l_now:
            alertas.append({"nivel": "bullish",
                "msg": prefix + f"🟢 Cruce Dorado EMA{p['ema_short']}/{p['ema_long']} {ver_tag}"})
        elif ema_s_prev > ema_l_prev and ema_s_now <= ema_l_now:
            alertas.append({"nivel": "bearish",
                "msg": prefix + f"🔴 Cruce de Muerte EMA{p['ema_short']}/{p['ema_long']} {ver_tag}"})

    # ── 2. SMAs fijas (cruce 20/80 y 200/800 para la tabla) ────────────────
    smas = {
        "SMA20":  (df["SMA20"].iloc[n],  df["SMA20"].iloc[n-1]),
        "SMA80":  (df["SMA80"].iloc[n],  df["SMA80"].iloc[n-1]),
        "SMA200": (df["SMA200"].iloc[n], df["SMA200"].iloc[n-1]),
        "SMA800": (df["SMA800"].iloc[n], df["SMA800"].iloc[n-1]),
    }

    for nombre, (sma_now, sma_prev) in smas.items():
        if not (pd.notna(sma_now) and pd.notna(sma_prev)):
            continue
        if precio_prev < sma_prev and precio_now >= sma_now:
            alertas.append({"nivel": "bullish",
                "msg": prefix + f"Precio cruza {nombre} al alza ${precio_now:.2f} {ver_tag}"})
        elif precio_prev > sma_prev and precio_now <= sma_now:
            alertas.append({"nivel": "bearish",
                "msg": prefix + f"Precio cruza {nombre} a la baja ${precio_now:.2f} {ver_tag}"})
        elif sma_now > 0 and abs(precio_now - sma_now) / sma_now * 100 <= 0.4:
            alertas.append({"nivel": "info",
                "msg": prefix + f"Precio tocando {nombre} ${precio_now:.2f} {ver_tag}"})

    # Cruce rápido SMA20/80
    s20_n, s20_p = smas["SMA20"]
    s80_n, s80_p = smas["SMA80"]
    if pd.notna(s20_n) and pd.notna(s80_n):
        if s20_p < s80_p and s20_n >= s80_n:
            alertas.append({"nivel": "bullish", "msg": prefix + "Golden Cross SMA20/80"})
        elif s20_p > s80_p and s20_n <= s80_n:
            alertas.append({"nivel": "bearish", "msg": prefix + "Death Cross SMA20/80"})

    # Cruce macro SMA200/800
    s200_n, s200_p = smas["SMA200"]
    s800_n, s800_p = smas["SMA800"]
    if pd.notna(s200_n) and pd.notna(s800_n):
        if s200_p < s800_p and s200_n >= s800_n:
            alertas.append({"nivel": "bullish", "msg": prefix + "Golden Cross SMA200/800"})
        elif s200_p > s800_p and s200_n <= s800_n:
            alertas.append({"nivel": "bearish", "msg": prefix + "Death Cross SMA200/800"})

    # ── 3. RSI extremo ──────────────────────────────────────────────────────
    rsi_now  = df["RSI"].iloc[n]
    rsi_prev = df["RSI"].iloc[n - 1]
    if pd.notna(rsi_now) and pd.notna(rsi_prev):
        if rsi_prev >= 30 and rsi_now < 30:
            alertas.append({"nivel": "bullish",
                "msg": prefix + f"RSI sobreventa (<30) → {rsi_now:.1f} {ver_tag}"})
        elif rsi_prev <= 70 and rsi_now > 70:
            alertas.append({"nivel": "bearish",
                "msg": prefix + f"RSI sobrecompra (>70) → {rsi_now:.1f} {ver_tag}"})

    # ── 4. Nivel clave ──────────────────────────────────────────────────────
    km = p["key_mult"]
    zs = p["zone_size"]
    key_near = round(precio_now / km) * km
    if abs(precio_now - key_near) <= (zs * 0.5):
        alertas.append({"nivel": "info",
            "msg": prefix + f"Precio cerca de nivel clave ×{km}: {key_near} {ver_tag}"})

    # ── 5. Fibonacci 55.9% ─────────────────────────────────────────────────
    fib_now = df["FIB559"].iloc[n]
    if pd.notna(fib_now) and abs(precio_now - fib_now) / max(fib_now, 1) * 100 <= 0.5:
        alertas.append({"nivel": "info",
            "msg": prefix + f"Precio en Fibonacci 55.9% → {fib_now:.2f} {ver_tag}"})

    return alertas


# ─────────────────────────────────────────────────────────────────────────────
# CONFLUENCIAS (5 condiciones → válido si ≥ 3)
# ─────────────────────────────────────────────────────────────────────────────

def calcular_confluencias(df, version="B"):
    p  = get_version_params(version)
    n  = len(df) - 1
    if n < 2:
        return {"count": 0, "valid": False, "conditions": {}}

    precio = float(df["Close"].iloc[n])
    zs     = p["zone_size"]
    km     = p["key_mult"]

    # C1: RSI extremo
    rsi = df["RSI"].iloc[n]
    c1  = pd.notna(rsi) and (rsi < 35 or rsi > 65)

    # C2: Cruce de EMAs (versión A/B)
    ema_s_n = df["EMA_S"].iloc[n];  ema_s_p = df["EMA_S"].iloc[n-1]
    ema_l_n = df["EMA_L"].iloc[n];  ema_l_p = df["EMA_L"].iloc[n-1]
    cross_bull = pd.notna(ema_s_n) and ema_s_p < ema_l_p and ema_s_n >= ema_l_n
    cross_bear = pd.notna(ema_s_n) and ema_s_p > ema_l_p and ema_s_n <= ema_l_n
    c2 = cross_bull or cross_bear

    # C3: Nivel clave
    key_near = round(precio / km) * km
    c3 = abs(precio - key_near) <= (zs * 0.5)

    # C4: Apertura semanal (usamos primera vela de la semana disponible)
    # Aproximación: comparamos con el primer cierre de la ventana semanal reciente
    # (En producción se puede refinar con datos de 1wk)
    c4 = False  # placeholder — se calcula si hay datos semanales

    # C5: Fibonacci 55.9%
    fib = df["FIB559"].iloc[n]
    c5  = pd.notna(fib) and abs(precio - fib) / max(fib, 1) * 100 <= 0.5

    count  = sum([c1, c2, c3, c4, c5])
    valid  = count >= 3

    return {
        "count": count,
        "valid": valid,
        "conditions": {
            "rsi_extremo":  c1,
            "cruce_ema":    c2,
            "nivel_clave":  c3,
            "apertura":     c4,
            "fibonacci":    c5,
        },
        "rsi_val":   round(float(rsi), 1) if pd.notna(rsi) else None,
        "fib_val":   round(float(fib), 2) if pd.notna(fib) else None,
        "key_level": int(key_near),
        "ema_short": p["ema_short"],
        "ema_long":  p["ema_long"],
        "cross_dir": "bull" if cross_bull else ("bear" if cross_bear else "none"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def safe(v):
    return float(v) if pd.notna(v) else None

def ts_ms(idx):
    return [int(t.timestamp() * 1000) for t in idx]


# ─────────────────────────────────────────────────────────────────────────────
# RUTAS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse("templates/index.html")


@app.get("/api/chart/{ticker}")
async def get_chart(ticker: str, interval: str = "1d"):
    try:
        yf_interval, yf_period = INTERVAL_MAP.get(interval, ("1d", "max"))
        df = yf.download(ticker.upper(), period=yf_period, interval=yf_interval, progress=False)
        if df.empty:
            return {"error": "Simbolo no encontrado: " + ticker}

        df = clean_df(df)
        version = detectar_version(ticker, df)
        df = calcular_indicadores(df, version)

        timestamps = ts_ms(df.index)
        candles = [
            {
                "x": timestamps[i],
                "o": safe(df["Open"].iloc[i]),
                "h": safe(df["High"].iloc[i]),
                "l": safe(df["Low"].iloc[i]),
                "c": safe(df["Close"].iloc[i]),
            }
            for i in range(len(df))
        ]

        def sma_series(col):
            return [
                {"x": timestamps[i], "y": float(df[col].iloc[i])}
                for i in range(len(df))
                if pd.notna(df[col].iloc[i])
            ]

        def ema_series(col):
            return [
                {"x": timestamps[i], "y": float(df[col].iloc[i])}
                for i in range(len(df))
                if pd.notna(df[col].iloc[i])
            ]

        # RSI markers
        rsi_os, rsi_ob = [], []
        for i in range(len(df)):
            r = df["RSI"].iloc[i]
            if pd.notna(r):
                if r < 30:
                    rsi_os.append({"x": timestamps[i], "y": float(df["Close"].iloc[i])})
                elif r > 70:
                    rsi_ob.append({"x": timestamps[i], "y": float(df["Close"].iloc[i])})

        # SuperTrend
        st_buy, st_sell = [], []
        for i in range(len(df)):
            st = df["ST"].iloc[i]
            dr = df["Dir"].iloc[i]
            if pd.notna(st):
                if dr == 1:
                    st_buy.append({"x": timestamps[i], "y": float(st)})
                else:
                    st_sell.append({"x": timestamps[i], "y": float(st)})

        # Fibonacci
        fib_series = [
            {"x": timestamps[i], "y": float(df["FIB559"].iloc[i])}
            for i in range(len(df))
            if pd.notna(df["FIB559"].iloc[i])
        ]

        last  = float(df["Close"].iloc[-1])
        first = float(df["Close"].iloc[0])
        rsi_series = df["RSI"].dropna()
        rsi_c = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50

        alertas     = detectar_alertas(df, ticker=ticker.upper(), version=version)
        confluencias = calcular_confluencias(df, version=version)

        p = get_version_params(version)

        return {
            "version": version,
            "version_params": p,
            "chart": {
                "candles": candles,
                "sma20":  sma_series("SMA20"),
                "sma80":  sma_series("SMA80"),
                "sma200": sma_series("SMA200"),
                "sma800": sma_series("SMA800"),
                "ema_s":  ema_series("EMA_S"),
                "ema_l":  ema_series("EMA_L"),
                "rsi_os": rsi_os,
                "rsi_ob": rsi_ob,
                "st_buy": st_buy,
                "st_sell": st_sell,
                "fib559": fib_series,
            },
            "last_price":    last,
            "change":        last - first,
            "change_pct":    (last - first) / first * 100,
            "rsi_current":   rsi_c,
            "alertas":       alertas,
            "confluencias":  confluencias,
        }

    except Exception as e:
        return {"error": str(e)}


@app.get("/api/row/{ticker}")
async def get_row(ticker: str):
    try:
        df = yf.download(ticker.upper(), period="1y", interval="1d", progress=False)
        if df.empty:
            return {"error": "not found"}

        df = clean_df(df)
        version = detectar_version(ticker, df)
        df = calcular_indicadores(df, version)

        last  = float(df["Close"].iloc[-1])
        first = float(df["Close"].iloc[0])

        def last_val(col):
            s = df[col].dropna()
            return float(s.iloc[-1]) if not s.empty else None

        rsi_s = df["RSI"].dropna()
        rsi   = float(rsi_s.iloc[-1]) if not rsi_s.empty else None

        dir_s  = df["Dir"].dropna()
        st_dir = int(dir_s.iloc[-1]) if not dir_s.empty else 0

        confluencias = calcular_confluencias(df, version=version)

        return {
            "ticker":       ticker.upper(),
            "version":      version,
            "price":        last,
            "change_pct":   round((last - first) / first * 100, 2),
            "rsi":          round(rsi, 1) if rsi is not None else None,
            "sma20":        last_val("SMA20"),
            "sma80":        last_val("SMA80"),
            "sma200":       last_val("SMA200"),
            "sma800":       last_val("SMA800"),
            "ema_s":        last_val("EMA_S"),
            "ema_l":        last_val("EMA_L"),
            "st_dir":       st_dir,
            "confluencias": confluencias,
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
            df = yf.download(t.upper(), period="1y", interval="1d", progress=False)
            if not df.empty:
                df = clean_df(df)
                version = detectar_version(t, df)
                df = calcular_indicadores(df, version)
                all_alertas.extend(detectar_alertas(df, ticker=t.upper(), version=version))
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
