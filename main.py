import os, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"CRT Bot is Live")
    def log_message(self, *a):
        pass
def keep_alive():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), H).serve_forever()
threading.Thread(target=keep_alive, daemon=True).start()

import time, requests, sqlite3
from datetime import datetime, timedelta
import pytz

# ============ KEYS - PUT FOR RENDER ENV, NOT INSIDE CODE ============
TWELVE_KEY = os.getenv("TWELVE_KEY", "PASTE_TWELVE_KEY_HERE")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "PASTE_BOT_TOKEN_HERE")
CHAT_ID = os.getenv("CHAT_ID", "PASTE_CHAT_ID_HERE")
LAGOS = pytz.timezone("Africa/Lagos")
TIMEFRAMES = ["H4", "D1", "W1", "MN1"]

# ============ 27 SYMBOLS - FULL ============
MARKETS = {
    "FOREX": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURJPY", "GBPJPY", "EURGBP", "GBPAUD", "GBPCAD", "AUDJPY"],
    "PRECIOUS METALS": ["XAUUSD", "XAGUSD", "XPTUSD"],
    "CRYPTOCURRENCIES": ["BTCUSD", "ETHUSD", "BNBUSDT", "SOLUSD", "XRPUSD", "ADAUSD", "DOGEUSD"],
    "ENERGY": ["USOIL", "UKOIL"],
    "DOLLAR INDEX": ["DXY"]
}

DECIMALS = {"EURUSD": 5, "GBPUSD": 5, "USDJPY": 3, "AUDUSD": 5, "NZDUSD": 5, "USDCAD": 5, "USDCHF": 5, "EURJPY": 3, "GBPJPY": 3, "EURGBP": 5, "GBPAUD": 5, "GBPCAD": 5, "AUDJPY": 3, "XAUUSD": 2, "XAGUSD": 3, "XPTUSD": 2, "BTCUSD": 2, "ETHUSD": 2, "BNBUSDT": 2, "SOLUSD": 2, "XRPUSD": 4, "ADAUSD": 4, "DOGEUSD": 4, "USOIL": 2, "UKOIL": 2, "DXY": 2}

# Fix Binance symbols for Twelve Data
SYMBOL_MAP = {"BNBUSDT": "BNB/USD", "BTCUSD": "BTC/USD", "ETHUSD": "ETH/USD", "SOLUSD": "SOL/USD", "XRPUSD": "XRP/USD", "ADAUSD": "ADA/USD", "DOGEUSD": "DOGE/USD"}

def fmt(sym, price):
    d = DECIMALS.get(sym, 2)
    return f"{price:.{d}f}"

def send_telegram(msg):
    if not TELEGRAM_TOKEN or "PASTE" in TELEGRAM_TOKEN:
        print("No Telegram token")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=15)
        print("Telegram sent")
    except Exception as e:
        print("Telegram error:", e)

def get_candles(symbol, tf):
    try:
        api_sym = SYMBOL_MAP.get(symbol, symbol)
        # Twelve Data interval mapping
        interval = {"H4": "4h", "D1": "1day", "W1": "1week", "MN1": "1month"}[tf]
        url = "https://api.twelvedata.com/time_series"
        params = {"symbol": api_sym, "interval": interval, "outputsize": 5, "apikey": TWELVE_KEY}
        r = requests.get(url, params=params, timeout=20)
        data = r.json()
        if "values" not in data:
            print(f"No data {symbol} {tf}: {data.get('message', data)}")
            return None
        vals = data["values"]
        # values come newest first, reverse to oldest first
        vals = list(reversed(vals))
        candles = []
        for v in vals:
            candles.append({"open": float(v["open"]), "high": float(v["high"]), "low": float(v["low"]), "close": float(v["close"]), "time": v["datetime"]})
        return candles
    except Exception as e:
        print(f"Error {symbol} {tf}: {e}")
        return None

def check_crt(symbol, tf, candles):
    if not candles or len(candles) < 3:
        return None
    # Last 3 closed candles: c1, c2, c3
    c1 = candles[-3]
    c2 = candles[-2]
    c3 = candles[-1]
    # CRT Model: c1 sweeps high/low of c2, then c3 closes back inside = turtle soup / CRT
    # Bullish CRT: c1 takes low below c2 low, then closes back above c2 low
    # Bearish CRT: c1 takes high above c2 high, then closes back below c2 high
    bullish = c1["low"] < c2["low"] and c1["close"] > c2["low"] and c3["close"] > c1["high"]
    bearish = c1["high"] > c2["high"] and c1["close"] < c2["high"] and c3["close"] < c1["low"]
    if bullish:
        return "BULLISH"
    if bearish:
        return "BEARISH"
    return None

# DB to avoid duplicate alerts
conn = sqlite3.connect("alerts.db", check_same_thread=False)
conn.execute("CREATE TABLE IF NOT EXISTS sent (key TEXT PRIMARY KEY)")
conn.commit()

def already_sent(key):
    cur = conn.execute("SELECT 1 FROM sent WHERE key=?", (key,))
    return cur.fetchone() is not None

def mark_sent(key):
    try:
        conn.execute("INSERT INTO sent VALUES (?)", (key,))
        conn.commit()
    except:
        pass

def scan():
    now = datetime.now(LAGOS).strftime("%Y-%m-%d %H:%M Lagos")
    print(f"--- Scan started {now} ---", flush=True)
    for group, symbols in MARKETS.items():
        for sym in symbols:
            for tf in TIMEFRAMES:
                candles = get_candles(sym, tf)
                if not candles:
                    time.sleep(1)
                    continue
                signal = check_crt(sym, tf, candles)
                if signal:
                    last = candles[-1]
                    key = f"{sym}_{tf}_{last['time']}_{signal}"
                    if already_sent(key):
                        print(f"Already sent {key}")
                        continue
                    emoji = "🟢" if signal == "BULLISH" else "🔴"
                    msg = f"{emoji} <b>CRT {signal} - {sym} {tf}</b>\n\nGroup: {group}\nPrice: {fmt(sym, last['close'])}\nHigh: {fmt(sym, last['high'])}\nLow: {fmt(sym, last['low'])}\nTime: {now}\n\nModel: Turtle Soup / CRT Sweep + Close Back Inside"
                    send_telegram(msg)
                    mark_sent(key)
                    print(f"ALERT {key}")
                time.sleep(1)
    print("--- Scan done, sleeping 15 min ---", flush=True)

if __name__ == "__main__":
    send_telegram("✅ <b>CRT Bot Started - 27 symbols</b>\nTimeframes: H4, D1, W1, MN1\nScanning every 15 mins...")
    while True:
        try:
            scan()
        except Exception as e:
            print("Scan error:", e)
        time.sleep(900)