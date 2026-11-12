import os
import time
import requests
import datetime
import calendar

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TWELVE_KEY = os.getenv("TWELVE_KEY")

SYMBOLS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "NZD/USD", "USD/CAD",
    "EUR/GBP", "EUR/JPY", "EUR/CHF", "EUR/AUD", "EUR/CAD", "EUR/NZD",
    "GBP/JPY", "GBP/CHF", "GBP/AUD", "GBP/CAD", "GBP/NZD",
    "AUD/JPY", "AUD/CHF", "AUD/CAD", "AUD/NZD",
    "CAD/JPY", "CAD/CHF", "NZD/JPY", "NZD/CHF", "NZD/CAD", "CHF/JPY",
    "XAU/USD", "XAG/USD", "BTC/USD", "ETH/USD",
]

TIMEFRAMES = ["4h", "1day", "1week", "1month"]
TF_LABEL = {"4h": "H4", "1day": "D1", "1week": "W1", "1month": "MN1"}

# HTF MAP: Which higher TF go confirm which TF
HTF_MAP = {
    "4h": "1day",    # H4 must align with D1
    "1day": "1week", # D1 must align with W1
    "1week": "1month", # W1 must align with MN1
    "1month": None,  # MN1 na king, no higher TF
}

SENT = set()

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("No Telegram token/chat")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg}, timeout=10)
        print("Telegram sent")
    except Exception as e:
        print("Telegram error:", e)

def get_candles(symbol, interval):
    try:
        url = "https://api.twelvedata.com/time_series"
        params = {"symbol": symbol, "interval": interval, "outputsize": 100, "apikey": TWELVE_KEY, "format": "JSON"}
        r = requests.get(url, params=params, timeout=20)
        data = r.json()
        if "values" not in data:
            print(f"No data {symbol} {interval}: {data.get('message','')[:100]}")
            return []
        candles = list(reversed(data["values"]))
        out = []
        for c in candles:
            out.append({"time": c["datetime"], "open": float(c["open"]), "high": float(c["high"]), "low": float(c["low"]), "close": float(c["close"])})
        return out
    except Exception as e:
        print(f"Fetch error {symbol} {interval}: {e}")
        return []

def get_close_time(sweep_time_str, interval):
    # TwelveData na UTC. Lagos na WAT = UTC+1
    try:
        try:
            dt = datetime.datetime.strptime(sweep_time_str, "%Y-%m-%d %H:%M:%S")
        except:
            dt = datetime.datetime.strptime(sweep_time_str, "%Y-%m-%d")
        if interval == "4h":
            close_utc = dt + datetime.timedelta(hours=4)
            close_wat = close_utc + datetime.timedelta(hours=1)
            return close_wat.strftime("%Y-%m-%d %H:%M") + " WAT"
        if interval == "1day":
            close_utc = dt + datetime.timedelta(days=1)
            close_wat = close_utc + datetime.timedelta(hours=1)
            return close_wat.strftime("%Y-%m-%d %H:%M") + " WAT"
        if interval == "1week":
            close_utc = dt + datetime.timedelta(days=7)
            close_wat = close_utc + datetime.timedelta(hours=1)
            return close_wat.strftime("%Y-%m-%d %H:%M") + " WAT"
        if interval == "1month":
            last_day = calendar.monthrange(dt.year, dt.month)[1]
            return f"{dt.year}-{dt.month:02d}-{last_day:02d} 23:59 WAT"
        return sweep_time_str
    except:
        return sweep_time_str

def get_htf_bias(htf_candles):
    # HTF BIAS: Last CLOSED candle close vs SMA 20
    # If price > SMA 20 -> BULLISH bias, if < -> BEARISH bias
    # We ignore last candle because e still open
    if len(htf_candles) < 22:
        return None  # Not enough data, we go allow signal (no filter)
    closed = htf_candles[:-1]  # Remove open candle
    last_close = closed[-1]["close"]
    # SMA 20 of last 20 closed candles
    sma20 = sum(c["close"] for c in closed[-20:]) / 20
    # Extra check: also compare with 10 candles ago to avoid flat market
    close_10_ago = closed[-11]["close"] if len(closed) >= 11 else last_close
    if last_close > sma20 and last_close >= close_10_ago:
        return "BULLISH"
    if last_close < sma20 and last_close <= close_10_ago:
        return "BEARISH"
    # If price dey near SMA but still above/below, use SMA only
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
    key = f"{symbol}-{interval}-{sweep['time']}"
    if key in SENT:
        return None

    signal = None
    direction = None
    if sweep["low"] < ref_low and sweep["close"] > ref_low and sweep["close"] < ref_high:
        direction = "BULLISH"
        ok, aoi = check_aoi(candles, ref, sweep, direction.lower(),)
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

    # --- HTF BIAS FILTER ---
    htf_interval = HTF_MAP.get(interval)
    if htf_interval and htf_candles:
        htf_bias = get_htf_bias(htf_candles)
        # If HTF bias dey and e no align with signal, REJECT
        if htf_bias and htf_bias != direction:
            print(f"HTF REJECT: {symbol} {interval} {direction} vs HTF {htf_interval} {htf_bias}")
            return None
        # Save HTF bias to show for signal
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
    print(f"--- Scan started {datetime.datetime.now()} ---")
    for symbol in SYMBOLS:
        clean = symbol.replace("/", "")
        # Fetch ALL timeframes once per symbol - so we fit reuse for HTF check, no extra API call
        all_candles = {}
        for interval in TIMEFRAMES:
            all_candles[interval] = get_candles(symbol, interval)
            time.sleep(8)  # TwelveData limit

        for interval in TIMEFRAMES:
            candles = all_candles.get(interval, [])
            if not candles:
                continue
            htf_interval = HTF_MAP.get(interval)
            htf_candles = all_candles.get(htf_interval) if htf_interval else None
            result = check_crt(symbol, interval, candles, htf_candles)
            if result:
                tf = TF_LABEL[interval]
                close_time = get_close_time(result['sweep']['time'], interval)
                msg = (
                    f"{result['emoji']} CRT {result['type']} - {clean} {tf}\n"
                    f"Price: {result['sweep']['close']:.5f}\n"
                    f"Ref High: {result['ref']['high']:.5f}\n"
                    f"Ref Low: {result['ref']['low']:.5f}\n"
                    f"50% Eq: {result['mid']:.5f}\n"
                    f"Sweep High: {result['sweep']['high']:.5f}\n"
                    f"Sweep Low: {result['sweep']['low']:.5f}\n"
                    f"Sweep Close: {result['sweep']['close']:.5f}\n"
                    f"AOI: {result['aoi']}\n"
                    f"HTF Bias: {result.get('htf_tf','')} {result.get('htf_bias','')} ✅ Aligned\n"
                    f"Sweep Candle Open: {result['sweep']['time']}\n"
                    f"Sweep Candle Closed: {close_time}\n"
                    f"Ref Candle: {result['ref']['time']}"
                )
                send_telegram(msg)
                print(f"Signal: {clean} {tf} {result['type']} AOI:{result['aoi']} HTF:{result.get('htf_bias')}")

if __name__ == "__main__":
    send_telegram("✅ CRT Bot Started - V3 HTF Bias\nMajors + Minors + XAU XAG BTC ETH\nH4->D1 | D1->W1 | W1->MN1 | Closed Candle Only | AOI Only | Time in WAT")
    while True:
        try:
            scan()
        except Exception as e:
            print("Scan error:", e)
        time.sleep(300)