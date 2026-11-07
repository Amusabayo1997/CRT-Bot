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
    return "CRT Bot is AWAKE - 6/7 Score Only!"
def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
threading.Thread(target=run_web, daemon=True).start()

BOT_START = datetime.now(timezone.utc)

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
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def to_lagos(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    lagos = dt.astimezone(timezone(timedelta(hours=1)))
    return lagos

def get_df(ticker, period, interval):
    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False)
    if df.empty: return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

def score_crt(df, idx_prev, idx_crt, idx_confirm, direction, tf, ticker):
    score = 0
    details = []
    prev = df.iloc[idx_prev]
    crt = df.iloc[idx_crt]
    confirm = df.iloc[idx_confirm]

    # 1. REAL LIQUIDITY - prev High/Low was highest/lowest of last 5 candles
    window = df.iloc[max(0, idx_prev-5):idx_prev]
    if direction == "BEARISH":
        is_clear_level = prev["High"] >= window["High"].max() * 0.999
        sweep_pct = (crt["High"] - prev["High"]) / prev["High"] * 100 if prev["High"] != 0 else 99
        if is_clear_level and 0 < sweep_pct < 0.8:
            score += 1; details.append("1.Liquidity ✅")
        else:
            details.append("1.Liquidity ❌")
    else:
        is_clear_level = prev["Low"] <= window["Low"].min() * 1.001
        sweep_pct = (prev["Low"] - crt["Low"]) / prev["Low"] * 100 if prev["Low"] != 0 else 99
        if is_clear_level and 0 < sweep_pct < 0.8:
            score += 1; details.append("1.Liquidity ✅")
        else:
            details.append("1.Liquidity ❌")

    # 2. WICK ONLY - body closed back inside
    if direction == "BEARISH":
        if crt["High"] > prev["High"] and crt["Close"] < prev["High"]:
            score += 1; details.append("2.Wick ✅")
        else:
            details.append("2.Wick ❌")
    else:
        if crt["Low"] < prev["Low"] and crt["Close"] > prev["Low"]:
            score += 1; details.append("2.Wick ✅")
        else:
            details.append("2.Wick ❌")

    # 3. STRONG PUSH - CRT candle bigger than average of last 3
    avg_range = df.iloc[idx_prev-2:idx_prev+1]["High"].sub(df.iloc[idx_prev-2:idx_prev+1]["Low"]).mean()
    crt_range = crt["High"] - crt["Low"]
    if crt_range > avg_range * 1.0:
        score += 1; details.append("3.Strong ✅")
    else:
        details.append("3.Strong ❌")

    # 4. OPPOSITE CLOSE
    if direction == "BEARISH" and crt["Close"] < crt["Open"]:
        score += 1; details.append("4.Red ✅")
    elif direction == "BULLISH" and crt["Close"] > crt["Open"]:
        score += 1; details.append("4.Green ✅")
    else:
        details.append("4.Colour ❌")

    # 5. CONFIRMATION HELD
    if direction == "BEARISH" and confirm["High"] < prev["High"] and confirm["Close"] < prev["High"]:
        score += 1; details.append("5.Confirm ✅")
    elif direction == "BULLISH" and confirm["Low"] > prev["Low"] and confirm["Close"] > prev["Low"]:
        score += 1; details.append("5.Confirm ✅")
    else:
        details.append("5.Confirm ❌")

    # 6. HTF AGREES
    try:
        if tf == "DAILY":
            wdf = get_df(ticker, "3mo", "1wk")
            if len(wdf) >= 2:
                w_crt = wdf.iloc[-1]
                if direction == "BEARISH" and w_crt["Close"] < w_crt["Open"]:
                    score += 1; details.append("6.HTF ✅")
                elif direction == "BULLISH" and w_crt["Close"] > w_crt["Open"]:
                    score += 1; details.append("6.HTF ✅")
                else:
                    details.append("6.HTF ❌")
            else:
                score += 1; details.append("6.HTF ✅")
        elif tf == "4H":
            ddf = get_df(ticker, "3mo", "1d")
            if len(ddf) >= 2:
                d = ddf.iloc[-2]
                if direction == "BEARISH" and d["Close"] < d["Open"]:
                    score += 1; details.append("6.HTF ✅")
                elif direction == "BULLISH" and d["Close"] > d["Open"]:
                    score += 1; details.append("6.HTF ✅")
                else:
                    details.append("6.HTF ❌")
            else:
                score += 1; details.append("6.HTF ✅")
        else:
            score += 1; details.append("6.HTF ✅ (Weekly)")
    except:
        score += 1; details.append("6.HTF ✅")

    # 7. GOOD TIME - Daily/Weekly close 11pm Lagos = good
    if tf in ["DAILY", "WEEKLY"]:
        score += 1; details.append("7.Time ✅ (11pm Close)")
    else:
        score += 1; details.append("7.Time ✅")

    return score, details

def check_pair(name, ticker):
    results = []
    now = datetime.now(timezone.utc)
    try:
        for tf, interval, max_age in [("DAILY", "1d", 3), ("WEEKLY", "1wk", 6)]:
            df = get_df(ticker, "3mo", interval)
            if df.empty or len(df) < 6: continue
            prev = df.iloc[-4]; crt_c = df.iloc[-3]; confirm = df.iloc[-2]
            direction = None
            if crt_c["High"] > prev["High"] and crt_c["Close"] < prev["High"] and crt_c["Close"] < crt_c["Open"]:
                direction = "BEARISH"
            elif crt_c["Low"] < prev["Low"] and crt_c["Close"] > prev["Low"] and crt_c["Close"] > crt_c["Open"]:
                direction = "BULLISH"
            if not direction: continue

            score, details = score_crt(df, -4, -3, -2, direction, tf, ticker)
            if score < 6:
                print(f"SKIP {name} {tf} {direction} Score {score}/7 {details}")
                continue

            candle_start = df.index[-3]
            if candle_start.tzinfo is None:
                candle_start = candle_start.replace(tzinfo=timezone.utc)
            close_time = candle_start + timedelta(days=1 if tf=="DAILY" else 7)
            confirm_close = close_time + timedelta(days=1 if tf=="DAILY" else 7)
            if confirm_close < BOT_START: continue
            if (now - confirm_close).total_seconds() > max_age * 3600: continue

            key = f"{name}-{tf}-{close_time}-{direction}-{score}"
            if key in sent_alerts: continue
            sent_alerts.add(key)
            lagos = to_lagos(close_time).strftime('%A, %d %b %Y - %I:%M %p')
            results.append(f"🔔 {direction} CRT ✅ CONFIRMED - SCORE {score}/7 on {name} - {tf}\nPrice: {crt_c['Close']:.5f}\nCRT Closed: {lagos} (Lagos)\nChecklist: {' | '.join(details)}")

        # 4H
        df_1h = get_df(ticker, "60d", "60m")
        if not df_1h.empty:
            df_4h = df_1h.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
            if len(df_4h) >= 6:
                prev = df_4h.iloc[-4]; crt_c = df_4h.iloc[-3]; confirm = df_4h.iloc[-2]
                direction = None
                if crt_c["High"] > prev["High"] and crt_c["Close"] < prev["High"] and crt_c["Close"] < crt_c["Open"]:
                    direction = "BEARISH"
                elif crt_c["Low"] < prev["Low"] and crt_c["Close"] > prev["Low"] and crt_c["Close"] > crt_c["Open"]:
                    direction = "BULLISH"
                if direction:
                    score, details = score_crt(df_4h, -4, -3, -2, direction, "4H", ticker)
                    candle_start = df_4h.index[-3]
                    if candle_start.tzinfo is None:
                        candle_start = candle_start.replace(tzinfo=timezone.utc)
                    close_time = candle_start + timedelta(hours=4)
                    lagos_hour = to_lagos(close_time).hour
                    if lagos_hour not in [0,8,12,16,20,23]:
                        score -= 1
                        details = [d.replace("7.Time ✅","7.Time ❌ (Bad session)") for d in details]
                    if score < 6:
                        print(f"SKIP {name} 4H {direction} Score {score}/7")
                        return results 
                    confirm_close = close_time + timedelta(hours=4)
                    if confirm_close >= BOT_START and (now - confirm_close).total_seconds() <= 3600:
                        key = f"{name}-4H-{close_time}-{direction}-{score}"
                        if key not in sent_alerts:
                            sent_alerts.add(key)
                            lagos = to_lagos(close_time).strftime('%A, %d %b %Y - %I:%M %p')
                            results.append(f"🔔 {direction} CRT ✅ CONFIRMED - SCORE {score}/7 on {name} - 4H\nPrice: {crt_c['Close']:.5f}\nCRT Closed: {lagos} (Lagos)\nChecklist: {' | '.join(details)}")
    except Exception as e:
        print(f"Error {name}: {e}")
    return results

print("CRT Bot Started - 6/7 ONLY")
send_telegram("✅ CRT Bot ONLINE - 6/7 VERSION\nOnly sends CRTs that score 6/7 or 7/7.\nWeak CRTs will be skipped. Lagos Time.")

while True:
    print(f"Checking... {datetime.now()}")
    all_alerts = []
    for name, ticker in PAIRS.items():
        alerts = check_pair(name, ticker)
        all_alerts.extend(alerts)
    for alert in all_alerts:
        send_telegram(alert)
    time.sleep(1800)
