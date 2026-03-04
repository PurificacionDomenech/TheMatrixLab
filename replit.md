# The Matrix Lab

A financial market dashboard with real-time technical analysis built with FastAPI.

## Overview

"The Matrix Lab" is a web application that provides:
- Real-time market data for stocks, indices, forex, and commodities via yfinance
- Technical analysis: EMA 200/800, RSI, fractal levels
- Automatic alerts via Telegram and email
- A scheduler that runs market checks every 4 hours
- A Telegram bot integration for subscribing to alerts

## Stack

- **Backend**: FastAPI (Python 3.12), uvicorn
- **Data**: yfinance, pandas, numpy
- **Charts**: Plotly.js (client-side)
- **Notifications**: Telegram Bot API, SMTP email
- **Database**: Supabase (for telegram subs and user notification prefs)
- **Scheduler**: APScheduler (AsyncIOScheduler)

## Project Structure

```
main.py              # FastAPI app, API routes, scheduler
notifier.py          # Telegram and email notification logic
app.py               # Legacy tkinter GUI (not used in web mode)
graficos/chart_tv.py # Chart utilities
indicadores/etf.py   # ETF indicator utilities
templates/
  Splash.html        # Landing page
  index.html         # Main dashboard
static/              # Static files (logo, etc.)
```

## Running the App

The app runs via uvicorn on port 5000:
```
uvicorn main:app --host 0.0.0.0 --port 5000
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_TOKEN` | Optional | Telegram bot token for alerts |
| `SUPABASE_URL` | Optional | Supabase project URL |
| `SUPABASE_KEY` | Optional | Supabase service role key |
| `MAIL_FROM` | Optional | Gmail address for email alerts |
| `MAIL_PASSWORD` | Optional | Gmail App Password |
| `MAIL_TO` | Optional | Default email recipient |
| `MAIL_SMTP` | Optional | SMTP host (default: smtp.gmail.com) |
| `MAIL_PORT` | Optional | SMTP port (default: 587) |

The app runs without any environment variables set — notifications are simply disabled if credentials are missing.

## Deployment

Configured for autoscale deployment using gunicorn with UvicornWorker on port 5000.
