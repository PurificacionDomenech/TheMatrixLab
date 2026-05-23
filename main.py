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
    "BTC-USD",
]

_sent_cache: dict = {}
_DEDUP_SECONDS = 4 * 3600

_row_cache: dict = {}
_ROW_TTL = 300
_yf_lock = asyncio.Lock()

_rsi_watchlist: dict = {}
_RSI_WATCH_INTERVAL_MIN = 2

_PATTERN_WATCH_INTERVAL_MIN = 5
_PATTERN_RECENT_BARS = 3  # 2º pico/valle/hombro debe estar en las últimas N velas 4H
_PATTERN_MIN_EXTRA_CONFLUENCIAS = 2
_PATTERN_DEDUP_SECONDS = 12 * 3600  # no reenviar el mismo patrón en 12h

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

# ── Componentes clave de índices para contexto ──────────────
INDEX_COMPONENTS = {
    "^DJI": ["AAPL", "MSFT", "JPM", "V", "UNH", "GS", "HD", "MCD", "CAT", "AXP"],
    "^NDX": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "COST", "NFLX"],
}


async def async_download(ticker, **kwargs):
    loop = asyncio.get_running_loop()
    async with _yf_lock:
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
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    df[f"EMA{es}"] = close.ewm(span=es, adjust=False).mean()
    df[f"EMA{el}"] = close.ewm(span=el, adjust=False).mean()
    d = close.diff()
    losses = (-d.where(d < 0, 0)).rolling(14).mean().replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + d.where(d > 0, 0).rolling(14).mean() / losses))
    return df


def _flat(series):
    """Devuelve siempre una Series 1D (yfinance a veces devuelve DataFrame)."""
    if isinstance(series, pd.DataFrame):
        return series.iloc[:, 0]
    return series


def calc_rsi_divergence(df, lookback=10):
    """Detecta divergencias regulares y ocultas del RSI vs precio.
    Devuelve dict con flags + tipo dominante (bullish/bearish/None)."""
    out = {"bull_div": False, "bear_div": False,
           "hidden_bull": False, "hidden_bear": False, "tipo": None,
           "points": None}
    if len(df) < lookback * 2 + 5 or "RSI" not in df.columns:
        return out

    high = _flat(df["High"])
    low  = _flat(df["Low"])
    rsi  = _flat(df["RSI"])

    lb = min(lookback, 5)
    n  = len(df)
    window_end = n - lb - 1
    if window_end <= lb:
        return out

    def is_pivot_low(s, idx):
        v = s.iloc[idx]
        return all(s.iloc[idx - i] >= v for i in range(1, lb + 1)) and \
               all(s.iloc[idx + i] >= v for i in range(1, lb + 1))

    def is_pivot_high(s, idx):
        v = s.iloc[idx]
        return all(s.iloc[idx - i] <= v for i in range(1, lb + 1)) and \
               all(s.iloc[idx + i] <= v for i in range(1, lb + 1))

    pivot_lows  = [i for i in range(lb, window_end) if is_pivot_low(rsi, i)]
    pivot_highs = [i for i in range(lb, window_end) if is_pivot_high(rsi, i)]

    # Divergencia bajista: precio HH + RSI LH | oculta: precio LH + RSI HH
    if len(pivot_highs) >= 2:
        p1, p2 = pivot_highs[-2], pivot_highs[-1]
        if 3 <= (p2 - p1) <= lookback * 4:
            ph1, ph2 = float(high.iloc[p1]), float(high.iloc[p2])
            rh1, rh2 = float(rsi.iloc[p1]),  float(rsi.iloc[p2])
            kind = None
            if ph2 > ph1 and rh2 < rh1:
                out["bear_div"] = True; out["tipo"] = "bearish"; kind = "bear_reg"
            elif ph2 < ph1 and rh2 > rh1:
                out["hidden_bear"] = True; out["tipo"] = out["tipo"] or "bearish"; kind = "bear_hidden"
            if kind:
                out["points"] = {"kind": kind, "tipo": "bearish",
                                 "p1_idx": int(p1), "p2_idx": int(p2),
                                 "p1_price": ph1, "p2_price": ph2,
                                 "p1_rsi": rh1, "p2_rsi": rh2}

    # Divergencia alcista: precio LL + RSI HL | oculta: precio HL + RSI LL
    if len(pivot_lows) >= 2:
        p1, p2 = pivot_lows[-2], pivot_lows[-1]
        if 3 <= (p2 - p1) <= lookback * 4:
            pl1, pl2 = float(low.iloc[p1]), float(low.iloc[p2])
            rl1, rl2 = float(rsi.iloc[p1]), float(rsi.iloc[p2])
            kind = None
            if pl2 < pl1 and rl2 > rl1:
                out["bull_div"] = True; out["tipo"] = "bullish"; kind = "bull_reg"
            elif pl2 > pl1 and rl2 < rl1:
                out["hidden_bull"] = True; out["tipo"] = out["tipo"] or "bullish"; kind = "bull_hidden"
            if kind and out["points"] is None:
                out["points"] = {"kind": kind, "tipo": "bullish",
                                 "p1_idx": int(p1), "p2_idx": int(p2),
                                 "p1_price": pl1, "p2_price": pl2,
                                 "p1_rsi": rl1, "p2_rsi": rl2}

    return out


def calc_shark_fin(df, lookback=30):
    """
    Detecta aleta de tiburón en RSI — señal de agotamiento extremo.
    Requiere divergencia previa confirmada.

    Casos:
      shark_bear: div bajista previa → RSI entra >70 y forma pico
      shark_bull: div alcista previa → RSI entra <30 y forma valle

    Fases:
      forming   → RSI en zona extrema, pico/valle aún no cerrado (pre-alerta)
      crossed   → RSI cruzó de vuelta la zona (confirmado, +2 pts)
      exceeded  → pico/valle supera el nivel R1/S1 original (extremo, +4 pts, alerta inmediata)
    """
    result = {
        "shark_bear": False, "shark_bull": False,
        "shark_exceeds_div": False, "shark_pts": 0,
        "shark_tipo": None, "shark_rsi_peak": None,
        "shark_div_r1": None, "phase": None,
        "alert_immediate": False,
    }
    if len(df) < 10 or "RSI" not in df.columns:
        return result

    rsi = _flat(df["RSI"]).dropna()
    if len(rsi) < 10:
        return result

    div = calc_rsi_divergence(df, lookback=lookback)
    pts = div.get("points")

    # ── ALETA BAJISTA ──────────────────────────────────────
    if div["bear_div"] and pts and pts["tipo"] == "bearish":
        r1_rsi = pts["p1_rsi"]   # pivote antiguo (más alto)
        n = len(rsi)
        recent = rsi.iloc[-min(lookback, n):]
        shark_peaks = [(i, float(recent.iloc[i]))
                       for i in range(1, len(recent) - 1)
                       if float(recent.iloc[i]) > 70
                       and float(recent.iloc[i]) >= float(recent.iloc[i - 1])
                       and float(recent.iloc[i]) >= float(recent.iloc[i + 1])]
        if shark_peaks:
            peak_i, peak_rsi = shark_peaks[-1]
            rsi_now = float(rsi.iloc[-1])
            result.update({"shark_bear": True, "shark_tipo": "bearish",
                           "shark_rsi_peak": peak_rsi, "shark_div_r1": r1_rsi})
            exceeds = peak_rsi > r1_rsi
            result["shark_exceeds_div"] = exceeds
            if exceeds:
                result.update({"phase": "exceeded", "alert_immediate": True, "shark_pts": 4})
            elif rsi_now < 70 and peak_i < len(recent) - 1:
                result.update({"phase": "crossed", "alert_immediate": True, "shark_pts": 2})
            else:
                result.update({"phase": "forming", "alert_immediate": False, "shark_pts": 1})

    # ── ALETA ALCISTA ──────────────────────────────────────
    elif div["bull_div"] and pts and pts["tipo"] == "bullish":
        s1_rsi = pts["p1_rsi"]   # pivote antiguo (más bajo)
        n = len(rsi)
        recent = rsi.iloc[-min(lookback, n):]
        shark_valleys = [(i, float(recent.iloc[i]))
                         for i in range(1, len(recent) - 1)
                         if float(recent.iloc[i]) < 30
                         and float(recent.iloc[i]) <= float(recent.iloc[i - 1])
                         and float(recent.iloc[i]) <= float(recent.iloc[i + 1])]
        if shark_valleys:
            valley_i, valley_rsi = shark_valleys[-1]
            rsi_now = float(rsi.iloc[-1])
            result.update({"shark_bull": True, "shark_tipo": "bullish",
                           "shark_rsi_peak": valley_rsi, "shark_div_r1": s1_rsi})
            exceeds = valley_rsi < s1_rsi
            result["shark_exceeds_div"] = exceeds
            if exceeds:
                result.update({"phase": "exceeded", "alert_immediate": True, "shark_pts": 4})
            elif rsi_now > 30 and valley_i < len(recent) - 1:
                result.update({"phase": "crossed", "alert_immediate": True, "shark_pts": 2})
            else:
                result.update({"phase": "forming", "alert_immediate": False, "shark_pts": 1})

    return result


def calc_pattern_mw(df, lookback=30):
    """Detecta doble techo (M) y doble suelo (W). Solo confirmado con
    divergencia RSI cuenta como señal fuerte."""
    out = {"M": False, "W": False, "M_with_div": False, "W_with_div": False,
           "points": None}
    if len(df) < lookback or "RSI" not in df.columns:
        return out

    w = df.iloc[-lookback:]
    base_idx = len(df) - lookback  # offset to map back to absolute df index
    high  = _flat(w["High"]).reset_index(drop=True)
    low   = _flat(w["Low"]).reset_index(drop=True)
    rsi_s = _flat(w["RSI"]).reset_index(drop=True)

    tol = 0.015  # 1.5% entre los dos picos/valles
    highs_idx, lows_idx = [], []
    for i in range(2, len(w) - 2):
        h = high.iloc[i]
        if h >= high.iloc[i - 1] and h >= high.iloc[i - 2] and \
           h >= high.iloc[i + 1] and h >= high.iloc[i + 2]:
            highs_idx.append(i)
        l = low.iloc[i]
        if l <= low.iloc[i - 1] and l <= low.iloc[i - 2] and \
           l <= low.iloc[i + 1] and l <= low.iloc[i + 2]:
            lows_idx.append(i)

    # Doble techo
    if len(highs_idx) >= 2:
        for h1_i in highs_idx[:-1]:
            h2_i = highs_idx[-1]
            if h2_i - h1_i < 5:
                continue
            h1, h2 = float(high.iloc[h1_i]), float(high.iloc[h2_i])
            if h1 > 0 and abs(h1 - h2) / h1 <= tol:
                out["M"] = True
                r1, r2 = float(rsi_s.iloc[h1_i]), float(rsi_s.iloc[h2_i])
                with_div = r2 < r1 - 2
                if with_div:
                    out["M_with_div"] = True
                neckline = float(low.iloc[h1_i:h2_i + 1].min())
                last_c = float(_flat(w["Close"]).reset_index(drop=True).iloc[-1])
                estado_m = ("confirmado" if last_c < neckline
                            else "formando_p2" if abs(last_c - h2) / h2 <= tol * 1.8
                            else "formando")
                out["points"] = {"tipo": "bearish", "shape": "M",
                                 "p1_idx": int(base_idx + h1_i),
                                 "p2_idx": int(base_idx + h2_i),
                                 "p1_y": h1, "p2_y": h2,
                                 "neckline": neckline, "with_div": with_div,
                                 "estado": estado_m}
                break

    # Doble suelo
    if len(lows_idx) >= 2:
        for l1_i in lows_idx[:-1]:
            l2_i = lows_idx[-1]
            if l2_i - l1_i < 5:
                continue
            l1, l2 = float(low.iloc[l1_i]), float(low.iloc[l2_i])
            if l1 > 0 and abs(l1 - l2) / l1 <= tol:
                out["W"] = True
                r1, r2 = float(rsi_s.iloc[l1_i]), float(rsi_s.iloc[l2_i])
                with_div = r2 > r1 + 2
                if with_div:
                    out["W_with_div"] = True
                neckline = float(high.iloc[l1_i:l2_i + 1].max())
                if out["points"] is None:
                    last_c = float(_flat(w["Close"]).reset_index(drop=True).iloc[-1])
                    estado_w = ("confirmado" if last_c > neckline
                                else "formando_v2" if abs(last_c - l2) / l2 <= tol * 1.8
                                else "formando")
                    out["points"] = {"tipo": "bullish", "shape": "W",
                                     "p1_idx": int(base_idx + l1_i),
                                     "p2_idx": int(base_idx + l2_i),
                                     "p1_y": l1, "p2_y": l2,
                                     "neckline": neckline, "with_div": with_div,
                                     "estado": estado_w}
                break

    return out


def calc_pattern_hch(df, lookback=60):
    """Detecta Hombro-Cabeza-Hombro (HCH bajista) y HCH invertido (alcista).
    Confirmación: ruptura del neckline en la última vela.
    - HCH:  3 picos donde el central (cabeza) > hombros, hombros similares.
            Neckline = min de los valles entre picos. Confirma si Close < neckline.
    - HCHi: 3 valles donde el central (cabeza) < hombros, hombros similares.
            Neckline = max de los picos entre valles. Confirma si Close > neckline.
    """
    out = {"HCH": False, "HCHi": False, "HCH_confirmed": False, "HCHi_confirmed": False,
           "points": None}
    if len(df) < lookback:
        return out

    w = df.iloc[-lookback:]
    base_idx = len(df) - lookback
    high  = _flat(w["High"]).reset_index(drop=True)
    low   = _flat(w["Low"]).reset_index(drop=True)
    close = _flat(w["Close"]).reset_index(drop=True)

    radius = 3
    n = len(w)
    highs_idx, lows_idx = [], []
    for i in range(radius, n - radius):
        h = high.iloc[i]
        if all(h >= high.iloc[i - k] for k in range(1, radius + 1)) and \
           all(h >= high.iloc[i + k] for k in range(1, radius + 1)):
            highs_idx.append(i)
        l = low.iloc[i]
        if all(l <= low.iloc[i - k] for k in range(1, radius + 1)) and \
           all(l <= low.iloc[i + k] for k in range(1, radius + 1)):
            lows_idx.append(i)

    tol_shoulders = 0.025  # hombros pueden diferir hasta 2.5%
    last_close = float(close.iloc[-1])

    # ── HCH bajista (3 picos: hombro–cabeza–hombro) ──
    if len(highs_idx) >= 3:
        for a, b, c in reversed([(highs_idx[i], highs_idx[i+1], highs_idx[i+2])
                                 for i in range(len(highs_idx) - 2)]):
            ha, hb, hc = float(high.iloc[a]), float(high.iloc[b]), float(high.iloc[c])
            if hb > ha and hb > hc and ha > 0 and \
               abs(ha - hc) / ha <= tol_shoulders and \
               (hb - max(ha, hc)) / max(ha, hc) >= 0.005:
                # neckline = mínimo del rango entre los dos hombros
                neckline = float(low.iloc[a:c + 1].min())
                out["HCH"] = True
                confirmed = last_close < neckline
                if confirmed:
                    out["HCH_confirmed"] = True
                estado_hch = ("confirmado" if confirmed
                              else "formando_hd" if abs(last_close - hc) / hc <= tol_shoulders
                              else "formando")
                out["points"] = {"tipo": "bearish", "shape": "HCH",
                                 "ls_idx": int(base_idx + a), "ls_y": ha,
                                 "head_idx": int(base_idx + b), "head_y": hb,
                                 "rs_idx": int(base_idx + c), "rs_y": hc,
                                 "neckline": neckline, "confirmed": confirmed,
                                 "estado": estado_hch}
                break

    # ── HCH invertido alcista (3 valles) ──
    if len(lows_idx) >= 3:
        for a, b, c in reversed([(lows_idx[i], lows_idx[i+1], lows_idx[i+2])
                                 for i in range(len(lows_idx) - 2)]):
            la, lb, lc = float(low.iloc[a]), float(low.iloc[b]), float(low.iloc[c])
            if lb < la and lb < lc and la > 0 and \
               abs(la - lc) / la <= tol_shoulders and \
               (min(la, lc) - lb) / min(la, lc) >= 0.005:
                neckline = float(high.iloc[a:c + 1].max())
                out["HCHi"] = True
                confirmed = last_close > neckline
                if confirmed:
                    out["HCHi_confirmed"] = True
                if out["points"] is None:
                    estado_hchi = ("confirmado" if confirmed
                                   else "formando_hd" if abs(last_close - lc) / lc <= tol_shoulders
                                   else "formando")
                    out["points"] = {"tipo": "bullish", "shape": "HCHi",
                                     "ls_idx": int(base_idx + a), "ls_y": la,
                                     "head_idx": int(base_idx + b), "head_y": lb,
                                     "rs_idx": int(base_idx + c), "rs_y": lc,
                                     "neckline": neckline, "confirmed": confirmed,
                                     "estado": estado_hchi}
                break

    return out


def calc_candle_patterns(df):
    """Detecta patrones de vela japonesa en la última vela cerrada.
    Solo se usan como CONTEXTO en el mensaje, NO suman puntos por sí solos."""
    if len(df) < 2:
        return []
    o  = float(_flat(df["Open"]).iloc[-1])
    h  = float(_flat(df["High"]).iloc[-1])
    l  = float(_flat(df["Low"]).iloc[-1])
    c  = float(_flat(df["Close"]).iloc[-1])
    o2 = float(_flat(df["Open"]).iloc[-2])
    c2 = float(_flat(df["Close"]).iloc[-2])

    body    = abs(c - o)
    rng     = max(h - l, 1e-9)
    upper_w = h - max(c, o)
    lower_w = min(c, o) - l
    body_pct = body / rng

    found = []
    # Engulfing
    if c2 < o2 and c > o and c > o2 and o < c2:
        found.append({"tipo": "bullish", "desc": "Engulfing alcista"})
    if c2 > o2 and c < o and c < o2 and o > c2:
        found.append({"tipo": "bearish", "desc": "Engulfing bajista"})
    # Pin bar / Hammer / Shooting star (mecha dominante)
    if lower_w >= body * 2 and upper_w <= body * 0.5 and body_pct < 0.4:
        found.append({"tipo": "bullish", "desc": "Hammer/Pin bar alcista"})
    if upper_w >= body * 2 and lower_w <= body * 0.5 and body_pct < 0.4:
        found.append({"tipo": "bearish", "desc": "Shooting star/Pin bar bajista"})
    # Marubozu (cuerpo casi pleno)
    if c > o and upper_w <= body * 0.05 and lower_w <= body * 0.05 and body_pct > 0.85:
        found.append({"tipo": "bullish", "desc": "Marubozu alcista"})
    if c < o and upper_w <= body * 0.05 and lower_w <= body * 0.05 and body_pct > 0.85:
        found.append({"tipo": "bearish", "desc": "Marubozu bajista"})
    # Doji (indecisión)
    if body_pct < 0.1:
        found.append({"tipo": "neutral", "desc": "Doji (indecisión)"})

    return found


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
    """Calcula aperturas de año, semana y día."""
    result = {"year_open": None, "week_open": None, "day_open": None}
    if df.empty:
        return result
    now = df.index[-1]

    # Apertura anual
    ys = pd.Timestamp(year=now.year, month=1, day=1, tz=now.tz if now.tz else None)
    ydf = df[df.index >= ys]
    if not ydf.empty:
        result["year_open"] = float(ydf["Open"].iloc[0])

    # Apertura semanal
    ws = (now - pd.Timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
    wdf = df[df.index >= ws]
    if not wdf.empty:
        result["week_open"] = float(wdf["Open"].iloc[0])

    # Apertura del día (primera vela del día actual)
    ds = pd.Timestamp(year=now.year, month=now.month, day=now.day,
                      tz=now.tz if now.tz else None)
    ddf = df[df.index >= ds]
    if not ddf.empty:
        result["day_open"] = float(ddf["Open"].iloc[0])

    return result


async def get_index_components_context(ticker: str) -> dict | None:
    """
    Para ^DJI y ^NDX: obtiene el % de componentes clave alcistas vs bajistas
    respecto al precio actual vs apertura del día.
    Retorna dict con bulls, bears, neutral, porcentajes y dirección dominante.
    """
    components = INDEX_COMPONENTS.get(ticker.upper())
    if not components:
        return None

    bulls, bears, neutral = [], [], []

    async def check_component(sym):
        try:
            df = await async_download(sym, period="2d", interval="1d", progress=False)
            if df.empty:
                return
            df = clean_df(df)
            if len(df) < 1:
                return
            last_close = float(df["Close"].iloc[-1])
            last_open  = float(df["Open"].iloc[-1])
            if last_close > last_open * 1.001:
                bulls.append(sym)
            elif last_close < last_open * 0.999:
                bears.append(sym)
            else:
                neutral.append(sym)
        except Exception:
            pass

    for s in components:
        await check_component(s)

    total = len(bulls) + len(bears) + len(neutral)
    if total == 0:
        return None

    bull_pct = round(len(bulls) / total * 100)
    bear_pct = round(len(bears) / total * 100)

    if bull_pct >= 60:
        direction = "bullish"
    elif bear_pct >= 60:
        direction = "bearish"
    else:
        direction = "mixed"

    return {
        "bulls":     bulls,
        "bears":     bears,
        "neutral":   neutral,
        "bull_pct":  bull_pct,
        "bear_pct":  bear_pct,
        "direction": direction,
        "total":     total,
    }


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


def evaluate_confluencias(df, ticker="", cfg=None, opens=None, components_ctx=None):
    """
    Evalúa las 5 confluencias de la matriz con validación DIRECCIONAL.

    Regla fundamental: para que el setup sea FAVORABLE, todas las confluencias
    activas deben apuntar en la MISMA dirección (todas bullish o todas bearish).
    Si hay conflicto de dirección → el setup es inválido (CONTRADICCIÓN).

    Direcciones de cada confluencia:
      ① RSI < 47  → bullish (comprar barato, ideal < 30)
         RSI > 53 → bearish (vender caro, ideal > 70)
      ② EMA corta > EMA larga → bullish (tendencia alcista)
         EMA corta < EMA larga → bearish (tendencia bajista)
      ③ Fractal soporte       → bullish
         Fractal resistencia   → bearish
      ④ Apertura día/semana   → bullish si precio arriba de ambas, bearish si abajo
      ⑤ Fibonacci 55.9%       → neutral (nivel de retroceso, válido para ambas)
      ⑥ Componentes índice    → bullish/bearish según mayoría (solo ^DJI/^NDX)
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

    raw = []

    # ① RSI — comprar barato (<47) o vender caro (>53)
    if rsi < 47:
        raw.append({"id": 1, "ok": True,
            "texto": f"RSI bajo ({rsi:.1f}) → favorable para largos", "tipo": "bullish"})
    elif rsi > 53:
        raw.append({"id": 1, "ok": True,
            "texto": f"RSI alto ({rsi:.1f}) → favorable para cortos", "tipo": "bearish"})
    else:
        raw.append({"id": 1, "ok": False,
            "texto": f"RSI neutro ({rsi:.1f})", "tipo": "info"})

    # ② Relación entre EMAs (tendencia)
    if ema_s_val and ema_l_val:
        if ema_s_val > ema_l_val:
            raw.append({"id": 2, "ok": True,
                "texto": f"EMA{es} ({ema_s_val:.5g}) ↑ EMA{el} ({ema_l_val:.5g}) — tendencia alcista",
                "tipo": "bullish"})
        else:
            raw.append({"id": 2, "ok": True,
                "texto": f"EMA{es} ({ema_s_val:.5g}) ↓ EMA{el} ({ema_l_val:.5g}) — tendencia bajista",
                "tipo": "bearish"})
    else:
        raw.append({"id": 2, "ok": False,
            "texto": "EMAs no disponibles", "tipo": "info"})

    # ③ Fractal (soporte → bullish, resistencia → bearish)
    if cfg:
        fr = calc_fractales(price, cfg)
        ft = detect_fractal_touch(
            float(df["High"].iloc[n]), float(df["Low"].iloc[n]), price, fr)
        if ft["touch"]:
            tag = "MAYOR" if ft["is_major"] else "menor"
            if ft["tipo"] == "soporte":
                raw.append({"id": 3, "ok": True,
                    "texto": f"Nivel clave {tag} como soporte en {ft['price']:.5g}",
                    "tipo": "bullish"})
            else:
                raw.append({"id": 3, "ok": True,
                    "texto": f"Nivel clave {tag} como resistencia en {ft['price']:.5g}",
                    "tipo": "bearish"})
        else:
            raw.append({"id": 3, "ok": False,
                "texto": "Sin nivel clave fractal relevante", "tipo": "info"})
    else:
        raw.append({"id": 3, "ok": False,
            "texto": "Sin nivel clave fractal relevante", "tipo": "info"})

    # ④ Precio sobre/bajo apertura del DÍA y SEMANA → dirección real
    if opens:
        do = opens.get("day_open")
        wo = opens.get("week_open")
        tol = 0.0005
        day_dir  = None
        week_dir = None
        if do and do > 0:
            if price > do * (1 + tol):   day_dir = "above"
            elif price < do * (1 - tol): day_dir = "below"
        if wo and wo > 0:
            if price > wo * (1 + tol):   week_dir = "above"
            elif price < wo * (1 - tol): week_dir = "below"

        if day_dir == "above" and week_dir == "above":
            raw.append({"id": 4, "ok": True,
                "texto": (f"Precio sobre apertura del día ({do:.5g}) "
                          f"y semana ({wo:.5g}) → sesgo alcista"),
                "tipo": "bullish"})
        elif day_dir == "below" and week_dir == "below":
            raw.append({"id": 4, "ok": True,
                "texto": (f"Precio bajo apertura del día ({do:.5g}) "
                          f"y semana ({wo:.5g}) → sesgo bajista"),
                "tipo": "bearish"})
        elif day_dir and week_dir:
            raw.append({"id": 4, "ok": False,
                "texto": (f"Apertura día {'↑' if day_dir=='above' else '↓'} "
                          f"vs semana {'↑' if week_dir=='above' else '↓'} — sin consenso"),
                "tipo": "info"})
        else:
            raw.append({"id": 4, "ok": False,
                "texto": "Datos de apertura del día/semana incompletos", "tipo": "info"})
    else:
        raw.append({"id": 4, "ok": False,
            "texto": "Datos de apertura no disponibles", "tipo": "info"})

    # ⑤ Fibonacci 55.9% (neutral — nivel de precio, no implica dirección)
    high_p = float(df["High"].max())
    low_p  = float(df["Low"].min())
    fib559 = high_p - (high_p - low_p) * 0.559
    tol_f  = (high_p - low_p) * 0.015
    if abs(price - fib559) <= tol_f:
        raw.append({"id": 5, "ok": True,
            "texto": f"Fibonacci 55.9% en {fib559:.5g} (rango {low_p:.5g}–{high_p:.5g})",
            "tipo": "neutral"})
    else:
        pct_dist = (price - fib559) / fib559 * 100
        raw.append({"id": 5, "ok": False,
            "texto": f"Fib 55.9% en {fib559:.5g} ({pct_dist:+.1f}% de distancia)",
            "tipo": "info"})

    # ⑥ Componentes del índice (solo ^DJI y ^NDX) — dirección real
    if components_ctx and components_ctx.get("total", 0) > 0:
        bull_pct  = components_ctx.get("bull_pct", 0)
        bear_pct  = components_ctx.get("bear_pct", 0)
        comp_dir  = components_ctx.get("direction", "mixed")
        n_bulls   = len(components_ctx.get("bulls", []))
        n_bears   = len(components_ctx.get("bears", []))
        total_c   = components_ctx.get("total", 1)
        if comp_dir == "bullish":
            raw.append({"id": 6, "ok": True,
                "texto": (f"{bull_pct}% de componentes alcistas ({n_bulls}/{total_c}) "
                          f"→ sesgo alcista del índice"),
                "tipo": "bullish"})
        elif comp_dir == "bearish":
            raw.append({"id": 6, "ok": True,
                "texto": (f"{bear_pct}% de componentes bajistas ({n_bears}/{total_c}) "
                          f"→ sesgo bajista del índice"),
                "tipo": "bearish"})
        else:
            raw.append({"id": 6, "ok": False,
                "texto": f"Componentes mixtos ({bull_pct}% ↑ / {bear_pct}% ↓)",
                "tipo": "info"})

    # ⑦ Divergencia RSI + Aleta de Tiburón (señal fuerte de reversión)
    div = calc_rsi_divergence(df, lookback=10)
    shark = calc_shark_fin(df, lookback=30)

    # Texto base de la divergencia
    if div["bull_div"]:
        div7_texto = "Divergencia RSI alcista regular — posible reversión al alza"
        div7_tipo  = "bullish"
        div7_ok    = True
    elif div["hidden_bull"]:
        div7_texto = "Divergencia RSI alcista oculta — continuación tendencia alcista"
        div7_tipo  = "bullish"
        div7_ok    = True
    elif div["bear_div"]:
        div7_texto = "Divergencia RSI bajista regular — posible reversión a la baja"
        div7_tipo  = "bearish"
        div7_ok    = True
    elif div["hidden_bear"]:
        div7_texto = "Divergencia RSI bajista oculta — continuación tendencia bajista"
        div7_tipo  = "bearish"
        div7_ok    = True
    else:
        div7_texto = "Sin divergencias RSI relevantes"
        div7_tipo  = "info"
        div7_ok    = False

    # Enriquecer con aleta de tiburón si corresponde
    pts_extra_7 = 0
    shark_info  = None
    if shark["shark_bear"] and div7_tipo in ("bearish", "info"):
        if shark["phase"] == "exceeded":
            div7_texto = (f"⚡🦈 Aleta tiburón EXTREMA — RSI pico {shark['shark_rsi_peak']:.1f} "
                          f"superó div R1 {shark['shark_div_r1']:.1f} → agotamiento máximo")
            div7_tipo = "bearish"; div7_ok = True; pts_extra_7 = 3  # +4 total
            shark_info = shark
        elif shark["phase"] == "crossed":
            div7_texto = (f"🦈 Aleta tiburón bajista confirmada — RSI pico {shark['shark_rsi_peak']:.1f} "
                          f"cruzó <70 (div R1={shark['shark_div_r1']:.1f})")
            div7_tipo = "bearish"; div7_ok = True; pts_extra_7 = 1  # +2 total
            shark_info = shark
        elif shark["phase"] == "forming":
            if div7_ok:
                div7_texto += f" + 🦈 aleta formándose (RSI {shark['shark_rsi_peak']:.1f} en zona)"
            else:
                div7_texto = f"🦈 Aleta tiburón formándose — RSI {shark['shark_rsi_peak']:.1f} en zona >70"
            shark_info = shark
    elif shark["shark_bull"] and div7_tipo in ("bullish", "info"):
        if shark["phase"] == "exceeded":
            div7_texto = (f"⚡🦈 Aleta tiburón EXTREMA — RSI valle {shark['shark_rsi_peak']:.1f} "
                          f"superó div S1 {shark['shark_div_r1']:.1f} → agotamiento máximo")
            div7_tipo = "bullish"; div7_ok = True; pts_extra_7 = 3
            shark_info = shark
        elif shark["phase"] == "crossed":
            div7_texto = (f"🦈 Aleta tiburón alcista confirmada — RSI valle {shark['shark_rsi_peak']:.1f} "
                          f"cruzó >30 (div S1={shark['shark_div_r1']:.1f})")
            div7_tipo = "bullish"; div7_ok = True; pts_extra_7 = 1
            shark_info = shark
        elif shark["phase"] == "forming":
            if div7_ok:
                div7_texto += f" + 🦈 aleta formándose (RSI {shark['shark_rsi_peak']:.1f} en zona)"
            else:
                div7_texto = f"🦈 Aleta tiburón formándose — RSI {shark['shark_rsi_peak']:.1f} en zona <30"
            shark_info = shark

    raw.append({"id": 7, "ok": div7_ok, "texto": div7_texto, "tipo": div7_tipo,
                "pts_extra": pts_extra_7, "shark": shark_info,
                "alert_immediate": shark["alert_immediate"] if shark_info else False})

    # ⑧ Patrón gráfico de reversión: M/W con divergencia o HCH/HCHi confirmado
    mw  = calc_pattern_mw(df, lookback=30)
    hch = calc_pattern_hch(df, lookback=60)

    if hch["HCHi_confirmed"]:
        raw.append({"id": 8, "ok": True,
            "texto": "HCH invertido confirmado (ruptura del neckline al alza)",
            "tipo": "bullish"})
    elif hch["HCH_confirmed"]:
        raw.append({"id": 8, "ok": True,
            "texto": "HCH confirmado (ruptura del neckline a la baja)",
            "tipo": "bearish"})
    elif mw["W_with_div"]:
        raw.append({"id": 8, "ok": True,
            "texto": "Patrón W (doble suelo) confirmado por divergencia RSI",
            "tipo": "bullish"})
    elif mw["M_with_div"]:
        raw.append({"id": 8, "ok": True,
            "texto": "Patrón M (doble techo) confirmado por divergencia RSI",
            "tipo": "bearish"})
    elif hch["HCHi"]:
        raw.append({"id": 8, "ok": False,
            "texto": "HCH invertido detectado (pendiente de romper neckline)",
            "tipo": "info"})
    elif hch["HCH"]:
        raw.append({"id": 8, "ok": False,
            "texto": "HCH detectado (pendiente de romper neckline)",
            "tipo": "info"})
    elif mw["W"]:
        raw.append({"id": 8, "ok": False,
            "texto": "Patrón W detectado (sin divergencia RSI confirmada)",
            "tipo": "info"})
    elif mw["M"]:
        raw.append({"id": 8, "ok": False,
            "texto": "Patrón M detectado (sin divergencia RSI confirmada)",
            "tipo": "info"})
    else:
        raw.append({"id": 8, "ok": False,
            "texto": "Sin patrón gráfico de reversión", "tipo": "info"})

    # Velas japonesas → contexto extra (NO suma puntos)
    candle_patterns = calc_candle_patterns(df)

    # ── PASO 2: determinar la dirección dominante con lógica direccional ──
    activas_bullish = [c for c in raw if c["ok"] and c["tipo"] == "bullish"]
    activas_bearish = [c for c in raw if c["ok"] and c["tipo"] == "bearish"]

    FUERTES = {1, 2}
    bullish_fuertes = [c for c in activas_bullish if c["id"] in FUERTES]
    bearish_fuertes = [c for c in activas_bearish if c["id"] in FUERTES]

    contradiccion = bool(bullish_fuertes) and bool(bearish_fuertes)

    if contradiccion:
        direction = "conflicto"
        puntos    = 0
        confluencias_final = []
        for c in raw:
            entry = dict(c)
            if c["ok"] and c["tipo"] in ("bullish", "bearish") and c["id"] in FUERTES:
                entry["conflicto"] = True
                entry["ok"] = False
            confluencias_final.append(entry)
    else:
        if bullish_fuertes and not bearish_fuertes:
            direction = "bullish"
        elif bearish_fuertes and not bullish_fuertes:
            direction = "bearish"
        elif len(activas_bullish) > len(activas_bearish):
            direction = "bullish"
        elif len(activas_bearish) > len(activas_bullish):
            direction = "bearish"
        else:
            direction = "info"

        confluencias_final = []
        puntos = 0
        for c in raw:
            entry = dict(c)
            if c["ok"] and c["tipo"] not in ("neutral", "info"):
                if direction in ("bullish", "bearish") and c["tipo"] != direction:
                    entry["ok"] = False
                    entry["descartada"] = True
                else:
                    puntos += 1
                    # pts_extra: aleta tiburón suma puntos adicionales
                    puntos += c.get("pts_extra", 0)
            elif c["ok"] and c["tipo"] == "neutral":
                puntos += 1
            confluencias_final.append(entry)

    # ── PASO 3: calcular contexto del día/semana ──
    day_context  = None
    week_context = None
    if opens:
        do = opens.get("day_open")
        wo = opens.get("week_open")
        if do and do > 0:
            if price > do * 1.0005:
                day_context = {"direction": "above", "open": do,
                               "pct": round((price - do) / do * 100, 3)}
            elif price < do * 0.9995:
                day_context = {"direction": "below", "open": do,
                               "pct": round((price - do) / do * 100, 3)}
            else:
                day_context = {"direction": "at", "open": do, "pct": 0.0}
        if wo and wo > 0:
            if price > wo * 1.0005:
                week_context = {"direction": "above", "open": wo,
                                "pct": round((price - wo) / wo * 100, 3)}
            elif price < wo * 0.9995:
                week_context = {"direction": "below", "open": wo,
                                "pct": round((price - wo) / wo * 100, 3)}
            else:
                week_context = {"direction": "at", "open": wo, "pct": 0.0}

    # ── PASO 4: determinar estado final ──
    if contradiccion:
        estado = "CONTRADICCIÓN"
        nivel  = "info"
        alert  = False
    elif puntos >= 4:
        estado = "FAVORABLE"
        nivel  = direction
        alert  = True
    elif puntos == 3:
        estado = "INTERESANTE"
        nivel  = direction
        alert  = False
    elif puntos == 2:
        estado = "CONSIDERAR"
        nivel  = "info"
        alert  = False
    else:
        estado = "NO AHORA"
        nivel  = "info"
        alert  = False

    max_confs = max(c["id"] for c in confluencias_final) if confluencias_final else 5

    return {
        "ticker":        ticker.upper(),
        "precio":        price,
        "rsi":           rsi,
        "puntos":        puntos,
        "max_confs":     max_confs,
        "estado":        estado,
        "nivel":         nivel,
        "direction":     direction,
        "contradiccion": contradiccion,
        "confluencias":  confluencias_final,
        "alert":         alert,
        "day_context":   day_context,
        "week_context":  week_context,
        "candle_patterns": candle_patterns,
    }


# ─── SCHEDULER ───────────────────────────────────────────────


async def _check_tickers(tickers: list, num_candles: int = 1, label: str = "",
                         max_per_ticker: int = 0) -> dict:
    """
    Revisa los tickers dados. num_candles controla cuántas velas recientes analizar.
    max_per_ticker: si > 0, limita las alertas enviadas por activo (0 = sin límite).
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

            # Obtener contexto de componentes para índices (una vez por ticker)
            components_ctx = None
            if t.upper() in INDEX_COMPONENTS:
                try:
                    components_ctx = await get_index_components_context(t.upper())
                except Exception:
                    pass

            nuevas = []
            # Analizar las últimas num_candles velas
            for i in range(min(num_candles, len(df))):
                fila = len(df) - 1 - i
                df_slice = df.iloc[: fila + 1]
                ts = df.index[fila]
                try:
                    ts_parsed   = pd.Timestamp(ts)
                    ts_utc      = ts_parsed.tz_localize("UTC") if ts_parsed.tzinfo is None else ts_parsed.tz_convert("UTC")
                    ts_utc_iso  = ts_utc.isoformat()
                    hora        = ts_utc.strftime("%d/%m %H:%M")
                    dia_num     = ts_parsed.weekday()
                    dia_name    = ts_parsed.strftime("%A")
                except Exception:
                    hora       = ""
                    ts_utc_iso = ""
                    dia_num    = -1
                    dia_name   = ""

                resultado = evaluate_confluencias(
                    df_slice,
                    ticker=t.upper(),
                    cfg=cfg,
                    opens=opens_data,
                    components_ctx=components_ctx,
                )

                if resultado and resultado.get("alert"):
                    # Clave de deduplicación: ticker + estado + dirección + precio redondeado
                    direction = resultado.get("direction", "info")
                    key = f"{t}_{resultado['estado']}_{direction}_{round(resultado['precio'], -1)}"
                    if now - _sent_cache.get(key, 0) > _DEDUP_SECONDS:
                        nuevas.append({
                            "nivel":          resultado["nivel"],
                            "msg":            f"[{t.upper()}] {resultado['estado']} {hora}".strip(),
                            "hora":           hora,
                            "ts_utc_iso":     ts_utc_iso,
                            "dia_num":        dia_num,
                            "dia_name":       dia_name,
                            "resultado":      resultado,
                            "components_ctx": components_ctx,
                        })
                        _sent_cache[key] = now
            if max_per_ticker > 0:
                nuevas = nuevas[:max_per_ticker]
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

    await _update_rsi_watchlist()


async def daily_catchup():
    """Catch-up al arrancar: revisa las últimas 6 velas (≈24h) y envía lo pendiente."""
    if not HAS_NOTIFIER:
        return
    print("[catchup] Revisando últimas 24h de alertas…")
    alerts_by_ticker = await _check_tickers(
        WATCH_TICKERS, num_candles=6, label="catchup", max_per_ticker=1
    )
    if alerts_by_ticker:
        total = sum(len(v) for v in alerts_by_ticker.values())
        print(f"[catchup] {total} alertas del día enviadas")
        await notify_users_with_alerts(alerts_by_ticker)
    else:
        print("[catchup] Sin alertas nuevas en las últimas 24h")

    await _update_rsi_watchlist()


async def _update_rsi_watchlist():
    """Evalúa todos los tickers y añade a la watchlist RSI aquellos con ≥3 puntos
    (sin contar RSI) cuyo RSI aún no está en zona extrema."""
    global _rsi_watchlist
    new_watchlist = {}
    for t in WATCH_TICKERS:
        try:
            cfg = get_cfg(t)
            df = await async_download(t.upper(), period="6mo", interval="4h", progress=False)
            if df.empty:
                continue
            df = clean_df(df)
            df = calc_indicators(df, cfg["ema_short"], cfg["ema_long"])
            opens_data = calc_opens(df)

            components_ctx = None
            if t.upper() in INDEX_COMPONENTS:
                try:
                    components_ctx = await get_index_components_context(t.upper())
                except Exception:
                    pass

            resultado = evaluate_confluencias(df, ticker=t.upper(), cfg=cfg,
                                              opens=opens_data, components_ctx=components_ctx)
            if not resultado or resultado.get("contradiccion"):
                continue

            confs = resultado.get("confluencias", [])
            direction = resultado.get("direction", "info")
            rsi = resultado.get("rsi", 50)

            if direction not in ("bullish", "bearish"):
                continue

            puntos_sin_rsi = 0
            for c in confs:
                if c["id"] == 1:
                    continue
                if c.get("ok") and not c.get("descartada") and not c.get("conflicto"):
                    puntos_sin_rsi += 1

            rsi_ya_extremo = (direction == "bullish" and rsi <= 30) or \
                             (direction == "bearish" and rsi >= 70)

            if puntos_sin_rsi >= 3 and not rsi_ya_extremo:
                new_watchlist[t.upper()] = {
                    "direction": direction,
                    "puntos_sin_rsi": puntos_sin_rsi,
                    "rsi_actual": rsi,
                    "resultado": resultado,
                    "components_ctx": components_ctx,
                    "cfg": cfg,
                }
                print(f"[rsi-watch] 👁 {t.upper()} en vigilancia RSI "
                      f"({puntos_sin_rsi} pts sin RSI, dir={direction}, RSI={rsi:.1f})")
        except Exception as e:
            print(f"[rsi-watch] Error evaluando {t}: {e}")

    _rsi_watchlist = new_watchlist
    if _rsi_watchlist:
        print(f"[rsi-watch] Vigilando {len(_rsi_watchlist)} activo(s): "
              f"{', '.join(_rsi_watchlist.keys())}")
    else:
        print("[rsi-watch] Sin activos en vigilancia RSI")


async def _rsi_realtime_check():
    """Cada 2 min revisa SOLO el RSI de los activos en la watchlist.
    Si el RSI cruza la zona extrema (≤30 largos, ≥70 cortos) → alerta inmediata."""
    if not HAS_NOTIFIER or not _rsi_watchlist:
        return

    now = time.time()
    alertas_rsi: dict = {}

    for ticker, info in list(_rsi_watchlist.items()):
        try:
            df = await async_download(ticker, period="5d", interval="15m", progress=False)
            if df.empty:
                continue
            df = clean_df(df)

            if "RSI" not in df.columns:
                d = df["Close"].diff()
                losses = (-d.where(d < 0, 0)).rolling(14).mean().replace(0, np.nan)
                df["RSI"] = 100 - (100 / (1 + d.where(d > 0, 0).rolling(14).mean() / losses))

            rsi_series = df["RSI"].dropna()
            if rsi_series.empty:
                continue
            rsi_now = float(rsi_series.iloc[-1])

            direction = info["direction"]
            triggered = (direction == "bullish" and rsi_now <= 30) or \
                        (direction == "bearish" and rsi_now >= 70)

            if not triggered:
                continue

            dedup_key = f"RSI_RT_{ticker}_{direction}"
            if now - _sent_cache.get(dedup_key, 0) < _DEDUP_SECONDS:
                continue

            cfg = info["cfg"]
            df_4h = await async_download(ticker, period="6mo", interval="4h", progress=False)
            if df_4h.empty:
                continue
            df_4h = clean_df(df_4h)
            df_4h = calc_indicators(df_4h, cfg["ema_short"], cfg["ema_long"])
            opens_data = calc_opens(df_4h)

            components_ctx = info.get("components_ctx")
            resultado = evaluate_confluencias(df_4h, ticker=ticker, cfg=cfg,
                                              opens=opens_data, components_ctx=components_ctx)

            if not resultado:
                continue

            resultado["rsi"] = rsi_now
            for c in resultado.get("confluencias", []):
                if c["id"] == 1:
                    if direction == "bullish" and rsi_now <= 30:
                        c["ok"] = True
                        c["tipo"] = "bullish"
                        c["texto"] = f"⚡ RSI en zona ({rsi_now:.1f}) → COMPRA"
                        c.pop("descartada", None)
                        c.pop("conflicto", None)
                    elif direction == "bearish" and rsi_now >= 70:
                        c["ok"] = True
                        c["tipo"] = "bearish"
                        c["texto"] = f"⚡ RSI en zona ({rsi_now:.1f}) → VENTA"
                        c.pop("descartada", None)
                        c.pop("conflicto", None)

            puntos = sum(
                1 + c.get("pts_extra", 0)
                for c in resultado["confluencias"]
                if c.get("ok") and not c.get("descartada") and not c.get("conflicto")
                and c.get("tipo") not in ("neutral", "info")
            ) + sum(
                1 for c in resultado["confluencias"]
                if c.get("ok") and not c.get("descartada") and not c.get("conflicto")
                and c.get("tipo") == "neutral"
            )
            resultado["puntos"] = puntos
            resultado["estado"] = "FAVORABLE" if puntos >= 4 else "INTERESANTE"
            resultado["nivel"] = direction
            # aleta extrema genera alerta aunque no llegue a 4 pts base
            shark_immediate = any(
                c.get("alert_immediate") and c.get("shark")
                for c in resultado.get("confluencias", [])
            )
            resultado["alert"] = puntos >= 4 or shark_immediate
            resultado["rsi_realtime"] = True

            if resultado["alert"]:
                ts_now = pd.Timestamp.now(tz="UTC")
                # Determinar emoji según si hay aleta
                shark_c = next((c for c in resultado.get("confluencias",[])
                                if c.get("shark") and c.get("alert_immediate")), None)
                if shark_c and shark_c["shark"].get("phase") == "exceeded":
                    msg_txt = f"[{ticker}] ⚡🦈 ALETA TIBURÓN EXTREMA — {resultado['estado']} ({puntos} pts)"
                elif shark_c:
                    msg_txt = f"[{ticker}] 🦈 Aleta tiburón confirmada — {resultado['estado']} ({puntos} pts)"
                else:
                    msg_txt = f"[{ticker}] ⚡ RSI EN ZONA — {resultado['estado']}"
                alertas_rsi[ticker] = [{
                    "nivel": direction,
                    "msg": msg_txt,
                    "hora": ts_now.strftime("%d/%m %H:%M"),
                    "ts_utc_iso": ts_now.isoformat(),
                    "dia_num": ts_now.weekday(),
                    "dia_name": ts_now.strftime("%A"),
                    "resultado": resultado,
                    "components_ctx": components_ctx,
                }]
                _sent_cache[dedup_key] = now
                del _rsi_watchlist[ticker]
                print(f"[rsi-watch] ⚡ {ticker} RSI={rsi_now:.1f} cruzó zona extrema "
                      f"({direction}) → ALERTA INMEDIATA")

            # ── Aleta tiburón standalone: alerta inmediata en df_4h ──────────
            shark_4h = calc_shark_fin(df_4h, lookback=30)
            if shark_4h.get("alert_immediate") and shark_4h.get("phase") in ("exceeded", "crossed"):
                s_tipo  = shark_4h["shark_tipo"]
                s_phase = shark_4h["phase"]
                shark_key = f"SHARK_{ticker}_{s_tipo}_{s_phase}"
                if now - _sent_cache.get(shark_key, 0) >= _DEDUP_SECONDS:
                    if s_phase == "exceeded":
                        s_emoji = "⚡🦈"; pts_lbl = "+4 pts"
                        s_msg = (f"[{ticker}] {s_emoji} ALETA TIBURÓN EXTREMA\n"
                                 f"RSI {'pico' if s_tipo=='bearish' else 'valle'} "
                                 f"{shark_4h['shark_rsi_peak']:.1f} superó "
                                 f"{'R1' if s_tipo=='bearish' else 'S1'}="
                                 f"{shark_4h['shark_div_r1']:.1f}")
                    else:
                        s_emoji = "🦈"; pts_lbl = "+2 pts"
                        s_msg = (f"[{ticker}] {s_emoji} Aleta tiburón "
                                 f"{'bajista' if s_tipo=='bearish' else 'alcista'} confirmada\n"
                                 f"RSI cruzó {'<70' if s_tipo=='bearish' else '>30'} "
                                 f"tras divergencia")
                    ts_now = pd.Timestamp.now(tz="UTC")
                    alertas_rsi.setdefault(ticker, []).append({
                        "nivel": s_tipo,
                        "msg": s_msg,
                        "hora": ts_now.strftime("%d/%m %H:%M"),
                        "ts_utc_iso": ts_now.isoformat(),
                        "dia_num": ts_now.weekday(),
                        "dia_name": ts_now.strftime("%A"),
                        "resultado": None,
                        "components_ctx": None,
                        "shark_data": shark_4h,
                        "pts_label": pts_lbl,
                    })
                    _sent_cache[shark_key] = now
                    print(f"[shark] {s_emoji} {ticker} — {s_phase} RSI={shark_4h['shark_rsi_peak']:.1f}")

        except Exception as e:
            print(f"[rsi-watch] Error revisando RSI de {ticker}: {e}")

    if alertas_rsi:
        await notify_users_with_alerts(alertas_rsi)


async def _pattern_realtime_check():
    """Cada N min revisa si está formándose el 2º pico (M), 2º valle (W)
    o 2º hombro (HCH/HCHi) en las últimas velas. Si coincide con ≥2
    confluencias adicionales en la misma dirección → 1 alerta inmediata.
    Dedup 12h: si el mismo patrón ya se notificó, NO se reenvía."""
    if not HAS_NOTIFIER:
        return

    now = time.time()
    alertas_pat: dict = {}

    for ticker in WATCH_TICKERS:
        try:
            cfg = get_cfg(ticker)
            df = await async_download(ticker, period="6mo", interval="4h", progress=False)
            if df.empty:
                continue
            df = clean_df(df)
            df = calc_indicators(df, cfg["ema_short"], cfg["ema_long"])
            n = len(df)
            if n < 30:
                continue

            mw  = calc_pattern_mw(df, lookback=30)
            hch = calc_pattern_hch(df, lookback=60)

            shape = tipo = None
            second_idx = -1
            descripcion = ""

            # Prioridad: HCH/HCHi (más fiable) sobre M/W
            if hch.get("points"):
                p = hch["points"]
                if p["rs_idx"] >= n - _PATTERN_RECENT_BARS:
                    shape = p["shape"]; tipo = p["tipo"]; second_idx = p["rs_idx"]
                    descripcion = ("Segundo hombro de HCH invertido formándose"
                                   if shape == "HCHi"
                                   else "Segundo hombro de HCH formándose")
            if not shape and mw.get("points"):
                p = mw["points"]
                if p["p2_idx"] >= n - _PATTERN_RECENT_BARS:
                    shape = p["shape"]; tipo = p["tipo"]; second_idx = p["p2_idx"]
                    descripcion = ("Segundo pico de M (doble techo) formándose"
                                   if shape == "M"
                                   else "Segundo valle de W (doble suelo) formándose")

            # ── Aleta de tiburón: check independiente del patrón ──────────────
            shark = calc_shark_fin(df, lookback=30)
            if shark.get("alert_immediate") and shark.get("phase") in ("exceeded", "crossed"):
                s_tipo  = shark["shark_tipo"]
                s_phase = shark["phase"]
                shark_key = f"SHARK_{ticker}_{s_tipo}_{s_phase}"
                if now - _sent_cache.get(shark_key, 0) >= _PATTERN_DEDUP_SECONDS:
                    # Necesitamos las confluencias para validar ≥1 extra alineada
                    opens_s = calc_opens(df)
                    comp_s  = None
                    if ticker in INDEX_COMPONENTS:
                        try:
                            comp_s = await get_index_components_context(ticker)
                        except Exception:
                            pass
                    res_s = evaluate_confluencias(df, ticker=ticker, cfg=cfg,
                                                  opens=opens_s, components_ctx=comp_s)
                    if res_s:
                        extras_s = sum(
                            1 for c in res_s.get("confluencias", [])
                            if c.get("ok") and not c.get("descartada")
                            and not c.get("conflicto")
                            and c.get("tipo") == s_tipo
                            and c.get("id") != 7   # no contar la propia ⑦ de la aleta
                        )
                        if extras_s >= 1:
                            # Enriquecer confluencia ⑦ en el resultado para el mensaje
                            for c in res_s.get("confluencias", []):
                                if c["id"] == 7 and c.get("shark"):
                                    c["alert_immediate"] = True
                            puntos_s = sum(
                                1 + c.get("pts_extra", 0)
                                for c in res_s["confluencias"]
                                if c.get("ok") and not c.get("descartada")
                                and not c.get("conflicto")
                                and c.get("tipo") not in ("neutral", "info")
                            ) + sum(
                                1 for c in res_s["confluencias"]
                                if c.get("ok") and not c.get("descartada")
                                and not c.get("conflicto")
                                and c.get("tipo") == "neutral"
                            )
                            res_s["puntos"] = puntos_s
                            res_s["estado"] = "FAVORABLE" if puntos_s >= 4 else "INTERESANTE"
                            res_s["nivel"]  = s_tipo
                            res_s["alert"]  = True
                            res_s["shark_realtime"] = True

                            s_emoji = "⚡🦈" if s_phase == "exceeded" else "🦈"
                            s_dir   = "bajista" if s_tipo == "bearish" else "alcista"
                            ts_now  = pd.Timestamp.now(tz="UTC")
                            alertas_pat.setdefault(ticker, []).append({
                                "nivel": s_tipo,
                                "msg": f"[{ticker}] {s_emoji} Aleta tiburón {s_dir} "
                                       f"{'EXTREMA' if s_phase == 'exceeded' else 'confirmada'} "
                                       f"+ {extras_s} confluencia(s) alineada(s)",
                                "hora": ts_now.strftime("%d/%m %H:%M"),
                                "ts_utc_iso": ts_now.isoformat(),
                                "dia_num": ts_now.weekday(),
                                "dia_name": ts_now.strftime("%A"),
                                "resultado": res_s,
                                "components_ctx": comp_s,
                            })
                            _sent_cache[shark_key] = now
                            print(f"[shark-rt] {s_emoji} {ticker} — {s_phase} "
                                  f"RSI={shark['shark_rsi_peak']:.1f} "
                                  f"+{extras_s} confluencias → ALERTA INMEDIATA")

            if not shape:
                continue

            # Dedup estricto: ticker + shape + tipo (no se reenvía en 12h)
            dedup_key = f"PAT_RT_{ticker}_{shape}_{tipo}"
            if now - _sent_cache.get(dedup_key, 0) < _PATTERN_DEDUP_SECONDS:
                continue

            # Confluencias: necesitamos ≥2 EXTRA (sin contar la ⑧) en la misma dirección
            opens_data = cls_ctx = None
            opens_data = calc_opens(df)
            components_ctx = None
            if ticker in INDEX_COMPONENTS:
                try:
                    components_ctx = await get_index_components_context(ticker)
                except Exception:
                    pass

            resultado = evaluate_confluencias(df, ticker=ticker, cfg=cfg,
                                              opens=opens_data,
                                              components_ctx=components_ctx)
            if not resultado:
                continue

            extras = sum(
                1 for c in resultado.get("confluencias", [])
                if c.get("ok") and not c.get("descartada") and not c.get("conflicto")
                and c.get("tipo") == tipo and c.get("id") != 8
            )
            if extras < _PATTERN_MIN_EXTRA_CONFLUENCIAS:
                continue

            # Forzar el aviso de "patrón formándose" en la confluencia ⑧
            for c in resultado.get("confluencias", []):
                if c["id"] == 8:
                    c["ok"] = True
                    c["tipo"] = tipo
                    c["texto"] = f"⚡ {descripcion} (en formación)"
                    c.pop("descartada", None)
                    c.pop("conflicto", None)
            puntos = sum(1 for c in resultado["confluencias"]
                         if c.get("ok") and not c.get("descartada") and not c.get("conflicto"))
            resultado["puntos"] = puntos
            resultado["estado"] = "FAVORABLE" if puntos >= 4 else "INTERESANTE"
            resultado["nivel"] = tipo
            resultado["alert"] = True
            resultado["pattern_realtime"] = True

            ts_now = pd.Timestamp.now(tz="UTC")
            alertas_pat[ticker] = [{
                "nivel": tipo,
                "msg": f"[{ticker}] ⚡ PATRÓN EN FORMACIÓN — {descripcion}",
                "hora": ts_now.strftime("%d/%m %H:%M"),
                "ts_utc_iso": ts_now.isoformat(),
                "dia_num": ts_now.weekday(),
                "dia_name": ts_now.strftime("%A"),
                "resultado": resultado,
                "components_ctx": components_ctx,
            }]
            _sent_cache[dedup_key] = now
            print(f"[pattern-rt] ⚡ {ticker} {shape} ({tipo}) "
                  f"+{extras} confluencias extra → ALERTA")

        except Exception as e:
            print(f"[pattern-rt] Error revisando {ticker}: {e}")

    if alertas_pat:
        await notify_users_with_alerts(alertas_pat)


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

    async def _warm_row_cache():
        print("[cache] Pre-calentando datos de los 9 activos…")
        for t in WATCH_TICKERS:
            try:
                await _compute_row(t)
            except Exception as e:
                print(f"[cache] Error calentando {t}: {e}")
        print("[cache] Cache de activos lista")

    @asynccontextmanager
    async def lifespan(app):
        scheduler = None
        polling_task = None
        token = os.getenv("TELEGRAM_TOKEN", "")
        if token:
            polling_task = asyncio.create_task(_tg_polling(token))
        try:
            scheduler = AsyncIOScheduler()
            scheduler.add_job(scheduled_watch, "interval", minutes=30, id="watch_30m")
            scheduler.add_job(_rsi_realtime_check, "interval",
                              minutes=_RSI_WATCH_INTERVAL_MIN, id="rsi_rt")
            scheduler.add_job(_pattern_realtime_check, "interval",
                              minutes=_PATTERN_WATCH_INTERVAL_MIN, id="pattern_rt")
            scheduler.start()
            print(f"[scheduler] Iniciado · 30 min · RSI {_RSI_WATCH_INTERVAL_MIN}m · Patrones {_PATTERN_WATCH_INTERVAL_MIN}m (dedup 12h)")
            # Catch-up: enviar alertas de las últimas 24h al arrancar
            asyncio.create_task(daily_catchup())
            asyncio.create_task(_warm_row_cache())
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


@app.get("/api/mail-subs")
async def mail_subs():
    if not HAS_NOTIFIER:
        return {"ok": False, "subs": 0}
    from notifier import get_all_user_prefs
    try:
        prefs = await get_all_user_prefs()
        count = sum(1 for p in prefs if p.get("email_enabled") and p.get("email_address"))
        return {"ok": True, "subs": count}
    except Exception:
        return {"ok": False, "subs": 0}


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

        # ── Overlays de patrones detectados (para dibujar en el gráfico) ──
        def _idx_to_x(i):
            try:
                return ts[int(i)]
            except Exception:
                return None

        overlays = {"divergence": None, "mw": None, "hch": None}
        patterns = {"M": None, "W": None, "HCH": None, "HCH_inv": None}
        divergences = {"bear_div": False, "bull_div": False,
                       "hidden_bear": False, "hidden_bull": False,
                       "bear_lines": [], "bull_lines": []}
        try:
            div = calc_rsi_divergence(df, lookback=10)
            divergences.update({
                "bear_div": div["bear_div"], "bull_div": div["bull_div"],
                "hidden_bear": div["hidden_bear"], "hidden_bull": div["hidden_bull"],
            })
            if div.get("points"):
                p = div["points"]
                ovd = {
                    "kind": p["kind"], "tipo": p["tipo"],
                    "p1": {"x": _idx_to_x(p["p1_idx"]),
                           "price": p["p1_price"], "rsi": p["p1_rsi"]},
                    "p2": {"x": _idx_to_x(p["p2_idx"]),
                           "price": p["p2_price"], "rsi": p["p2_rsi"]},
                }
                overlays["divergence"] = ovd
                # también en bear/bull_lines para el RSI chart
                line = {"x0": _idx_to_x(p["p1_idx"]), "x1": _idx_to_x(p["p2_idx"]),
                        "rsi0": p["p1_rsi"], "rsi1": p["p2_rsi"],
                        "p0": p["p1_price"], "p1": p["p2_price"],
                        "tipo": p["kind"]}
                if p["tipo"] == "bearish":
                    divergences["bear_lines"].append(line)
                else:
                    divergences["bull_lines"].append(line)

            mw = calc_pattern_mw(df, lookback=30)
            if mw.get("points"):
                p = mw["points"]
                estado = p.get("estado", "formando")
                overlays["mw"] = {
                    "shape": p["shape"], "tipo": p["tipo"],
                    "with_div": p["with_div"], "neckline": p["neckline"],
                    "estado": estado,
                    "p1": {"x": _idx_to_x(p["p1_idx"]), "y": p["p1_y"]},
                    "p2": {"x": _idx_to_x(p["p2_idx"]), "y": p["p2_y"]},
                }
                key = "M" if p["shape"] == "M" else "W"
                patterns[key] = {
                    "p1_x": _idx_to_x(p["p1_idx"]), "p1_y": p["p1_y"],
                    "p2_x": _idx_to_x(p["p2_idx"]), "p2_y": p["p2_y"],
                    "neckline": p["neckline"], "rsi_div": p["with_div"],
                    "estado": estado,
                    "bearish": p["tipo"] == "bearish",
                }

            hch = calc_pattern_hch(df, lookback=60)
            if hch.get("points"):
                p = hch["points"]
                estado = p.get("estado", "formando")
                overlays["hch"] = {
                    "shape": p["shape"], "tipo": p["tipo"],
                    "confirmed": p["confirmed"], "neckline": p["neckline"],
                    "estado": estado,
                    "ls":   {"x": _idx_to_x(p["ls_idx"]),   "y": p["ls_y"]},
                    "head": {"x": _idx_to_x(p["head_idx"]), "y": p["head_y"]},
                    "rs":   {"x": _idx_to_x(p["rs_idx"]),   "y": p["rs_y"]},
                }
                key = "HCH" if p["shape"] == "HCH" else "HCH_inv"
                patterns[key] = {
                    "hi_x":  _idx_to_x(p["ls_idx"]),   "hi_y":  p["ls_y"],
                    "cab_x": _idx_to_x(p["head_idx"]), "cab_y": p["head_y"],
                    "hd_x":  _idx_to_x(p["rs_idx"]),   "hd_y":  p["rs_y"],
                    "nk1_x": _idx_to_x(p["ls_idx"]),   "nk1_y": p["neckline"],
                    "nk2_x": _idx_to_x(p["rs_idx"]),   "nk2_y": p["neckline"],
                    "neckline": p["neckline"], "estado": estado,
                    "bearish": p["tipo"] == "bearish",
                }
        except Exception as ovl_err:
            print(f"[overlays] failed for {ticker}: {ovl_err}")

        return {
            "chart": {
                "candles": candles,
                f"ema{es}": ema_s(f"EMA{es}"),
                f"ema{el}": ema_s(f"EMA{el}"),
                "rsi_os": ros,
                "rsi_ob": rob,
                "fractal_touch_candles": ftc,
                "overlays": overlays,
            },
            "patterns": patterns,
            "divergences": divergences,
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


async def _compute_row(ticker: str) -> dict:
    key = ticker.upper()
    now = time.time()
    cached = _row_cache.get(key)
    if cached and now - cached["ts"] < _ROW_TTL:
        return cached["data"]
    cfg = get_cfg(ticker)
    es, el = cfg["ema_short"], cfg["ema_long"]
    df = await async_download(key, period="1y", interval="4h", progress=False)
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
    row_components_ctx = None
    if key in INDEX_COMPONENTS:
        try:
            row_components_ctx = await get_index_components_context(key)
        except Exception:
            pass
    confl = evaluate_confluencias(df, ticker=key, cfg=cfg, opens=opens, components_ctx=row_components_ctx)

    # ── Patrones detectados (para columna en tabla y badge en RSI) ──
    div_info = None
    pat_info = None
    try:
        _div = calc_rsi_divergence(df, lookback=10)
        if _div.get("points"):
            p = _div["points"]
            div_info = {"kind": p["kind"], "tipo": p["tipo"]}
        _hch = calc_pattern_hch(df, lookback=60)
        if _hch.get("points"):
            p = _hch["points"]
            pat_info = {"shape": p["shape"], "tipo": p["tipo"],
                        "confirmed": p["confirmed"]}
        else:
            _mw = calc_pattern_mw(df, lookback=30)
            if _mw.get("points"):
                p = _mw["points"]
                pat_info = {"shape": p["shape"], "tipo": p["tipo"],
                            "confirmed": p["with_div"]}
    except Exception as _e:
        print(f"[row patterns] {key}: {_e}")

    result = {
        "ticker": key,
        "price": last,
        "change_pct": round((last - first) / first * 100, 2),
        "rsi": round(rsi, 1) if rsi else None,
        "divergence": div_info,
        "pattern": pat_info,
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
        "confluencias_max": confl.get("max_confs", 5) if confl else 5,
        "confluencias_estado": confl["estado"] if confl else "NO AHORA",
        "confluencias_direction": confl.get("direction", "info") if confl else "info",
        "confluencias_contradiccion": confl.get("contradiccion", False) if confl else False,
        "confluencias": confl["confluencias"] if confl else [],
        "confluencias_rsi": confl["rsi"] if confl else None,
    }
    _row_cache[key] = {"ts": now, "data": result}
    return result


@app.get("/api/row/{ticker}")
async def get_row(ticker: str):
    try:
        return await _compute_row(ticker)
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
