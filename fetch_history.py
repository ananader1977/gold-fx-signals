"""Download 1h price history from Twelve Data for backtesting (run manually via the Backtest data workflow).

Saves backtest/data/<SYMBOL>.csv with datetime,open,high,low,close (UTC). Never trades.
"""
import csv, os, time
from datetime import datetime, timedelta

import alert

SYMBOLS = ["XAU/USD", "EUR/USD", "GBP/USD"]
PAGES = int(os.environ.get("PAGES", "2"))   # 5000 bars per page (~10 months of forex)
os.makedirs("backtest/data", exist_ok=True)

for sym in SYMBOLS:
    rows, end = {}, None
    for page in range(PAGES):
        params = {"symbol": sym, "interval": "1h", "outputsize": 5000, "timezone": "UTC",
                  "order": "ASC", "apikey": alert.KEY}
        if end:
            params["end_date"] = end
        j = alert.get("https://api.twelvedata.com/time_series", params)
        time.sleep(10)  # stay well under the free plan's 8 calls/min
        if j.get("status") == "error" or not j.get("values"):
            print(sym, "page", page, "error:", j.get("message"))
            break
        for v in j["values"]:
            rows[v["datetime"]] = v
        first = min(v["datetime"] for v in j["values"])
        end = (datetime.strptime(first, "%Y-%m-%d %H:%M:%S") - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        print(sym, "page", page, len(j["values"]), "bars from", first)
    with open(f"backtest/data/{sym.replace('/', '')}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["datetime", "open", "high", "low", "close"])
        for k in sorted(rows):
            v = rows[k]
            w.writerow([k, v["open"], v["high"], v["low"], v["close"]])
    print(sym, "saved", len(rows), "bars")
