"""Replay of trade.py rules on 1h history. Results in R (1R = the stop distance = 1% of balance)."""
import csv, math, random, sys
from datetime import datetime

sys.path.insert(0, ".")
import alert  # the bot's own indicator code

WINDOW = 199            # bot fetches 200 bars and drops the forming one
SPREAD = {"XAU/USD": 0.45, "EUR/USD": 0.00007, "GBP/USD": 0.00013}   # typical Capital.com spreads
FUND_PER_NIGHT = 0.00022   # ~8%/yr overnight funding on notional (each side pays roughly this)


def load(sym):
    rows = list(csv.DictReader(open(f"backtest/data/{sym.replace('/', '')}.csv")))
    return [{"t": datetime.strptime(r["datetime"], "%Y-%m-%d %H:%M:%S"), "o": float(r["open"]),
             "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"])} for r in rows]


def atr(c, n=14):
    tr = [c[0]["h"] - c[0]["l"]] + [max(x["h"] - x["l"], abs(x["h"] - c[i - 1]["c"]), abs(x["l"] - c[i - 1]["c"]))
                                    for i, x in enumerate(c) if i > 0]
    a = sum(tr[1:n + 1]) / n
    for v in tr[n + 1:]:
        a = (a * (n - 1) + v) / n
    return a


def signals(bars, scorer=None):
    """Signal + ATR at the close of each bar, computed exactly as the bot would (199-bar window)."""
    out = [None] * len(bars)
    for i in range(WINDOW - 1, len(bars)):
        w = bars[i - WINDOW + 1:i + 1]
        closes = [b["c"] for b in w]
        if scorer:
            sig = scorer(closes)
        else:
            _, sig, _, _ = alert.analyse(closes)
        out[i] = (sig, atr(w))
    return out


def blocked(t):
    if 12 <= t.hour < 15: return True
    if t.weekday() == 4 and t.hour >= 18: return True
    if t.weekday() == 6 and t.hour < 23: return True
    if t.weekday() == 5: return True
    return False


def run(sym, bars, sigs, stop_atr=1.5, target_atr=3.0, close_opp=True, time_filter=True,
        random_dir=None, spread_mult=1.0, start=None, end=None, long_only=False):
    """Returns list of trades: dict(entry_t, dir, R, exit_reason, hours)."""
    sp = SPREAD[sym] * spread_mult
    trades, pos, entered = [], None, None
    prev_real, flip = None, False
    rnd = random.Random(random_dir) if random_dir is not None else None
    for i in range(WINDOW - 1, len(bars) - 1):
        b, nb = bars[i], bars[i + 1]
        if start and b["t"] < start: continue
        if end and b["t"] >= end: break
        sig, a = sigs[i]
        if rnd is not None:
            # random-direction benchmark: each time the real signal changes, flip a coin once
            # and keep that direction until the real signal changes again (same timing, same exits logic)
            if sig != prev_real:
                flip = rnd.random() < 0.5
                prev_real = sig
            if sig != "WAIT" and flip:
                sig = "SELL" if sig == "BUY" else "BUY"
        # 1) manage open position on this bar (stop/target checked intrabar)
        if pos and i > pos["i"]:
            d = pos["d"]
            if b["t"].date() != bars[i - 1]["t"].date():
                pos["fund"] += FUND_PER_NIGHT * pos["entry"]
            hit_stop = (b["l"] <= pos["stop"]) if d == 1 else (b["h"] + sp >= pos["stop"])
            hit_tgt = (b["h"] >= pos["tgt"]) if d == 1 else (b["l"] + sp <= pos["tgt"])
            exit_px = reason = None
            if hit_stop:   # conservative: stop first if both inside one bar
                exit_px, reason = pos["stop"], "stop"
                # weekend/news gap through the stop
                gap = b["o"] if d == 1 else b["o"] + sp
                if (d == 1 and gap < pos["stop"]) or (d == -1 and gap > pos["stop"]):
                    exit_px = gap
            elif hit_tgt:
                exit_px, reason = pos["tgt"], "target"
            if exit_px is not None:
                pnl = (exit_px - pos["entry"]) * d - pos["fund"]
                trades.append({**pos["meta"], "R": pnl / pos["risk"], "exit": reason, "hours": i - pos["i"]})
                pos = None
        # 2) bot runs after this bar closes; actions fill at next bar open
        if entered and entered != sig:
            entered = None
        if pos and close_opp and sig != "WAIT" and sig != ("BUY" if pos["d"] == 1 else "SELL"):
            px = nb["o"] if pos["d"] == 1 else nb["o"] + sp
            pnl = (px - pos["entry"]) * pos["d"] - pos["fund"]
            trades.append({**pos["meta"], "R": pnl / pos["risk"], "exit": "flip", "hours": i + 1 - pos["i"]})
            pos = None
        if sig == "WAIT" or pos or entered == sig or (long_only and sig == "SELL"):
            continue
        if time_filter and blocked(nb["t"]):
            continue
        d = 1 if sig == "BUY" else -1
        entry = nb["o"] + sp if d == 1 else nb["o"]          # bid/offer
        risk = stop_atr * a
        pos = {"i": i + 1, "d": d, "entry": entry, "stop": entry - d * risk, "tgt": entry + d * target_atr * a,
               "risk": risk, "fund": 0.0, "meta": {"t": nb["t"], "dir": sig, "sym": sym}}
        entered = sig
        # entry bar itself can hit stop/target
        hb = nb
        hit_stop = (hb["l"] <= pos["stop"]) if d == 1 else (hb["h"] + sp >= pos["stop"])
        hit_tgt = (hb["h"] >= pos["tgt"]) if d == 1 else (hb["l"] + sp <= pos["tgt"])
        if hit_stop or hit_tgt:
            px = pos["stop"] if hit_stop else pos["tgt"]
            trades.append({**pos["meta"], "R": (px - entry) * d / risk, "exit": "stop" if hit_stop else "target", "hours": 0})
            pos = None
    return trades


def stats(tr):
    if not tr:
        return {"n": 0}
    R = [t["R"] for t in tr]
    eq, peak, dd, streak, worst = 0, 0, 0, 0, 0
    for r in R:
        eq += r; peak = max(peak, eq); dd = max(dd, peak - eq)
        streak = streak + 1 if r < 0 else 0; worst = max(worst, streak)
    wins = [r for r in R if r > 0]
    gp, gl = sum(wins), -sum(r for r in R if r < 0)
    return {"n": len(R), "win%": 100 * len(wins) / len(R), "avgR": sum(R) / len(R), "totR": sum(R),
            "PF": gp / gl if gl else float("inf"), "maxDD_R": dd, "lose_streak": worst}
