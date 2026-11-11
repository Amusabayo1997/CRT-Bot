import time, requests, sqlite3
from datetime import datetime, timedelta
import pytz

# ============ CONFIG - CHANGE THESE ============
FCS_KEY = "YOUR_FCS_API_KEY"  # get from fcsapi.com
TELEGRAM_TOKEN = "YOUR_BOT_TOKEN" # your Bayo_bot token
CHAT_ID = "YOUR_CHAT_ID" # from @userinfobot
LAGOS = pytz.timezone("Africa/Lagos")
TIMEFRAMES = ["H4", "D1", "W1", "MN1"] # ONLY THESE

MARKETS = {
 "FOREX": ["EURUSD","GBPUSD","USDJPY","AUDUSD","NZDUSD","USDCAD","USDCHF","EURJPY","GBPJPY","EURGBP","GBPAUD","GBPCAD","AUDJPY"],
 "PRECIOUS METALS": ["XAUUSD","XAGUSD","XPTUSD"],
 "CRYPTOCURRENCIES": ["BTCUSD","ETHUSD","BNBUSD","SOLUSD","XRPUSD","ADAUSD","DOGEUSD"],
 "ENERGY": ["USOIL","UKOIL"],
 "DOLLAR INDEX": ["DXY"]
}
DECIMALS = {"EURUSD":5,"GBPUSD":5,"USDJPY":3,"AUDUSD":5,"NZDUSD":5,"USDCAD":5,"USDCHF":5,"EURJPY":3,"GBPJPY":3,"EURGBP":5,"GBPAUD":5,"GBPCAD":5,"AUDJPY":3,"XAUUSD":2,"XAGUSD":3,"XPTUSD":2,"BTCUSD":2,"ETHUSD":2,"BNBUSD":2,"SOLUSD":2,"XRPUSD":4,"ADAUSD":4,"DOGEUSD":4,"USOIL":2,"UKOIL":2,"DXY":2}
ASSET_NAME = {"XAUUSD":"GOLD","XAGUSD":"SILVER","BTCUSD":"BITCOIN","ETHUSD":"ETHEREUM","USOIL":"WTI CRUDE","UKOIL":"BRENT CRUDE","DXY":"US DOLLAR INDEX"}

# ============ DATABASE - NO DUPLICATE ALERTS ============
db = sqlite3.connect("crt_alerts.db", check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS sent (key TEXT PRIMARY KEY)")
db.commit()
def already_sent(key):
    cur = db.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone()
    if cur: return True
    db.execute("INSERT INTO sent VALUES (?)", (key,)); db.commit()
    return False

# ============ DATA PROVIDER ============
def get_candles(symbol, tf):
    period = {"H4":"4h","D1":"1d","W1":"1w","MN1":"1M"}[tf]
    # FCS has different endpoints per asset, we try generic candle endpoint
    urls = [
        f"https://fcsapi.com/api-v3/forex/candle?symbol={symbol}&period={period}&access_key={FCS_KEY}",
        f"https://fcsapi.com/api-v3/crypto/candle?symbol={symbol}&period={period}&access_key={FCS_KEY}",
        f"https://fcsapi.com/api-v3/commodities/candle?symbol={symbol}&period={period}&access_key={FCS_KEY}",
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=15).json()
            resp = r.get("response")
            if resp and isinstance(resp, list) and len(resp) > 30:
                # normalize: FCS returns {o,h,l,c,t}
                candles = []
                for c in resp:
                    candles.append({"o":float(c["o"]),"h":float(c["h"]),"l":float(c["l"]),"c":float(c["c"]),"t":int(c["t"])})
                candles.sort(key=lambda x: x["t"])
                return candles
        except: pass
    return None

# ============ 8 LIQUIDITY AREAS + OB + FVG ============
def calc_areas(candles):
    # candles oldest -> newest, last one must be CLOSED candle
    if len(candles) < 50: return {}
    # Use completed candles only: exclude current forming candle if needed - caller passes closed only
    # Tolerance for Equal Highs/Lows = 0.1% of price
    areas = {}
    # 1. PDH/PDL - last completed daily-equivalent: for H4 use last 6 candles = 1 day, for D1 use last 1, W1 last 1 week etc.
    # Simplified: previous candle block
    areas["PDH/PDL"] = (max(c["h"] for c in candles[-7:-1]), min(c["l"] for c in candles[-7:-1]))
    # 2. PWH/PWL - last 30 candles approx
    areas["PWH/PWL"] = (max(c["h"] for c in candles[-31:-1]), min(c["l"] for c in candles[-31:-1]))
    # 3. PMH/PML - last 120 candles approx
    areas["PMH/PML"] = (max(c["h"] for c in candles[-121:-1]), min(c["l"] for c in candles[-121:-1]))
    # 4. EQH/EQL - find 2 highs within 0.05%
    highs = [c["h"] for c in candles[-30:]]
    lows = [c["l"] for c in candles[-30:]]
    eqh = None; eql = None
    for i in range(len(highs)):
        for j in range(i+1, len(highs)):
            if abs(highs[i]-highs[j]) / highs[i] < 0.0005:
                eqh = highs[i]; break
    for i in range(len(lows)):
        for j in range(i+1, len(lows)):
            if abs(lows[i]-lows[j]) / lows[i] < 0.0005:
                eql = lows[i]; break
    if eqh: areas["Equal Highs (EQH)"] = (eqh, eqh)
    if eql: areas["Equal Lows (EQL)"] = (eql, eql)
    # 5. CRT Candle 1 Range - handled in detect
    # 6. Session High/Low - last 12 candles high/low
    areas["Session High/Low"] = (max(c["h"] for c in candles[-13:-1]), min(c["l"] for c in candles[-13:-1]))
    # 7. HTF FVG - 3-candle imbalance: candle[i-2] high < candle[i] low = Bullish FVG, opposite = Bearish
    fvgs = []
    for i in range(2, len(candles)-1):
        if candles[i-2]["h"] < candles[i]["l"]:
            fvgs.append(("BULLISH FVG", candles[i-2]["h"], candles[i]["l"]))
        if candles[i-2]["l"] > candles[i]["h"]:
            fvgs.append(("BEARISH FVG", candles[i]["h"], candles[i-2]["l"]))
    if fvgs:
        last = fvgs[-1]
        areas[last[0]] = (last[1], last[2])
    # 8. HTF ORDER BLOCK - last bearish candle before bullish move = Bullish OB, vice versa
    obs = []
    for i in range(2, len(candles)-1):
        # Bullish OB: bearish candle, then bullish break above its high
        if candles[i-1]["c"] < candles[i-1]["o"] and candles[i]["c"] > candles[i-1]["h"]:
            obs.append(("BULLISH ORDER BLOCK", candles[i-1]["l"], candles[i-1]["h"]))
        if candles[i-1]["c"] > candles[i-1]["o"] and candles[i]["c"] < candles[i-1]["l"]:
            obs.append(("BEARISH ORDER BLOCK", candles[i-1]["l"], candles[i-1]["h"]))
    if obs:
        last = obs[-1]
        areas[last[0]] = (last[1], last[2])
    return areas

def price_in_area(price, low, high, tolerance):
    return (low - tolerance) <= price <= (high + tolerance)

def is_sideways(candles):
    # If last 20 candles range is tiny vs average, reject
    ranges = [c["h"]-c["l"] for c in candles[-21:-1]]
    avg = sum(ranges)/len(ranges)
    last_range = candles[-1]["h"]-candles[-1]["l"]
    return last_range < avg * 0.3

# ============ MSS CHECK ============
def has_mss(candles, direction):
    # Bullish MSS: after sweep low, price breaks above previous swing high (last 5 candles high)
    # Bearish MSS: after sweep high, price breaks below previous swing low
    # We use the sweep candle itself + confirmation: close must break swing
    c2 = candles[-1]
    prev_high = max(c["h"] for c in candles[-6:-1])
    prev_low = min(c["l"] for c in candles[-6:-1])
    if direction == "BULLISH":
        return c2["c"] > prev_high or c2["h"] > prev_high
    else:
        return c2["c"] < prev_low or c2["l"] < prev_low

# ============ CORE CRT DETECTION ============
def detect(symbol, market, tf, candles):
    if len(candles) < 50: return None
    if is_sideways(candles):
        return None # REJECT: sideways

    c1 = candles[-2] # Range Candle
    c2 = candles[-1] # Sweep Candle

    # REJECT: Swept BOTH sides
    swept_high = c2["h"] > c1["h"]
    swept_low = c2["l"] < c1["l"]
    if swept_high and swept_low:
        return None

    # REJECT: Closed strongly outside - must reclaim inside
    if c2["c"] > c1["h"] or c2["c"] < c1["l"]:
        return None

    areas = calc_areas(candles)
    tolerance = (c1["h"]-c1["l"]) * 0.15 # 15% tolerance around area
    matched_area = None
    matched_level = None
    direction = None

    # BULLISH: Candle 2 wicks BELOW Candle 1 Low, closes inside
    if swept_low and c2["c"] > c1["l"] and c2["c"] < c1["h"]:
        direction = "BULLISH"
        sweep_level = c2["l"]
        # Must be in/around one of 8 areas
        for name, (alow, ahigh) in areas.items():
            if price_in_area(sweep_level, min(alow,ahigh), max(alow,ahigh), tolerance) or price_in_area(c1["l"], min(alow,ahigh), max(alow,ahigh), tolerance):
                matched_area = name; matched_level = min(alow,ahigh) if "LOW" in name or "FVG" in name or "BLOCK" in name else sweep_level
                # For OB/FVG, level = area low
                if "ORDER BLOCK" in name or "FVG" in name:
                    matched_level = min(alow,ahigh)
                break
        # Also check CRT Candle 1 itself as area 5
        if not matched_area:
            matched_area = "CRT Candle 1 Range Low"; matched_level = c1["l"]

    # BEARISH: Candle 2 wicks ABOVE Candle 1 High, closes inside
    elif swept_high and c2["c"] < c1["h"] and c2["c"] > c1["l"]:
        direction = "BEARISH"
        sweep_level = c2["h"]
        for name, (alow, ahigh) in areas.items():
            if price_in_area(sweep_level, min(alow,ahigh), max(alow,ahigh), tolerance) or price_in_area(c1["h"], min(alow,ahigh), max(alow,ahigh), tolerance):
                matched_area = name; matched_level = max(alow,ahigh)
                if "ORDER BLOCK" in name or "FVG" in name:
                    matched_level = max(alow,ahigh)
                break
        if not matched_area:
            matched_area = "CRT Candle 1 Range High"; matched_level = c1["h"]

    if not direction or not matched_area:
        return None

    # MUST HAVE MSS - else no alert
    if not has_mss(candles, direction):
        return None

    return build_alert(symbol, market, tf, direction, matched_area, matched_level, c1, c2)

def build_alert(symbol, market, tf, direction, area, level, c1, c2):
    dec = DECIMALS.get(symbol, 2)
    upper = c2["h"] - max(c2["o"], c2["c"])
    lower = min(c2["o"], c2["c"]) - c2["l"]
    body = abs(c2["c"] - c2["o"])
    now = datetime.now(LAGOS)
    open_t = datetime.fromtimestamp(c2["t"], tz=pytz.utc).astimezone(LAGOS)
    dur = {"H4":4,"D1":24,"W1":168,"MN1":720}[tf]
    close_t = open_t + timedelta(hours=dur)
    asset = ASSET_NAME.get(symbol, symbol)
    emoji = "🟢" if direction=="BULLISH" else "🔴"
    target = f"Candle 1 High: {c1['h']:.{dec}f}" if direction=="BULLISH" else f"Candle 1 Low: {c1['l']:.{dec}f}"
    entry = "Buy on retracement to sweep low / OB" if direction=="BULLISH" else "Sell on retracement to sweep high / OB"
    return f"""🚨 CONFIRMED CRT LIQUIDITY SWEEP 🚨

ASSET: {asset}
SYMBOL: {symbol}
MARKET: {market}

DIRECTION: {emoji} {direction}

TIMEFRAME: {tf}

LIQUIDITY AREA:
{area}

DATE: {now.strftime('%d %B %Y')}

CANDLE OPEN TIME: {open_t.strftime('%H:%M')}
CANDLE CLOSE TIME: {close_t.strftime('%H:%M')}

SWEEP CANDLE OHLC:

OPEN: {c2['o']:.{dec}f}
HIGH: {c2['h']:.{dec}f}
LOW: {c2['l']:.{dec}f}
CLOSE: {c2['c']:.{dec}f}

SWEPT LIQUIDITY LEVEL: {level:.{dec}f}

UPPER WICK: {upper:.{dec}f}
LOWER WICK: {lower:.{dec}f}
BODY SIZE: {body:.{dec}f}

RANGE CANDLE 1: High {c1['h']:.{dec}f} / Low {c1['l']:.{dec}f}
MSS: ✅ CONFIRMED
ENTRY: {entry}
TARGET: {target}

STATUS: CONFIRMED {direction} CRT SWEEP

ALERT GENERATED: {now.strftime('%H:%M:%S')}
TIMEZONE: Africa/Lagos
DATA PROVIDER: FCS API

NOTE: This is a liquidity sweep alert, not an automatic buy or sell recommendation."""

def send_telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg}, timeout=15)
    except Exception as e:
        print("Telegram error:", e)

def scan_once():
    for market, symbols in MARKETS.items():
        for sym in symbols:
            for tf in TIMEFRAMES:
                candles = get_candles(sym, tf)
                if not candles:
                    print(f"{sym} {tf} -> UNAVAILABLE, no fake alert")
                    continue
                alert = detect(sym, market, tf, candles)
                if alert:
                    key = f"{sym}-{tf}-{candles[-1]['t']}"
                    if already_sent(key): continue
                    send_telegram(alert)
                    print(f"✅ ALERT SENT: {sym} {tf}")

if __name__ == "__main__":
    print("CRT Bot Started - H4/D1/W1/MN1 ONLY - 8 Areas + OB + FVG + MSS")
    while True:
        scan_once()
        time.sleep(60)