import os
import time
import requests
import datetime
import calendar
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TWELVE_KEY = os.getenv("TWELVE_KEY")
def run_dummy_server():
    port = int(os.getenv("PORT", 10000))
    print("Starting dummy server on port " + str(port), flush=True)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"CRT Bot Running")
        def log_message(self, format, *args):
            return
    try:
        HTTPServer.allow_reuse_address = True
        HTTPServer(("0.0.0.0", port), Handler).serve_forever()
    except Exception as e:
        print("Dummy server error: " + str(e), flush=True)
threading.Thread(target=run_dummy_server, daemon=True).start()
print("Dummy server thread started", flush=True)
SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "NZD/USD", "USD/CAD", "EUR/GBP", "EUR/JPY", "EUR/CHF", "EUR/AUD", "EUR/CAD", "EUR/NZD", "GBP/JPY", "GBP/CHF", "GBP/AUD", "GBP/CAD", "GBP/NZD", "AUD/JPY", "AUD/CHF", "AUD/CAD", "AUD/NZD", "CAD/JPY", "CAD/CHF", "NZD/JPY", "NZD/CHF", "NZD/CAD", "CHF/JPY", "XAU/USD", "XAG/USD", "BTC/USD", "ETH/USD"]
TIMEFRAMES = ["4h", "1day", "1week", "1month"]
TF_LABEL = {"4h": "H4", "1day": "D1", "1week": "W1", "1month": "MN1"}
HTF_MAP = {"4h": "1day", "1day": "1week", "1week": "1month", "1month": None}
SENT = set()
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("No Telegram token/chat", flush=True)
        return
    try:
        url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg}, timeout=10)
        print("Telegram sent", flush=True)
    except Exception as e:
        print("Telegram error: " + str(e), flush=True)
def get_candles(symbol, interval):
    try:
        url = "https://api.twelvedata.com/time_series"
        params = {"symbol": symbol, "interval": interval, "outputsize": 100, "apikey": TWELVE_KEY, "format": "JSON"}
        r = requests.get(url, params=params, timeout=20)
        data = r.json()
        if "values" not in data:
            err_msg = str(data.get("message", ""))
            print("No data " + symbol + " " + interval + ": " + err_msg[:100], flush=True)
            return []
        candles = list(reversed(data["values"]))
        out = []
        for c in candles:
            out.append({"time": c["datetime"], "open": float(c["open"]), "high": float(c["high"]), "low": float(c["low"]), "close": float(c["close"])})
        return out
    except Exception as e:
        print("Fetch error " + symbol + " " + interval + ": " + str(e), flush=True)
        return []
def get_close_time(sweep_time_str, interval):
    try:
        try:
            dt = datetime.datetime.strptime(sweep_time_str, "%Y-%m-%d %H:%M:%S")
        except:
            dt = datetime.datetime.strptime(sweep_time_str, "%Y-%m-%d")
        if interval == "4h":
            close_wat = dt + datetime.timedelta(hours=4) + datetime.timedelta(hours=1)
            return close_wat.strftime("%Y-%m-%d %H:%M") + " WAT"
        if interval == "1day":
            close_wat = dt + datetime.timedelta(days=1) + datetime.timedelta(hours=1)
            return close_wat.strftime("%Y-%m-%d %H:%M") + " WAT"
        if interval == "1week":
            close_wat = dt + datetime.timedelta(days=7) + datetime.timedelta(hours=1)
            return close_wat.strftime("%Y-%m-%d %H:%M") + " WAT"
        if interval == "1month":
            last_day = calendar.monthrange(dt.year, dt.month)[1]
            return str(dt.year) + "-" + str(dt.month).zfill(2) + "-" + str(last_day).zfill(2) + " 23:59 WAT"
        return sweep_time_str
    except:
        return sweep_time_str
def get_htf_bias(htf_candles):
    if len(htf_candles) < 22:
        return None
    closed = htf_candles[:-1]
    last_close = closed[-1]["close"]
    sma20 = sum(c["close"] for c in closed[-20:]) / 20
    close_10_ago = closed[-11]["close"] if len(closed) >= 11 else last_close
    if last_close > sma20 and last_close >= close_10_ago:
        return "BULLISH"
    if last_close < sma20 and last_close <= close_10_ago:
        return "BEARISH"
    if last_close > sma20:
        return "BULLISH"
    if last_close < sma20:
        return "BEARISH"
    return None
def is_close_enough(a, b, atr):
    return abs(a - b) <= max(atr * 0.2, 1e-9)
def check_aoi(candles, ref, sweep, direction):
    if len(candles) < 30:
        return False, ""
    hist = candles[:-3]
    sweep_level = sweep["low"] if direction == "bullish" else sweep["high"]
    ranges = [c["high"] - c["low"] for c in hist[-20:]]
    atr = sum(ranges) / len(ranges) if ranges else 0.0001
    if len(hist) >= 20:
        recent_high = max(c["high"] for c in hist[-5:])
        recent_low = min(c["low"] for c in hist[-5:])
        prev_high = max(c["high"] for c in hist[-20:-5])
        prev_low = min(c["low"] for c in hist[-20:-5])
        if direction == "bullish":
            if is_close_enough(sweep_level, prev_low, atr) or is_close_enough(sweep_level, recent_low, atr):
                return True, "Prev Daily/Weekly Low"
        else:
            if is_close_enough(sweep_level, prev_high, atr) or is_close_enough(sweep_level, recent_high, atr):
                return True, "Prev Daily/Weekly High"
    count = 0
    for c in hist[-30:]:
        if direction == "bullish" and is_close_enough(sweep_level, c["low"], atr):
            count += 1
        if direction == "bearish" and is_close_enough(sweep_level, c["high"], atr):
            count += 1
    if count >= 2:
        return True, "Support" if direction == "bullish" else "Resistance"
    for i in range(len(hist)-1):
        if direction == "bullish":
            if is_close_enough(hist[i]["low"], hist[i+1]["low"], atr) and is_close_enough(sweep_level, hist[i]["low"], atr):
                return True, "Equal Lows"
        else:
            if is_close_enough(hist[i]["high"], hist[i+1]["high"], atr) and is_close_enough(sweep_level, hist[i]["high"], atr):
                return True, "Equal Highs"
    for i in range(1, len(hist)-1):
        if direction == "bullish":
            gap_low = hist[i-1]["high"]
            gap_high = hist[i+1]["low"]
            if gap_high > gap_low and gap_low <= sweep_level <= gap_high:
                return True, "FVG"
        else:
            gap_high = hist[i-1]["low"]
            gap_low = hist[i+1]["high"]
            if gap_low < gap_high and gap_low <= sweep_level <= gap_high:
                return True, "FVG"
    for i in range(len(hist)-1):
        c = hist[i]
        nxt = hist[i+1]
        move = abs(nxt["close"] - nxt["open"])
        if move > atr * 0.8:
            if direction == "bullish" and is_close_enough(sweep_level, c["low"], atr):
                return True, "Order Block"
            if direction == "bearish" and is_close_enough(sweep_level, c["high"], atr):
                return True, "Order Block"
    return False, ""
def check_crt(symbol, interval, candles, htf_candles=None):
    if len(candles) < 5:
        return None
    ref = candles[-3]
    sweep = candles[-2]
    ref_high = ref["high"]
    ref_low = ref["low"]
    mid = (ref_high + ref_low) / 2
    sweep_time = sweep["time"]
    key = symbol + "-" + interval + "-" + str(sweep_time)
    if key in SENT:
        return None
    signal = None
    direction = None
    if sweep["low"] < ref_low and sweep["close"] > ref_low and sweep["close"] < ref_high:
        direction = "BULLISH"
        ok, aoi = check_aoi(candles, ref, sweep, direction.lower())
        if not ok:
            return None
        signal = {"type": "BULLISH", "emoji": "🟢", "aoi": aoi, "ref": ref, "sweep": sweep, "mid": mid}
    elif sweep["high"] > ref_high and sweep["close"] < ref_high and sweep["close"] > ref_low:
        direction = "BEARISH"
        ok, aoi = check_aoi(candles, ref, sweep, direction.lower())
        if not ok:
            return None
        signal = {"type": "BEARISH", "emoji": "🔴", "aoi": aoi, "ref": ref, "sweep": sweep, "mid": mid}
    else:
        return None
    htf_interval = HTF_MAP.get(interval)
    if htf_interval and htf_candles:
        htf_bias = get_htf_bias(htf_candles)
        if htf_bias and htf_bias != direction:
            print("HTF REJECT: " + symbol + " " + interval + " " + direction + " vs HTF " + htf_interval + " " + str(htf_bias), flush=True)
            return None
        signal["htf_bias"] = htf_bias
        signal["htf_tf"] = TF_LABEL[htf_interval]
    else:
        signal["htf_bias"] = "N/A (King)"
        signal["htf_tf"] = "MN1"
    if signal:
        SENT.add(key)
        return signal
    return None
def scan():
    print("--- Scan started " + str(datetime.datetime.now()) + " ---", flush=True)
    for symbol in SYMBOLS:
        clean = symbol.replace("/", "")
        all_candles = {}
        for interval in TIMEFRAMES:
            all_candles[interval] = get_candles(symbol, interval)
            time.sleep(8)
        for interval in TIMEFRAMES:
            candles = all_candles.get(interval, [])
            if not candles:
                continue
            htf_interval = HTF_MAP.get(interval)
            htf_candles = all_candles.get(htf_interval) if htf_interval else None
            result = check_crt(symbol, interval, candles, htf_candles)
            if result:
                emoji = result.get("emoji", "")
                typ = result.get("type", "")
                tf2 = TF_LABEL[interval]
                sweep_time2 = result["sweep"]["time"]
                close_time = get_close_time(sweep_time2, interval)
                msg = emoji + " CRT " + typ + " - " + clean + " " + tf2 + "\n"
                msg += "Price: " + str(round(result["sweep"]["close"], 5)) + "\n"
                msg += "Ref High: " + str(round(result["ref"]["high"], 5)) + "\n"
                msg += "Ref Low: " + str(round(result["ref"]["low"], 5)) + "\n"
                msg += "50% Eq: " + str(round(result["mid"], 5)) + "\n"
                msg += "Sweep High: " + str(round(result["sweep"]["high"], 5)) + "\n"
                msg += "Sweep Low: " + str(round(result["sweep"]["low"], 5)) + "\n"
                msg += "Sweep Close: " + str(round(result["sweep"]["close"], 5)) + "\n"
                msg += "AOI: " + str(result["aoi"]) + "\n"
                msg += "HTF Bias: " + str(result.get("htf_tf", "")) + " " + str(result.get("htf_bias", "")) + " Aligned\n"
                msg += "Sweep Candle Open: " + str(sweep_time2) + "\n"
                msg += "Sweep Candle Closed: " + str(close_time) + "\n"
                msg += "Ref Candle: " + str(result["ref"]["time"])
                send_telegram(msg)
                print("Signal: " + clean + " " + tf2 + " " + typ + " AOI:" + str(result["aoi"]) + " HTF:" + str(result.get("htf_bias")), flush=True)
if __name__ == "__main__":
    send_telegram("✅ CRT Bot Started - V3.1 HTF Bias | 15min Scan | Free Web Service")
    while True:
        try:
            scan()
        except Exception as e:
            print("Scan error: " + str(e), flush=True)
        time.sleep(900)