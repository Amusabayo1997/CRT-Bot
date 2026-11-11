import yfinance as yf
import time
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import threading
import os
from flask import Flask

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

app = Flask(__name__)

@app.route('/')
def home():
    return "CRT Bot is AWAKE and watching!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

BOT_START = datetime.now(timezone.utc)
print(f"Bot started at {BOT_START}")

PAIRS = {
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X", "USDCAD": "USDCAD=X", "NZDUSD": "NZDUSD=X",
    "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X", "GBPJPY": "GBPJPY=X",
    "AUDJPY": "AUDJPY=X", "CADJPY": "CADJPY=X", "CHFJPY": "CHFJPY=X",
    "EURCHF": "EURCHF=X", "GBPCHF": "GBPCHF=X", "AUDCAD": "AUDCAD=X",
    "AUDNZD": "AUDNZD=X", "NZDJPY": "NZDJPY=X", "USDCHF": "USDCHF=X",
    "EURAUD": "EURAUD=X", "GBPAUD": "GBPAUD=X", "EURNZD": "EURNZD=X",
    "GBPNZD": "GBPNZD=X", "EURCAD": "EURCAD=X", "GBPCAD": "GBPCAD=X",
    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "USOIL": "CL=F",
    "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
    "US30": "^DJI", "NAS100": "^IXIC", "SPX500": "^GSPC"
}

sent_alerts = set()

def send_telegram(msg):
    if not TOKEN or not CHAT_ID:
        print("No TOKEN/CHAT_ID")
        return
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def to_lagos(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    lagos = dt.astimezone(timezone(timedelta(hours=1)))
    return lagos.strftime('%A, %d %b %Y - %I:%M %p')

def fmt_price(pair, price):
    if pair in ["XAUUSD", "XAGUSD", "USOIL", "BTCUSD", "ETHUSD", "US30", "NAS100", "SPX500"]:
        return f"{price:,.2f}"
    return f"{price:.5f}"

def is_crt_sweep(prev, curr):
    prev_bullish = prev["Close"] > prev["Open"]
    prev_bearish = prev["Close"] < prev["Open"]
    curr_bullish = curr["Close"] > curr["Open"]
    curr_bearish = curr["Close"] < curr["Open"]

    if prev_bullish and curr_bearish:
        swept_high = curr["High"] > prev["High"]
        closed_inside = curr["Close"] < prev["High"] and curr["Close"] > prev["Low"]
        if swept_high and closed_inside:
            return "BEARISH CRT 🔴 - BSL Sweep"

    if prev_bearish and curr_bullish:
        swept_low = curr["Low"] < prev["Low"]
        closed_inside = curr["Close"] > prev["Low"] and curr["Close"] < prev["High"]
        if swept_low and closed_inside:
            return "BULLISH CRT 🟢 - SSL Sweep"

    return None

def check_pair(name, ticker):
    results = []
    now = datetime.now(timezone.utc)
    try:
        for tf, interval, tf_hours in [("DAILY", "1d", 24), ("WEEKLY", "1wk", 168)]:
            df = yf.download(ticker, period="3mo", interval=interval, progress=False, auto_adjust=False)
            if df.empty or len(df) < 3:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            prev = df.iloc[-3]
            curr = df.iloc[-2]
            crt = is_crt_sweep(prev, curr)
            if not crt:
                continue

            candle_start = df.index[-2]
            if candle_start.tzinfo is None:
                candle_start = candle_start.replace(tzinfo=timezone.utc)
            close_time = candle_start + timedelta(hours=tf_hours)

            if close_time < BOT_START:
                continue
            if not (0 <= (now - close_time).total_seconds() <= 900):
                continue

            key = f"{name}-{tf}-{close_time}-{crt}"
            if key in sent_alerts:
                continue
            sent_alerts.add(key)
            results.append(
                f"🚨 {crt} on {name} - {tf}\n"
                f"Date & Time Closed: {to_lagos(close_time)} (Lagos)\n"
                f"Range Candle High (BSL/CRH): {fmt_price(name, prev['High'])}\n"
                f"Range Candle Low (SSL/CRL): {fmt_price(name, prev['Low'])}\n"
                f"2nd Candle (Sweep) Open: {fmt_price(name, curr['Open'])}\n"
                f"2nd Candle (Sweep) Close: {fmt_price(name, curr['Close'])}\n"
                f"2nd Candle High: {fmt_price(name, curr['High'])}\n"
                f"2nd Candle Low: {fmt_price(name, curr['Low'])}"
            )

        df_1h = yf.download(ticker, period="60d", interval="60m", progress=False, auto_adjust=False)
        if not df_1h.empty and len(df_1h) > 10:
            if isinstance(df_1h.columns, pd.MultiIndex):
                df_1h.columns = df_1h.columns.get_level_values(0)
            df_4h = df_1h.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
            if len(df_4h) >= 3:
                prev = df_4h.iloc[-3]
                curr = df_4h.iloc[-2]
                crt = is_crt_sweep(prev, curr)
                if crt:
                    candle_start = df_4h.index[-2]
                    if candle_start.tzinfo is None:
                        candle_start = candle_start.replace(tzinfo=timezone.utc)
                    close_time = candle_start + timedelta(hours=4)
                    if close_time >= BOT_START and 0 <= (now - close_time).total_seconds() <= 900:
                        key = f"{name}-4H-{close_time}-{crt}"
                        if key not in sent_alerts:
                            sent_alerts.add(key)
                            results.append(
                                f"🚨 {crt} on {name} - 4H\n"
                                f"Date & Time Closed: {to_lagos(close_time)} (Lagos)\n"
                                f"Range Candle High (BSL/CRH): {fmt_price(name, prev['High'])}\n"
                                f"Range Candle Low (SSL/CRL): {fmt_price(name, prev['Low'])}\n"
                                f"2nd Candle (Sweep) Open: {fmt_price(name, curr['Open'])}\n"
                                f"2nd Candle (Sweep) Close: {fmt_price(name, curr['Close'])}\n"
                                f"2nd Candle High: {fmt_price(name, curr['High'])}\n"
                                f"2nd Candle Low: {fmt_price(name, curr['Low'])}"
                            )
    except Exception as e:
        print(f"Error {name}: {e}")
    return results

print("CRT Bot Started - COMBINED MODE")
send_telegram("✅ CRT Bot ONLINE - COMBINED MODE\nPrevious pairs + New sweep logic.\n2nd candle sweep liquidity -> signal immediately after close.")

while True:
    print(f"Checking... {datetime.now()}")
    all_alerts = []
    for name, ticker in PAIRS.items():
        all_alerts.extend(check_pair(name, ticker))
    for alert in all_alerts:
        send_telegram(alert)
    time.sleep(60)