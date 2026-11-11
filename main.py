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

def check_zone(df, curr_idx, direction, sweep_price):
    zones = []
    try:
        lookback = df.iloc[max(0, curr_idx-30):curr_idx]
        if len(lookback) < 5:
            return zones
        tol = abs(sweep_price) * 0.0035
        swing_high = lookback["High"].max()
        swing_low = lookback["Low"].min()
        recent_highs = lookback["High"].nlargest(3).tolist()
        recent_lows = lookback["Low"].nsmallest(3).tolist()

        if direction == "BEARISH":
            if abs(sweep_price - swing_high) <= tol:
                zones.append("Supply / Resistance / POI")
            for h in recent_highs:
                if abs(sweep_price - h) <= tol and "Supply / Resistance / POI" not in zones:
                    zones.append("Supply / Resistance / POI")
                    break
            for i in range(len(lookback)-1, max(0, len(lookback)-10), -1):
                c = lookback.iloc[i]
                if c["Close"] > c["Open"]:
                    if abs(sweep_price - c["High"]) <= tol or abs(sweep_price - c["Close"]) <= tol:
                        zones.append("Bearish OB")
                        break
        else:
            if abs(sweep_price - swing_low) <= tol:
                zones.append("Demand / Support / POI")
            for l in recent_lows:
                if abs(sweep_price - l) <= tol and "Demand / Support / POI" not in zones:
                    zones.append("Demand / Support / POI")
                    break
            for i in range(len(lookback)-1, max(0, len(lookback)-10), -1):
                c = lookback.iloc[i]
                if c["Close"] < c["Open"]:
                    if abs(sweep_price - c["Low"]) <= tol or abs(sweep_price - c["Close"]) <= tol:
                        zones.append("Bullish OB")
                        break

        for i in range(2, len(lookback)):
            c0 = lookback.iloc[i-2]
            c2 = lookback.iloc[i]
            if c0["High"] < c2["Low"]:
                fvg_low = c0["High"]
                fvg_high = c2["Low"]
                if direction == "BULLISH" and fvg_low - tol <= sweep_price <= fvg_high + tol:
                    zones.append("FVG (Bullish Gap)")
                    break
            if c0["Low"] > c2["High"]:
                fvg_low = c2["High"]
                fvg_high = c0["Low"]
                if direction == "BEARISH" and fvg_low - tol <= sweep_price <= fvg_high + tol:
                    zones.append("FVG (Bearish Gap)")
                    break
    except Exception as e:
        print(f"Zone check error: {e}")
    return zones

def check_pair(name, ticker):
    results = []
    now = datetime.now(timezone.utc)
    try:
        # FIXED: DAILY = 6mo, WEEKLY = 2y (so WEEKLY gets enough candles)
        for tf, interval, period, tf_hours in [("DAILY", "1d", "6mo", 24), ("WEEKLY", "1wk", "2y", 168)]:
            df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False)
            if df.empty or len(df) < 35:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            prev = df.iloc[-3]
            curr = df.iloc[-2]
            crt = is_crt_sweep(prev, curr)
            if not crt:
                continue

            direction = "BEARISH" if "BEARISH" in crt else "BULLISH"
            sweep_price = curr["High"] if direction == "BEARISH" else curr["Low"]
            zones = check_zone(df, len(df)-2, direction, sweep_price)
            if not zones:
                print(f"{name} {tf} sweep but NO ZONE - skipped")
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
            zone_text = " + ".join(zones)
            results.append(
                f"🚨 {crt} on {name} - {tf}\n"
                f"Date & Time Closed: {to_lagos(close_time)} (Lagos)\n"
                f"Range Candle High (BSL/CRH): {fmt_price(name, prev['High'])}\n"
                f"Range Candle Low (SSL/CRL): {fmt_price(name, prev['Low'])}\n"
                f"2nd Candle (Sweep) Open: {fmt_price(name, curr['Open'])}\n"
                f"2nd Candle (Sweep) Close: {fmt_price(name, curr['Close'])}\n"
                f"2nd Candle High: {fmt_price(name, curr['High'])}\n"
                f"2nd Candle Low: {fmt_price(name, curr['Low'])}\n"
                f"📍 Zone: Sweep at {zone_text} ✅"
            )

        df_1h = yf.download(ticker, period="60d", interval="60m", progress=False, auto_adjust=False)
        if not df_1h.empty and len(df_1h) > 35:
            if isinstance(df_1h.columns, pd.MultiIndex):
                df_1h.columns = df_1h.columns.get_level_values(0)
            df_4h = df_1h.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
            if len(df_4h) >= 35:
                prev = df_4h.iloc[-3]
                curr = df_4h.iloc[-2]
                crt = is_crt_sweep(prev, curr)
                if crt:
                    direction = "BEARISH" if "BEARISH" in crt else "BULLISH"
                    sweep_price = curr["High"] if direction == "BEARISH" else curr["Low"]
                    zones = check_zone(df_4h, len(df_4h)-2, direction, sweep_price)
                    if zones:
                        candle_start = df_4h.index[-2]
                        if candle_start.tzinfo is None:
                            candle_start = candle_start.replace(tzinfo=timezone.utc)
                        close_time = candle_start + timedelta(hours=4)
                        if close_time >= BOT_START and 0 <= (now - close_time).total_seconds() <= 900:
                            key = f"{name}-4H-{close_time}-{crt}"
                            if key not in sent_alerts:
                                sent_alerts.add(key)
                                zone_text = " + ".join(zones)
                                results.append(
                                    f"🚨 {crt} on {name} - 4H\n"
                                    f"Date & Time Closed: {to_lagos(close_time)} (Lagos)\n"
                                    f"Range Candle High (BSL/CRH): {fmt_price(name, prev['High'])}\n"
                                    f"Range Candle Low (SSL/CRL): {fmt_price(name, prev['Low'])}\n"
                                    f"2nd Candle (Sweep) Open: {fmt_price(name, curr['Open'])}\n"
                                    f"2nd Candle (Sweep) Close: {fmt_price(name, curr['Close'])}\n"
                                    f"2nd Candle High: {fmt_price(name, curr['High'])}\n"
                                    f"2nd Candle Low: {fmt_price(name, curr['Low'])}\n"
                                    f"📍 Zone: Sweep at {zone_text} ✅"
                                )
                    else:
                        print(f"{name} 4H sweep but NO ZONE - skipped")
    except Exception as e:
        print(f"Error {name}: {e}")
    return results

print("CRT Bot Started - ZONE MODE")
send_telegram("✅ CRT Bot ONLINE - ZONE MODE\nSweep must be at Supply/Demand OR POI OR FVG OR OB OR Support/Resistance.\nSignal immediately after 2nd candle close.")

while True:
    print(f"Checking... {datetime.now()}")
    all_alerts = []
    for name, ticker in PAIRS.items():
        all_alerts.extend(check_pair(name, ticker))
    for alert in all_alerts:
        send_telegram(alert)
    time.sleep(60)