"""Run from the repo root: python backtest/btc.py  — pre-registered gold-rule test on BTC/USD (never trades)."""
# Pre-registered gold test applied unchanged to BTC/USD (same PASS rule as backtest/pairs.py)
import sys; sys.path.insert(0, "backtest"); sys.path.insert(0, ".")
from datetime import datetime
from engine import *
import engine
from helpers import to4h, trend_only
MID = datetime(2025, 8, 6)
sym = "BTC/USD"
b4 = to4h(load(sym)); sg = signals(b4, trend_only)
print("bars", len(b4), b4[0]["t"], "->", b4[-1]["t"])
for spread, fund in [(30, 0.0003), (60, 0.0006), (100, 0.0009)]:
    engine.SPREAD[sym] = spread; engine.FUND_PER_NIGHT = fund
    for name, kw in [("buy-only", {"long_only": True}), ("both", {})]:
        tr = run(sym, b4, sg, stop_atr=2, target_atr=4, time_filter=False, **kw)
        s = stats(tr); a = stats([t for t in tr if t['t'] < MID]); b = stats([t for t in tr if t['t'] >= MID])
        r = [stats(run(sym, b4, sg, stop_atr=2, target_atr=4, time_filter=False, random_dir=k, **kw))['avgR'] for k in range(100)]
        beat = sum(x < s['avgR'] for x in r)
        ok = a.get('avgR', -1) > 0.10 and b.get('avgR', -1) > 0.10 and beat >= 95
        hold = sum(t["hours"] for t in tr) / max(len(tr), 1) * 4
        print(f"spread ${spread} fund {fund*100:.2f}%/night {name:9s} n{s['n']:4d} win{s['win%']:3.0f}% avgR {s['avgR']:+.3f} "
              f"OLD n{a.get('n',0)} {a.get('avgR',0):+.2f} NEW n{b.get('n',0)} {b.get('avgR',0):+.2f} DD {s['maxDD_R']:4.1f}R "
              f"streak {s['lose_streak']} beats {beat:3d}% hold~{hold:.0f}h {'PASS' if ok else 'FAIL'}")
# gold reference under the repo's own assumptions
engine.FUND_PER_NIGHT = 0.00015
g4 = to4h(load("XAU/USD")); gs = signals(g4, trend_only)
tr = run("XAU/USD", g4, gs, stop_atr=2, target_atr=4, time_filter=False, long_only=True)
s = stats(tr); print("GOLD ref buy-only", {k: round(v, 3) for k, v in s.items()})
