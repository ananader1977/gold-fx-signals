import sys; sys.path.insert(0, "backtest")  # run from repo root: python backtest/pairs.py USD/JPY AUD/USD ...
# Pre-registered test: the gold setup's rules, unchanged, on other pairs.
# PASS = avgR > +0.10 in BOTH periods (Apr 2022-Aug 2025, Aug 2025-Oct 2026) AND beats >= 95% of random-direction runs.
import sys
from datetime import datetime
from engine import *
import engine
from helpers import to4h, trend_only
engine.FUND_PER_NIGHT = 0.00015
MID = datetime(2025, 8, 6)
for sym in sys.argv[1:]:
    b4 = to4h(load(sym)); sg = signals(b4, trend_only)
    for name, kw in [("both", {}), ("buy-only", {"long_only": True})]:
        tr = run(sym, b4, sg, stop_atr=2, target_atr=4, time_filter=False, **kw)
        s = stats(tr); a = stats([t for t in tr if t['t'] < MID]); b = stats([t for t in tr if t['t'] >= MID])
        r = [stats(run(sym, b4, sg, stop_atr=2, target_atr=4, time_filter=False, random_dir=k, **kw))['avgR'] for k in range(100)]
        beat = sum(x < s['avgR'] for x in r)
        ok = a.get('avgR', -1) > 0.10 and b.get('avgR', -1) > 0.10 and beat >= 95
        print(f"{sym:8s} {name:9s} n{s['n']:4d} win{s['win%']:3.0f}% avgR {s['avgR']:+.3f} OLD {a.get('avgR',0):+.2f} NEW {b.get('avgR',0):+.2f} DD {s['maxDD_R']:4.1f}R beats {beat:3d}% {'PASS' if ok else '-'}")
    # sell-only: mirror by negating prices is awkward; count SELL trades from 'both'
    tr = run(sym, b4, sg, stop_atr=2, target_atr=4, time_filter=False)
    x = stats([t for t in tr if t['dir'] == 'SELL']); print(f"{sym:8s} sells-in-both n{x['n']:4d} avgR {x['avgR']:+.3f}")
