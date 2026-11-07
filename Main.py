import yfinance as yf
import time
import requests
import pandas as pd
from datetime import datetime
import threading
import os
from flask import Flask

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# --- Small door for UptimeRobot to knock on ---
app = Flask(__name__)

@app.route('/')
def home():
    return "CRT Bot is AWAKE and watching!"

def run_web():
    # Render gives us a PORT, we must use it
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# Start web door in background
threading.Thread(target=run_web, daemon=True).start()

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

# Memory to avoid sending same alert again and again
sent_alerts = set()

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def check_crt(df):
    if len(df) < 3:
        return None
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    prev_high, prev_low = prev["High"], prev["Low"]
    if curr["Low"] < prev_low and curr["Close"] > prev_low and curr["Close"] > curr["Open"]:
        return "BULLISH CRT"
    if curr["High"] > prev_high and curr["Close"] < prev_high and curr["Close"] < curr["Open"]:
        return "BEARISH CRT"
    return None

def check_pair(name, ticker):
    results = []
    try:
        for tf, interval in [("DAILY", "1d"), ("WEEKLY", "1wk")]:
            df = yf.download(ticker, period="3mo", interval=interval, progress=False, auto_adjust=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            crt = check_crt(df)
            if crt:
                # Use date + pair + tf as unique key
                key = f"{name}-{tf}-{df.index[-1].date()}-{crt}"
                if key not in sent_alerts:
                    sent_alerts.add(key)
                    results.append(f"{crt} on {name} - {tf} - Price: {float(df.iloc[-1]['Close']):.5f}")

        df_1h = yf.download(ticker, period="60d", interval="60m", progress=False, auto_adjust=False)
        if not df_1h.empty:
            if isinstance(df_1h.columns, pd.MultiIndex):
                df_1h.columns = df_1h.columns.get_level_values(0)
            df_4h = df_1h.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
            crt = check_crt(df_4h)
            if crt:
                key = f"{name}-4H-{df_4h.index[-1]}-{crt}"
                if key not in sent_alerts:
                    sent_alerts.add(key)
                    results.append(f"{crt} on {name} - 4H - Price: {float(df_4h.iloc[-1]['Close']):.5f}")
    except Exception as e:
        print(f"Error {name}: {e}")
    return results

print("CRT Screener Bot Started - Always Active Version...")
send_telegram("✅ CRT Screener Bot is ONLINE - Always Active Mode. Watching 31 pairs on Weekly, Daily, 4H")

while True:
    print(f"Checking... {datetime.now()}")
    for name, ticker in PAIRS.items():
        alerts = check_pair(name, ticker)
        for alert in alerts:
            send_telegram(f"🔔 {alert}")
    time.sleep(1800) # Check every 30 mins
