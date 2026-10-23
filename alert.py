"""Background price-target + signal alerts. Runs on GitHub Actions, sends Telegram messages.

Secrets needed (repo Settings > Secrets and variables > Actions):
  TWELVEDATA_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
Targets live in config.json. Fired-alert memory lives in state.json (committed back by the workflow).
"""
import json, os, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

KEY = os.environ.get("TWELVEDATA_KEY", "")
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
DP = {"XAU/USD": 2, "EUR/USD": 5, "XAG/USD": 3}
CACHE = ".candle_cache.json"


def get(url, params):
    """GET JSON. HTTP errors come back as {"status": "error", "message": ...} instead of crashing."""
    try:
        with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(params), timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {}
        return {"status": "error", "code": e.code, "message": body.get("message") or f"HTTP {e.code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


def time_series(sym):
    """1h candles from Twelve Data, cached for 10 min so alert.py and trade.py share one API call."""
    import time
    try:
        cache = json.load(open(CACHE))
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    hit = cache.get(sym)
    if hit and time.time() - hit["t"] < 600:
        return hit["data"]
    j = get("https://api.twelvedata.com/time_series",
            {"symbol": sym, "interval": "1h", "outputsize": 200, "timezone": "UTC", "apikey": KEY})
    if j.get("status") != "error":
        cache[sym] = {"t": time.time(), "data": j}
        json.dump(cache, open(CACHE, "w"))
    return j


def telegram(text, strict=False):
    """Send a Telegram message. Failures are logged, never fatal, unless strict=True (used by the test)."""
    if not (TG_TOKEN and TG_CHAT):
        print("[telegram not configured]", text)
        if strict:
            sys.exit("Telegram secrets missing")
        return
    data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data, timeout=30)
    except Exception as e:
        print(f"[telegram FAILED: {e}]", text)
        if strict:
            raise


def ema(a, n):
    out = [None] * len(a)
    if len(a) < n:
        return out
    k = 2 / (n + 1)
    out[n - 1] = sum(a[:n]) / n
    for i in range(n, len(a)):
        out[i] = a[i] * k + out[i - 1] * (1 - k)
    return out


def rsi(a, n=14):
    if len(a) <= n:
        return None
    g = l = 0.0
    for i in range(1, n + 1):
        d = a[i] - a[i - 1]
        g += max(d, 0); l += max(-d, 0)
    g /= n; l /= n
    for i in range(n + 1, len(a)):
        d = a[i] - a[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def macd_hist(a):
    e12, e26 = ema(a, 12), ema(a, 26)
    m = [x - y if x is not None and y is not None else None for x, y in zip(e12, e26)]
    st = next(i for i, v in enumerate(m) if v is not None)
    sig = [None] * st + ema(m[st:], 9)
    return [x - y if x is not None and y is not None else None for x, y in zip(m, sig)]


def analyse(closes):
    """Same scoring as the dashboard."""
    p = closes[-1]
    e20, e50 = ema(closes, 20)[-1], ema(closes, 50)[-1]
    h = macd_hist(closes)
    r = rsi(closes)
    w = closes[-20:]
    mean = sum(w) / 20
    sd = (sum((x - mean) ** 2 for x in w) / 20) ** 0.5
    score = (1 if e20 > e50 else -1) + (1 if p > e50 else -1) + (1 if h[-1] > 0 else -1)
    if h[-2] is not None and h[-1] > 0 >= h[-2]: score += 1
    if h[-2] is not None and h[-1] < 0 <= h[-2]: score -= 1
    if r < 30: score += 1
    elif r > 70: score -= 1
    if p < mean - 2 * sd: score += 1
    elif p > mean + 2 * sd: score -= 1
    signal = "BUY" if score >= 3 else "SELL" if score <= -3 else "WAIT"
    return p, signal, score, r


def market_closed(now):
    d, h = now.weekday(), now.hour  # Mon=0 .. Sun=6
    return d == 5 or (d == 6 and h < 21) or (d == 4 and h >= 21)


def main():
    now = datetime.now(timezone.utc)
    if market_closed(now):
        print("Market closed, skipping"); return
    if not KEY:
        sys.exit("TWELVEDATA_KEY secret missing")
    cfg = json.load(open("config.json"))
    try:
        state = json.load(open("state.json"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    fired = set(state.get("fired", []))
    last_sig = state.get("last_signal", {})
    errors = {}

    for sym, targets in cfg["symbols"].items():
        j = time_series(sym)
        if j.get("status") == "error" or not j.get("values"):
            msg = j.get("message", "no data")
            print(sym, "error:", msg)
            errors[sym] = msg[:200]
            continue
        closes = [float(v["close"]) for v in reversed(j["values"])]
        p, signal, score, r = analyse(closes)
        dp = DP.get(sym, 4)
        print(f"{sym} {p:.{dp}f} {signal} score={score} rsi={r:.1f}")

        for direction in ("above", "below"):
            for t in targets.get(direction, []):
                key = f"{sym}|{direction}|{t}"
                hit = p >= t if direction == "above" else p <= t
                if hit and key not in fired:
                    fired.add(key)
                    telegram(f"🔔 {sym} {'rose to' if direction == 'above' else 'fell to'} {t}\nNow: {p:.{dp}f}\nSignal: {signal} (score {score:+d})")
                elif not hit and key in fired:
                    fired.discard(key)  # re-arm once price moves back

        if cfg.get("signal_alerts", True) and last_sig.get(sym) not in (None, signal) and signal != "WAIT":
            telegram(f"📈 {sym}: indicator signal now {signal} bias (score {score:+d}, RSI {r:.0f})\nPrice {p:.{dp}f}. Review the chart before trading.")
        last_sig[sym] = signal

    json.dump({"fired": sorted(fired), "last_signal": last_sig, "errors": errors},
              open("state.json", "w"), indent=2)


if __name__ == "__main__":
    main()
