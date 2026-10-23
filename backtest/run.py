"""Run from the repo root: python backtest/run.py  — replays trade.py rules on backtest/data (never trades)."""
import sys; sys.path.insert(0, "backtest")
from engine import *
total = []
for s in ["XAU/USD", "EUR/USD", "GBP/USD"]:
    b = load(s); tr = run(s, b, signals(b)); total += tr
    print(s, {k: round(v, 3) for k, v in stats(tr).items()})
total.sort(key=lambda t: t["t"])
print("ALL", {k: round(v, 3) for k, v in stats(total).items()})
