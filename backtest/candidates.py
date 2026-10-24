"""Run from repo root: python backtest/candidates.py — pre-registered test of the gold rules on new candidates (never trades).
Same rules as live gold: 4h trend (EMA20>EMA50, price>EMA50, MACD hist>0), buy-only, SELL closes long, stop 2xATR / target 4xATR.
PASS (same as pairs.py) = avgR > +0.10 in BOTH periods (Apr 2022-Aug 2025, Aug 2025-Oct 2026) AND beats >= 95% of random-direction runs.
Extra check: must also beat >= 95% of random-TIMING buy-only runs (otherwise the profit is just the market rising).
ETF proxies (free data): SPY ~ US 500, QQQ ~ US Tech 100, USO ~ oil, SLV ~ silver. Costs as fraction of price."""
import sys, random; sys.path.insert(0, "backtest"); sys.path.insert(0, ".")
from datetime import datetime
from engine import *
import engine
from helpers import to4h, trend_only
MID, START = datetime(2025, 8, 6), datetime(2022, 4, 1)
CAND = {"SPY": ("US 500 (via SPY)", 0.0002, 0.00015), "QQQ": ("US Tech 100 (via QQQ)", 0.0002, 0.00015),
        "ETH/USD": ("Ethereum", 0.001, 0.0006), "USO": ("Oil (via USO)", 0.0006, 0.00015), "SLV": ("Silver (via SLV)", 0.0005, 0.00015)}
for sym, (name, spr, fund) in CAND.items():
    bars = [b for b in load(sym)]
    b4 = to4h(bars); sg = signals(b4, trend_only)
    engine.SPREAD[sym] = spr * b4[-1]["c"]; engine.FUND_PER_NIGHT = fund
    kw = dict(stop_atr=2, target_atr=4, time_filter=False, long_only=True, start=START)
    tr = run(sym, b4, sg, **kw)
    s = stats(tr); a = stats([t for t in tr if t['t'] < MID]); b = stats([t for t in tr if t['t'] >= MID])
    rd = [stats(run(sym, b4, sg, random_dir=k, **kw)).get('avgR', 0) for k in range(100)]
    beat_dir = sum(x < s['avgR'] for x in rd)
    rb = []
    for k in range(100):
        r = random.Random(k); q = s['n'] / (len(b4) * 0.45)
        fake = [None if x is None else ("BUY" if r.random() < q else "WAIT", x[1]) for x in sg]
        t2 = run(sym, b4, fake, close_opp=False, **kw); rb.append(stats(t2).get('avgR', 0) if t2 else 0)
    beat_buy = sum(x < s['avgR'] for x in rb)
    ok = a.get('avgR', -1) > 0.10 and b.get('avgR', -1) > 0.10 and beat_dir >= 95
    first = next(x for x in b4 if x["t"] >= START)["c"]
    e = pk = 1; dd = 0
    for t in tr: e *= 1 + 0.01 * t['R']; pk = max(pk, e); dd = max(dd, 1 - e / pk)
    yrs = (b4[-1]["t"] - START).days / 365
    print(f"{name:24s} n{s['n']:4d} win{s.get('win%',0):3.0f}% avgR {s.get('avgR',0):+.3f} old {a.get('avgR',0):+.2f} new {b.get('avgR',0):+.2f} "
          f"streak {s.get('lose_streak',0):2d} DD {100*dd:4.1f}% /yr {100*(e**(1/yrs)-1):+5.1f}% beats-dir {beat_dir:3d}% beats-random-buys {beat_buy:3d}% "
          f"market {100*(b4[-1]['c']/first-1):+5.0f}% -> {'PASS' if ok else 'FAIL'}{'' if beat_buy >= 95 or not ok else ' (but no better than random buying)'}")
