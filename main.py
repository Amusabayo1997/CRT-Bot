import time, requests, sqlite3, os
from datetime import datetime, timedelta
import pytz

# === PUT YOUR KEYS HERE LATER FOR RENDER, NOT FOR GITHUB ===
FCS_KEY = os.getenv("FCS_KEY", "PASTE_YOUR_FCS_KEY_HERE")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")
CHAT_ID = os.getenv("CHAT_ID", "PASTE_YOUR_CHAT_ID_HERE")
LAGOS = pytz.timezone("Africa/Lagos")
TIMEFRAMES = ["H4", "D1", "W1", "MN1"]

# ONLY 5 SYMBOLS FOR TEST - EURUSD, GBPUSD, XAUUSD, BTCUSD, USOIL
MARKETS = {
 "FOREX": ["EURUSD","GBPUSD"],
 "PRECIOUS METALS": ["XAUUSD"],
 "CRYPTOCURRENCIES": ["BTCUSD"],
 "ENERGY": ["USOIL"],
 "DOLLAR INDEX": ["DXY"]
}
DECIMALS = {"EURUSD":5,"GBPUSD":5,"XAUUSD":2,"BTCUSD":2,"USOIL":2,"DXY":2}
ASSET_NAME = {"XAUUSD":"GOLD","BTCUSD":"BITCOIN","USOIL":"WTI CRUDE","DXY":"US DOLLAR INDEX"}

db = sqlite3.connect("crt_alerts.db", check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS sent (key TEXT PRIMARY KEY)")
db.commit()
def already_sent(key):
    cur = db.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone()
    if cur: return True
    db.execute("INSERT INTO sent VALUES (?)", (key,)); db.commit()
    return False

def get_candles(symbol, tf):
    period = {"H4":"4h","D1":"1d","W1":"1w","MN1":"1M"}[tf]
    urls = [
        f"https://fcsapi.com/api-v3/forex/candle?symbol={symbol}&period={period}&access_key={FCS_KEY}",
        f"https://fcsapi.com/api-v3/crypto/candle?symbol={symbol}&period={period}&access_key={FCS_KEY}",
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=15).json()
            resp = r.get("response")
            if resp and isinstance(resp, list) and len(resp) > 30:
                candles = []
                for c in resp:
                    candles.append({"o":float(c["o"]),"h":float(c["h"]),"l":float(c["l"]),"c":float(c["c"]),"t":int(c["t"])})
                candles.sort(key=lambda x: x["t"])
                return candles
        except: pass
    return None

def calc_areas(candles):
    if len(candles) < 50: return {}
    areas = {}
    areas["PDH/PDL"] = (max(c["h"] for c in candles[-7:-1]), min(c["l"] for c in candles[-7:-1]))
    areas["PWH/PWL"] = (max(c["h"] for c in candles[-31:-1]), min(c["l"] for c in candles[-31:-1]))
    areas["PMH/PML"] = (max(c["h"] for c in candles[-121:-1]), min(c["l"] for c in candles[-121:-1]))
    areas["Session High/Low"] = (max(c["h"] for c in candles[-13:-1]), min(c["l"] for c in candles[-13:-1]))
    fvgs = []
    for i in range(2, len(candles)-1):
        if candles[i-2]["h"] < candles[i]["l"]:
            fvgs.append(("BULLISH FVG", candles[i-2]["h"], candles[i]["l"]))
        if candles[i-2]["l"] > candles[i]["h"]:
            fvgs.append(("BEARISH FVG", candles[i]["h"], candles[i-2]["l"]))
    if fvgs:
        last = fvgs[-1]; areas[last[0]] = (last[1], last[2])
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

def detect(symbol, market, tf, candles):
    if len(candles) < 50: return None
    if is_sideways(candles): return None
    c1 = candles[-2]; c2 = candles[-1]
    swept_high = c2["h"] > c1["h"]
    swept_low = c2["l"] < c1["l"]
    if swept_high and swept_low: return None
    if c2["c"] > c1["h"] or c2["c"] < c1["l"]: return None
    areas = calc_areas(candles)
    tol = (c1["h"]-c1["l"]) * 0.15
    direction = None; matched_area = None; matched_level = None
    if swept_low and c2["c"] > c1["l"] and c2["c"] < c1["h"]:
        direction = "BULLISH"; sweep_level = c2["l"]
        for name, (alow, ahigh) in areas.items():
            if price_in_area(sweep_level, min(alow,ahigh), max(alow,ahigh), tol):
                matched_area = name; matched_level = min(alow,ahigh); break
        if not matched_area:
            matched_area = "CRT Candle 1 Range Low"; matched_level = c1["l"]
    elif swept_high and c2["c"] < c1["h"] and c2["c"] > c1["l"]:
        direction = "BEARISH"; sweep_level = c2["h"]
        for name, (alow, ahigh) in areas.items():
            if price_in_area(sweep_level, min(alow,ahigh), max(alow,ahigh), tol):
                matched_area = name; matched_level = max(alow,ahigh); break
        if not matched_area:
            matched_area = "CRT Candle 1 Range High"; matched_level = c1["h"]
    if not direction or not matched_area: return None
    if not has_mss(candles, direction): return None
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
    return f"""🚨 CONFIRMED CRT LIQUIDITY SWEEP 🚨\n\nASSET: {asset}\nSYMBOL: {symbol}\nMARKET: {market}\n\nDIRECTION: {emoji} {direction}\n\nTIMEFRAME: {tf}\n\nLIQUIDITY AREA:\n{area}\n\nDATE: {now.strftime('%d %B %Y')}\n\nCANDLE OPEN TIME: {open_t.strftime('%H:%M')}\nCANDLE CLOSE TIME: {close_t.strftime('%H:%M')}\n\nSWEEP CANDLE OHLC:\n\nOPEN: {c2['o']:.{dec}f}\nHIGH: {c2['h']:.{dec}f}\nLOW: {c2['l']:.{dec}f}\nCLOSE: {c2['c']:.{dec}f}\n\nSWEPT LIQUIDITY LEVEL: {level:.{dec}f}\n\nUPPER WICK: {upper:.{dec}f}\nLOWER WICK: {lower:.{dec}f}\nBODY SIZE: {body:.{dec}f}\n\nMSS: ✅ CONFIRMED\nTARGET: {target}\n\nSTATUS: CONFIRMED {direction} CRT SWEEP\n\nALERT GENERATED: {now.strftime('%H:%M:%S')}\nTIMEZONE: Africa/Lagos\nDATA PROVIDER: FCS API\n\nNOTE: This is a liquidity sweep alert, not an automatic buy or sell recommendation."""

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
                    print(f"{sym} {tf} -> UNAVAILABLE")
                    continue
                alert = detect(sym, market, tf, candles)
                if alert:
                    key = f"{sym}-{tf}-{candles[-1]['t']}"
                    if already_sent(key): continue
                    send_telegram(alert)
                    print(f"ALERT SENT: {sym} {tf}")

if __name__ == "__main__":
    print("CRT Bot Started - H4/D1/W1/MN1 ONLY")
    while True:
        scan_once()
        time.sleep(60)