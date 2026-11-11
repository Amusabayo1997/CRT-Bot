import time, requests, sqlite3, os
from datetime import datetime, timedelta
import pytz

# ============ KEYS - PUT FOR RENDER ENV, NOT INSIDE CODE ============
TWELVE_KEY = os.getenv("TWELVE_KEY", "PASTE_TWELVE_KEY_HERE")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "PASTE_BOT_TOKEN_HERE")
CHAT_ID = os.getenv("CHAT_ID", "PASTE_CHAT_ID_HERE")
LAGOS = pytz.timezone("Africa/Lagos")
TIMEFRAMES = ["H4", "D1", "W1", "MN1"] # ONLY THESE

# ============ 27 SYMBOLS - FULL ============
MARKETS = {
 "FOREX": ["EURUSD","GBPUSD","USDJPY","AUDUSD","NZDUSD","USDCAD","USDCHF","EURJPY","GBPJPY","EURGBP","GBPAUD","GBPCAD","AUDJPY"],
 "PRECIOUS METALS": ["XAUUSD","XAGUSD","XPTUSD"],
 "CRYPTOCURRENCIES": ["BTCUSD","ETHUSD","BNBUSD","SOLUSD","XRPUSD","ADAUSD","DOGEUSD"],
 "ENERGY": ["USOIL","UKOIL"],
 "DOLLAR INDEX": ["DXY"]
}
DECIMALS = {"EURUSD":5,"GBPUSD":5,"USDJPY":3,"AUDUSD":5,"NZDUSD":5,"USDCAD":5,"USDCHF":5,"EURJPY":3,"GBPJPY":3,"EURGBP":5,"GBPAUD":5,"GBPCAD":5,"AUDJPY":3,"XAUUSD":2,"XAGUSD":3,"XPTUSD":2,"BTCUSD":2,"ETHUSD":2,"BNBUSD":2,"SOLUSD":2,"XRPUSD":4,"ADAUSD":4,"DOGEUSD":4,"USOIL":2,"UKOIL":2,"DXY":2}
ASSET_NAME = {"XAUUSD":"GOLD","XAGUSD":"SILVER","XPTUSD":"PLATINUM","BTCUSD":"BITCOIN","ETHUSD":"ETHEREUM","BNBUSD":"BNB","SOLUSD":"SOLANA","XRPUSD":"XRP","ADAUSD":"CARDANO","DOGEUSD":"DOGECOIN","USOIL":"WTI CRUDE","UKOIL":"BRENT CRUDE","DXY":"US DOLLAR INDEX"}

# Twelve Data symbol mapping: EURUSD -> EUR/USD, XAUUSD -> XAU/USD, USOIL -> WTI/USD
def to_twelve(symbol):
    m = {"USOIL":"WTI/USD","UKOIL":"BRENT/USD","XPTUSD":"XPT/USD","DXY":"DXY"}
    if symbol in m: return m[symbol]
    if symbol in ["XAUUSD","XAGUSD"]: return symbol[:3]+"/"+symbol[3:]
    return symbol[:3]+"/"+symbol[3:]  # EURUSD -> EUR/USD

# Binance mapping: BTCUSD -> BTCUSDT, ETHUSD -> ETHUSDT
def to_binance(symbol):
    return symbol.replace("USD","USDT")

# ============ NO DUPLICATE ALERTS ============
db = sqlite3.connect("crt_alerts.db", check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS sent (key TEXT PRIMARY KEY)")
db.commit()
def already_sent(key):
    cur = db.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone()
    if cur: return True
    db.execute("INSERT INTO sent VALUES (?)", (key,)); db.commit()
    return False

# ============ DATA PROVIDERS ============
# 1. Twelve Data for Forex / Metals / Energy / DXY - 800 calls/day free
def get_twelve_candles(symbol, tf):
    interval = {"H4":"4h","D1":"1day","W1":"1week","MN1":"1month"}[tf]
    td_sym = to_twelve(symbol)
    url = f"https://api.twelvedata.com/time_series?symbol={td_sym}&interval={interval}&outputsize=150&apikey={TWELVE_KEY}&timezone=UTC"
    try:
        r = requests.get(url, timeout=20).json()
        if "values" not in r: 
            print(f"{symbol} {tf} Twelve Data error: {r.get('message','no data')}")
            return None
        candles = []
        for v in r["values"]:
            dt = datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.utc)
            candles.append({"o":float(v["open"]),"h":float(v["high"]),"l":float(v["low"]),"c":float(v["close"]),"t":int(dt.timestamp())})
        candles.sort(key=lambda x: x["t"])
        return candles
    except Exception as e:
        print(f"{symbol} Twelve error {e}")
        return None

# 2. Binance for Crypto - FREE, no limit
def get_binance_candles(symbol, tf):
    interval = {"H4":"4h","D1":"1d","W1":"1w","MN1":"1M"}[tf]
    b_sym = to_binance(symbol)
    url = f"https://api.binance.com/api/v3/klines?symbol={b_sym}&interval={interval}&limit=150"
    try:
        r = requests.get(url, timeout=20).json()
        if not isinstance(r, list): return None
        candles = []
        for k in r:
            candles.append({"o":float(k[1]),"h":float(k[2]),"l":float(k[3]),"c":float(k[4]),"t":int(k[0]//1000)})
        return candles
    except Exception as e:
        print(f"{symbol} Binance error {e}")
        return None

def get_candles(symbol, market, tf):
    if market == "CRYPTOCURRENCIES":
        return get_binance_candles(symbol, tf)
    else:
        return get_twelve_candles(symbol, tf)

# ============ 8 AREAS + OB + FVG ============
def calc_areas(candles):
    if len(candles) < 50: return {}
    areas = {}
    areas["Previous Day High/Low (PDH/PDL)"] = (max(c["h"] for c in candles[-7:-1]), min(c["l"] for c in candles[-7:-1]))
    areas["Previous Week High/Low (PWH/PWL)"] = (max(c["h"] for c in candles[-31:-1]), min(c["l"] for c in candles[-31:-1]))
    areas["Previous Month High/Low (PMH/PML)"] = (max(c["h"] for c in candles[-121:-1]), min(c["l"] for c in candles[-121:-1]))
    areas["Session High/Low"] = (max(c["h"] for c in candles[-13:-1]), min(c["l"] for c in candles[-13:-1]))
    # Equal Highs / Lows - 2 highs within 0.05%
    highs = [c["h"] for c in candles[-30:]]
    lows = [c["l"] for c in candles[-30:]]
    for i in range(len(highs)):
        for j in range(i+1, len(highs)):
            if abs(highs[i]-highs[j])/highs[i] < 0.0005:
                areas["Equal Highs (EQH)"] = (highs[i], highs[i]); break
    for i in range(len(lows)):
        for j in range(i+1, len(lows)):
            if abs(lows[i]-lows[j])/lows[i] < 0.0005:
                areas["Equal Lows (EQL)"] = (lows[i], lows[i]); break
    # HTF FVG
    fvgs = []
    for i in range(2, len(candles)-1):
        if candles[i-2]["h"] < candles[i]["l"]:
            fvgs.append(("BULLISH FVG", candles[i-2]["h"], candles[i]["l"]))
        if candles[i-2]["l"] > candles[i]["h"]:
            fvgs.append(("BEARISH FVG", candles[i]["h"], candles[i-2]["l"]))
    if fvgs:
        last = fvgs[-1]; areas[last[0]] = (last[1], last[2])
    # HTF ORDER BLOCK
    obs = []
    for i in range(2, len(candles)-1):
        if candles[i-1]["c"] < candles[i-1]["o"] and candles[i]["c"] > candles[i-1]["h"]:
            obs.append(("BULLISH ORDER BLOCK", candles[i-1]["l"], candles[i-1]["h"]))
        if candles[i-1]["c"] > candles[i-1]["o"] and candles[i]["c"] < candles[i-1]["l"]:
            obs.append(("BEARISH ORDER BLOCK", candles[i-1]["l"], candles[i-1]["h"]))
    if obs:
        last = obs[-1]; areas[last[0]] = (last[1], last[2])
    return areas

def price_in_area(price, low, high, tol):
    return (low - tol) <= price <= (high + tol)
def is_sideways(candles):
    ranges = [c["h"]-c["l"] for c in candles[-21:-1]]
    avg = sum(ranges)/len(ranges)
    return (candles[-1]["h"]-candles[-1]["l"]) < avg * 0.3
def has_mss(candles, direction):
    c2 = candles[-1]
    prev_high = max(c["h"] for c in candles[-6:-1])
    prev_low = min(c["l"] for c in candles[-6:-1])
    if direction == "BULLISH":
        return c2["c"] > prev_high or c2["h"] > prev_high
    else:
        return c2["c"] < prev_low or c2["l"] < prev_low

# ============ CORE CRT ============
def detect(symbol, market, tf, candles):
    if len(candles) < 50: return None
    if is_sideways(candles): return None # REJECT sideways
    c1 = candles[-2]; c2 = candles[-1]
    swept_high = c2["h"] > c1["h"]
    swept_low = c2["l"] < c1["l"]
    if swept_high and swept_low: return None # REJECT both sides
    if c2["c"] > c1["h"] or c2["c"] < c1["l"]: return None # REJECT close outside
    areas = calc_areas(candles)
    tol = (c1["h"]-c1["l"]) * 0.15
    direction = None; matched_area = None; matched_level = None
    # BULLISH: wick below Candle1 Low, close inside
    if swept_low and c2["c"] > c1["l"] and c2["c"] < c1["h"]:
        direction = "BULLISH"; sweep_level = c2["l"]
        for name, (alow, ahigh) in areas.items():
            if price_in_area(sweep_level, min(alow,ahigh), max(alow,ahigh), tol) or price_in_area(c1["l"], min(alow,ahigh), max(alow,ahigh), tol):
                matched_area = name; matched_level = min(alow,ahigh); break
        if not matched_area:
            matched_area = "CRT Candle 1 Range Low"; matched_level = c1["l"]
    # BEARISH: wick above Candle1 High, close inside
    elif swept_high and c2["c"] < c1["h"] and c2["c"] > c1["l"]:
        direction = "BEARISH"; sweep_level = c2["h"]
        for name, (alow, ahigh) in areas.items():
            if price_in_area(sweep_level, min(alow,ahigh), max(alow,ahigh), tol) or price_in_area(c1["h"], min(alow,ahigh), max(alow,ahigh), tol):
                matched_area = name; matched_level = max(alow,ahigh); break
        if not matched_area:
            matched_area = "CRT Candle 1 Range High"; matched_level = c1["h"]
    if not direction or not matched_area: return None
    if not has_mss(candles, direction): return None # REJECT no MSS
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
    provider = "Binance" if market=="CRYPTOCURRENCIES" else "Twelve Data"
    return f"""🚨 CONFIRMED CRT LIQUIDITY SWEEP 🚨\n\nASSET: {asset}\nSYMBOL: {symbol}\nMARKET: {market}\n\nDIRECTION: {emoji} {direction}\n\nTIMEFRAME: {tf}\n\nLIQUIDITY AREA:\n{area}\n\nDATE: {now.strftime('%d %B %Y')}\n\nCANDLE OPEN TIME: {open_t.strftime('%H:%M')}\nCANDLE CLOSE TIME: {close_t.strftime('%H:%M')}\n\nSWEEP CANDLE OHLC:\n\nOPEN: {c2['o']:.{dec}f}\nHIGH: {c2['h']:.{dec}f}\nLOW: {c2['l']:.{dec}f}\nCLOSE: {c2['c']:.{dec}f}\n\nSWEPT LIQUIDITY LEVEL: {level:.{dec}f}\n\nUPPER WICK: {upper:.{dec}f}\nLOWER WICK: {lower:.{dec}f}\nBODY SIZE: {body:.{dec}f}\n\nRANGE CANDLE 1: High {c1['h']:.{dec}f} / Low {c1['l']:.{dec}f}\nMSS: ✅ CONFIRMED\nENTRY: {entry}\nTARGET: {target}\n\nSTATUS: CONFIRMED {direction} CRT SWEEP\n\nALERT GENERATED: {now.strftime('%H:%M:%S')}\nTIMEZONE: Africa/Lagos\nDATA PROVIDER: {provider}\n\nNOTE: This is a liquidity sweep alert, not an automatic buy or sell recommendation."""

def send_telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg}, timeout=15)
    except Exception as e:
        print("Telegram error:", e)

def scan_once():
    for market, symbols in MARKETS.items():
        for sym in symbols:
            for tf in TIMEFRAMES:
                candles = get_candles(sym, market, tf)
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
    print("CRT Bot Started - 27 symbols - H4/D1/W1/MN1 ONLY - Twelve Data + Binance")
    while True:
        scan_once()
        time.sleep(14400) # 4 hours - only on candle close, save API calls