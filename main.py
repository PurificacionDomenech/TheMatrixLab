from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import numpy as np

app = FastAPI()

# =============================
# CORS
# =============================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================
# PERFILES DE ACTIVO
# =============================

ASSET_PROFILES = {
    "indices": {
        "ema_fast": 200,
        "ema_slow": 800,
        "level_minor": 500,
        "level_major": 1000,
        "zone_buffer": 100,
    },
    "metals": {
        "ema_fast": 20,
        "ema_slow": 80,
        "level_minor": 50,
        "level_major": 100,
        "zone_buffer": 10,
    }
}

PROFILE_MAP = {
    "US30": "indices",
    "SPX": "indices",
    "NAS100": "indices",

    "XAUUSD": "metals",
    "XAGUSD": "metals",
}

def get_profile(ticker: str):
    profile_key = PROFILE_MAP.get(ticker, "indices")
    return ASSET_PROFILES[profile_key]

# =============================
# INDICADORES
# =============================

def calculate_rsi(df, period=14):
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_emas(df, profile):
    df["EMA_FAST"] = df["Close"].ewm(span=profile["ema_fast"]).mean()
    df["EMA_SLOW"] = df["Close"].ewm(span=profile["ema_slow"]).mean()
    return df

def calculate_levels(price, profile):
    step_minor = profile["level_minor"]
    step_major = profile["level_major"]
    zone = profile["zone_buffer"]

    nearest_minor = round(price / step_minor) * step_minor
    nearest_major = round(price / step_major) * step_major

    zone_high = nearest_major + zone
    zone_low = nearest_major - zone

    return {
        "minor_level": nearest_minor,
        "major_level": nearest_major,
        "zone_high": zone_high,
        "zone_low": zone_low,
    }

def calculate_fib_559(df):
    high = df["High"].max()
    low = df["Low"].min()
    return high - (high - low) * 0.559

# =============================
# CONFLUENCIA
# =============================

def calculate_confluence(df, profile):
    latest = df.iloc[-1]

    score = 0
    conditions = {}

    # RSI sobrevendido
    if latest["RSI"] <= 30:
        score += 1
        conditions["rsi"] = True
    else:
        conditions["rsi"] = False

    # Cruce EMA
    if latest["EMA_FAST"] > latest["EMA_SLOW"]:
        score += 1
        conditions["ema_cross"] = True
    else:
        conditions["ema_cross"] = False

    # Fibonacci 55.9%
    fib_559 = calculate_fib_559(df)
    if abs(latest["Close"] - fib_559) / latest["Close"] < 0.01:
        score += 1
        conditions["fib"] = True
    else:
        conditions["fib"] = False

    return {
        "score": score,
        "conditions": conditions
    }

# =============================
# API ENDPOINT
# =============================

@app.get("/api/chart/{ticker}")
def get_chart(ticker: str):

    try:
        profile = get_profile(ticker)

        df = yf.download(ticker, period="6mo", interval="4h")

        if df.empty:
            raise HTTPException(status_code=404, detail="No data found")

        df = calculate_emas(df, profile)
        df["RSI"] = calculate_rsi(df)

        latest_price = df["Close"].iloc[-1]

        levels = calculate_levels(latest_price, profile)
        confluence = calculate_confluence(df, profile)

        return {
            "ticker": ticker,
            "price": float(latest_price),
            "ema_fast": float(df["EMA_FAST"].iloc[-1]),
            "ema_slow": float(df["EMA_SLOW"].iloc[-1]),
            "rsi": float(df["RSI"].iloc[-1]),
            "levels": levels,
            "confluence": confluence
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =============================
# ROOT
# =============================

@app.get("/")
def root():
    return {"status": "MatrixLab API running"}
