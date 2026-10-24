"""Capital.com auto-trader (DEMO by default). Runs on GitHub Actions after alert.py.

Signal (set in config.json):
  timeframe "4h" + signal "trend" + long_only  -> backtested gold setup (Oct 2026): buy when, on closed 4h
  candles, EMA20 > EMA50, price > EMA50 and MACD histogram > 0; close longs when all three turn bearish.
  timeframe "1h" + signal "score" -> the original dashboard score (failed the 4.5-year backtest).
Every order is sent with a stop loss and take profit attached.

Secrets (repo Settings > Secrets and variables > Actions):
  TWELVEDATA_KEY      price candles for the signal
  CAPITAL_API_KEY     Capital.com API key
  CAPITAL_IDENTIFIER  your Capital.com login email
  CAPITAL_PASSWORD    the custom password you set for the API key
  TELEGRAM_TOKEN / TELEGRAM_CHAT_ID  (optional) trade notifications
  CAPITAL_LIVE_CONFIRM  only needed for live trading; must equal YES

Run modes:
  python trade.py          normal run (trades if enabled in config.json)
  python trade.py --check  log in, show account, epics, positions; never trades
"""
import json, math, os, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

import alert  # reuse indicators, Telegram helper and market-hours check

DEMO = "https://demo-api-capital.backend-capital.com/api/v1"
LIVE = "https://api-capital.backend-capital.com/api/v1"
STATE_FILE = "trade_state.json"
EQUITY_FILE = "equity.json"

DEFAULTS = {
    "enabled": False,               # master switch
    "mode": "demo",                 # "demo" or "live"
    "risk_pct": 1.0,                # % of balance risked per trade (distance to stop)
    "max_size": {"XAU/USD": 5},     # hard cap per order (oz)
    "epics": {"XAU/USD": "GOLD"},   # gold only (other instruments failed the backtest)
    "stop_atr": 1.5,
    "target_atr": 3.0,
    "max_open_positions": 3,
    "max_trades_per_day": 6,
    "max_daily_loss_pct": 3.0,      # stop opening trades after this drawdown today
    "max_spread_atr": 0.3,          # skip if spread > 30% of ATR
    "close_on_opposite_signal": True,
    "timeframe": "1h",              # "1h" or "4h" (4h candles are built from 1h, aligned to 00/04/08.. UTC)
    "signal": "score",              # "score" = dashboard score, "trend" = EMA20/EMA50/MACD all agree
    "long_only": False,             # True = never open SELL positions (SELL signal only closes longs)
    "no_trade_hours_utc": [[12, 15]],   # skip entries 12:00-15:00 UTC (US data releases)
    "no_trade_friday_after_utc": 18,    # no new trades late Friday (weekend gap risk)
}


# ---------------- Capital.com client ----------------
class Capital:
    def __init__(self, base, key):
        self.base, self.key, self.h = base, key, {}

    def req(self, method, path, body=None, params=None):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(url, data=data, method=method)
        r.add_header("Content-Type", "application/json")
        r.add_header("X-CAP-API-KEY", self.key)
        for k, v in self.h.items():
            r.add_header(k, v)
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                raw = resp.read().decode() or "{}"
                return json.loads(raw), resp.headers
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:300]
            raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {msg}") from None

    def login(self, ident, pwd):
        _, hdr = self.req("POST", "/session", {"identifier": ident, "password": pwd, "encryptedPassword": False})
        self.h = {"CST": hdr["CST"], "X-SECURITY-TOKEN": hdr["X-SECURITY-TOKEN"]}

    def account(self):
        j, _ = self.req("GET", "/accounts")
        accs = j.get("accounts", [])
        acc = next((a for a in accs if a.get("preferred")), accs[0] if accs else {})
        bal = acc.get("balance", {})
        return {"id": acc.get("accountId"), "name": acc.get("accountName"), "currency": acc.get("currency"),
                "balance": float(bal.get("balance", 0)), "available": float(bal.get("available", 0)),
                "pnl": float(bal.get("profitLoss", 0))}

    def market(self, epic):
        j, _ = self.req("GET", f"/markets/{epic}")
        snap, rules = j.get("snapshot", {}), j.get("dealingRules", {})
        def rule(name, default):
            v = rules.get(name) or {}
            return float(v.get("value", default)) if isinstance(v, dict) else float(v or default)
        return {"bid": float(snap.get("bid") or 0), "offer": float(snap.get("offer") or 0),
                "status": snap.get("marketStatus", ""), "min_size": rule("minDealSize", 0),
                "step": rule("minSizeIncrement", 0) or rule("minDealSize", 0),
                "name": j.get("instrument", {}).get("name", epic)}

    def search(self, term):
        j, _ = self.req("GET", "/markets", params={"searchTerm": term})
        return [(m.get("epic"), m.get("instrumentName")) for m in j.get("markets", [])][:8]

    def positions(self):
        j, _ = self.req("GET", "/positions")
        out = []
        for p in j.get("positions", []):
            pos, mk = p.get("position", {}), p.get("market", {})
            out.append({"dealId": pos.get("dealId"), "epic": mk.get("epic"), "direction": pos.get("direction"),
                        "size": pos.get("size"), "level": pos.get("level"), "upl": pos.get("upl"),
                        "stop": pos.get("stopLevel"), "profit": pos.get("profitLevel"),
                        "created": pos.get("createdDateUTC"), "bid": mk.get("bid"), "offer": mk.get("offer")})
        return out

    def activity(self, days=3):
        """Recent account activity (opens, closes, stop/limit hits). Returns [] if unavailable."""
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        params = {"from": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S"),
                  "to": now.strftime("%Y-%m-%dT%H:%M:%S"), "detailed": "true"}
        try:
            j, _ = self.req("GET", "/history/activity", params=params)
        except RuntimeError as e:
            print("  (activity history unavailable:", str(e)[:120], ")")
            return []
        return j.get("activities", [])

    def open(self, epic, direction, size, stop, target):
        j, _ = self.req("POST", "/positions", {"epic": epic, "direction": direction, "size": size,
                                               "guaranteedStop": False, "stopLevel": stop, "profitLevel": target})
        ref = j.get("dealReference")
        c, _ = self.req("GET", f"/confirms/{ref}")
        return c

    def close(self, deal_id):
        j, _ = self.req("DELETE", f"/positions/{deal_id}")
        return j


# ---------------- helpers ----------------
def load_json(path, default):
    try:
        return json.load(open(path))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


WINDOW = 199  # candles per signal calculation (same as the backtest)


def candles(sym, timeframe="1h"):
    """Closed candles only. 4h candles are grouped from 1h exactly as in backtest/engine.py."""
    j = alert.time_series(sym)
    if j.get("status") == "error" or not j.get("values"):
        raise RuntimeError(f"Twelve Data {sym}: {j.get('message', 'no data')}")
    rows = list(reversed(j["values"]))
    now = datetime.now(timezone.utc)
    c = []
    for r in rows:
        t = datetime.strptime(r["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        c.append({"t": t, "open": float(r["open"]), "high": float(r["high"]),
                  "low": float(r["low"]), "close": float(r["close"])})
    # drop the still-forming hour so the signal does not flicker inside a candle
    if c and (now - c[-1]["t"]).total_seconds() < 3600:
        c = c[:-1]
    if timeframe == "4h":
        out = []
        for x in c:
            start = x["t"].replace(hour=x["t"].hour // 4 * 4)
            if out and out[-1]["t"] == start:
                o = out[-1]
                o["high"], o["low"], o["close"] = max(o["high"], x["high"]), min(o["low"], x["low"]), x["close"]
            else:
                out.append({**x, "t": start})
        # drop a 4h candle that has not finished yet
        if out and (now - out[-1]["t"]).total_seconds() < 4 * 3600:
            out = out[:-1]
        c = out
    return c[-WINDOW:]


def trend_signal(closes):
    """Trend-only signal: EMA20 vs EMA50, price vs EMA50, MACD histogram. All three must agree."""
    p = closes[-1]
    e20, e50 = alert.ema(closes, 20)[-1], alert.ema(closes, 50)[-1]
    h = alert.macd_hist(closes)[-1]
    score = (1 if e20 > e50 else -1) + (1 if p > e50 else -1) + (1 if h > 0 else -1)
    signal = "BUY" if score == 3 else "SELL" if score == -3 else "WAIT"
    return p, signal, score, alert.rsi(closes)


def atr(c, n=14):
    tr = [c[0]["high"] - c[0]["low"]] + [max(x["high"] - x["low"], abs(x["high"] - c[i - 1]["close"]),
                                             abs(x["low"] - c[i - 1]["close"])) for i, x in enumerate(c) if i > 0]
    a = sum(tr[1:n + 1]) / n
    for v in tr[n + 1:]:
        a = (a * (n - 1) + v) / n
    return a


def round_step(x, step):
    if step <= 0:
        return round(x, 2)
    dec = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    return round(math.floor(x / step) * step, dec)


def blocked_time(now, t):
    if any(a <= now.hour < b for a, b in t["no_trade_hours_utc"]):
        return "news window"
    if now.weekday() == 4 and now.hour >= t["no_trade_friday_after_utc"]:
        return "late Friday"
    if now.weekday() == 6 and now.hour < 23:
        return "Sunday open"
    return None


def snapshot(cap, label, signals=None):
    """Save balance, equity and open positions to equity.json for the dashboard's account card."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    acc, pos = cap.account(), cap.positions()
    upl = sum(float(p["upl"] or 0) for p in pos)
    eq = load_json(EQUITY_FILE, {})
    eq.setdefault("start", {"time": "2026-10-22T10:58:00Z", "balance": 1002.81})
    eq.setdefault("history", [[eq["start"]["time"], eq["start"]["balance"], eq["start"]["balance"]]])
    eq.update({"mode": label, "currency": acc["currency"], "updated": now})
    eq["latest"] = {"balance": round(acc["balance"], 2), "available": round(acc["available"], 2),
                    "open_pl": round(upl, 2), "equity": round(acc["balance"] + upl, 2),
                    "positions": [{k: p[k] for k in ("epic", "direction", "size", "level", "stop", "profit", "upl", "created")}
                                  for p in pos]}
    if signals is not None:
        eq["signals"] = signals   # the bot's own view per instrument, shown on the dashboard
    # Deposit / withdrawal detection: with 1% risk and one position, trading can't move the balance 10%
    # between two runs. A bigger jump is a top-up or withdrawal -> start a new test phase instead of
    # counting it as profit or loss.
    last_bal = eq["history"][-1][1] if eq["history"] else None
    if last_bal and abs(acc["balance"] - last_bal) > 0.10 * last_bal:
        eq.setdefault("phases", []).append({"start": eq["start"], "end": {"time": now, "balance": last_bal,
                                            "equity": eq["history"][-1][2]}})
        eq["start"] = {"time": now, "balance": round(acc["balance"], 2)}
        eq["history"] = []
        alert.telegram(f"[{label}] Balance changed {last_bal:,.2f} → {acc['balance']:,.2f} {acc['currency']} "
                       f"(deposit/withdrawal). New test phase started; 'change since start' now measures from here.")
    eq["history"].append([now, eq["latest"]["balance"], eq["latest"]["equity"]])
    eq["history"] = eq["history"][-5000:]
    json.dump(eq, open(EQUITY_FILE, "w"), indent=1)
    print(f"Snapshot: balance {acc['balance']:.2f} equity {eq['latest']['equity']:.2f} {acc['currency']}")


def report(cap, t):
    """Check every open position has a stop loss and take profit on the correct side. Never trades."""
    def note(msg, level="notice"):
        print(msg)
        print(f"::{level}::{msg}")  # also shows as an annotation on the run page
    pos = cap.positions()
    if not pos:
        note("No open positions.")
    bad = 0
    for p in pos:
        lvl, stop, prof = p["level"], p["stop"], p["profit"]
        buy = p["direction"] == "BUY"
        problems = []
        if stop is None:
            problems.append("NO STOP LOSS")
        elif (buy and stop >= lvl) or (not buy and stop <= lvl):
            problems.append("stop on wrong side")
        if prof is None:
            problems.append("NO TAKE PROFIT")
        elif (buy and prof <= lvl) or (not buy and prof >= lvl):
            problems.append("take profit on wrong side")
        rr = ""
        if stop is not None and prof is not None and stop != lvl:
            rr = f" reward:risk {abs(prof - lvl) / abs(lvl - stop):.2f}"
        status = "OK" if not problems else "PROBLEM: " + ", ".join(problems)
        bad += bool(problems)
        note(f"{p['epic']} {p['direction']} size {p['size']} entry {lvl} stop {stop} target {prof}{rr} "
             f"P/L {p['upl']} opened {p['created']} -> {status}", "notice" if not problems else "error")
    acts = cap.activity()
    for a in acts[:15]:
        d = a.get("details") or {}
        note(f"history {a.get('dateUTC') or a.get('date')} {a.get('epic')} {a.get('type')} {a.get('status')} "
             f"src={a.get('source')} dir={d.get('direction')} size={d.get('size')} level={d.get('level')} "
             f"stop={d.get('stopLevel')} limit={d.get('limitLevel') or d.get('profitLevel')}")
    if bad:
        sys.exit(f"{bad} position(s) without a correct stop/target")


# ---------------- main ----------------
def main():
    check_only = "--check" in sys.argv
    report_only = "--report" in sys.argv
    live_run = "--live" in sys.argv   # second, separate run on the LIVE account (config.json -> "live" overrides)
    now = datetime.now(timezone.utc)
    cfg = load_json("config.json", {})
    t = {**DEFAULTS, **cfg.get("trading", {})}
    state_file = STATE_FILE
    if live_run:
        t = {**t, **cfg.get("live", {}), "mode": "live"}
        state_file = "live_state.json"   # kept in a private Actions cache, never committed (repo is public)
        if not t["enabled"]:
            print("::warning::Live trading disabled in config.json (live.enabled=false)."); return
        conf_val = os.environ.get("CAPITAL_LIVE_CONFIRM", "")
        if conf_val.strip().upper() != "YES":
            print(f"::warning::Live locked: secret CAPITAL_LIVE_CONFIRM is "
                  f"{'missing or empty' if not conf_val else f'set but not YES ({len(conf_val)} characters)'}."); return
        if report_only:
            print("Position report is demo-only (public logs)."); return
    live = t["mode"] == "live"
    if live and os.environ.get("CAPITAL_LIVE_CONFIRM", "").strip().upper() != "YES":
        sys.exit("Live mode requested but secret CAPITAL_LIVE_CONFIRM is not YES. Refusing to trade.")
    label = "LIVE" if live else "DEMO"

    if not (check_only or report_only) and not t["enabled"]:
        print("Trading disabled in config.json (trading.enabled=false)."); return
    if not (check_only or report_only) and alert.market_closed(now):
        print("Market closed."); return

    for k in ("CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_PASSWORD"):
        if not os.environ.get(k):
            sys.exit(f"Secret {k} missing")
    cap = Capital(LIVE if live else DEMO, os.environ["CAPITAL_API_KEY"])
    cap.login(os.environ["CAPITAL_IDENTIFIER"], os.environ["CAPITAL_PASSWORD"])
    acc = cap.account()
    if live_run:   # public run logs: never print live money amounts
        print(f"[{label}] logged in, account currency {acc['currency']}")
    else:
        print(f"[{label}] {acc['name']} balance {acc['balance']:.2f} {acc['currency']} available {acc['available']:.2f}")

    if report_only:
        snapshot(cap, label)
        report(cap, t)
        return

    if check_only:
        missing = []
        for sym, epic in t["epics"].items():
            try:
                m = cap.market(epic)
                msg = (f"[{label}] {sym} -> epic {epic}: {m['name']} bid {m['bid']} offer {m['offer']} "
                       f"status {m['status']} min size {m['min_size']} step {m['step']}")
                print("  " + msg)
                print("::notice::" + msg)
                c = candles(sym, t["timeframe"])
                a = atr(c)
                need = m["min_size"] * t["stop_atr"] * a * (3.6725 if acc["currency"] == "AED" else 1)
                fn = trend_signal if t["signal"] == "trend" else alert.analyse
                _, sig, score, _ = fn([x["close"] for x in c])
                pct = 100 * need / max(acc['balance'], 0.01)
                amt = "" if live_run else f"{need:.2f} {acc['currency']} = "
                print(f"::notice::[{label}] {sym} {t['timeframe']} signal {sig} (score {score:+d}), ATR {a:.5f}; "
                      f"min size risks {amt}{pct:.2f}% of balance (risk setting {t['risk_pct']}%, "
                      f"min-size allowed up to {t.get('min_size_max_risk_pct', 0)}%) -> "
                      f"{'OK, will trade min size' if t['risk_pct'] >= pct or t.get('min_size_max_risk_pct', 0) >= pct else 'TOO SMALL: would skip trades'}")
            except RuntimeError as e:
                print(f"  {sym} -> epic {epic} NOT FOUND ({e}). Candidates:",
                      cap.search({"XAU/USD": "gold", "XAG/USD": "silver"}.get(sym, sym.replace("/", ""))))
                missing.append(sym)
        if not live_run:
            print("  open positions:", cap.positions() or "none")
        else:
            print(f"::notice::[{label}] open positions: {len(cap.positions())}")
        if missing:
            sys.exit(f"Market name not found for: {', '.join(missing)} (see candidates above)")
        return

    state = load_json(state_file, {})
    today = now.strftime("%Y-%m-%d")
    if state.get("day") != today:
        state.update({"day": today, "start_balance": acc["balance"], "trades_today": 0})
    state.setdefault("entered", {})

    loss_pct = (state["start_balance"] - acc["balance"] - min(acc["pnl"], 0)) / max(state["start_balance"], 1) * 100
    halt = None
    if loss_pct >= t["max_daily_loss_pct"]:
        halt = f"daily loss limit hit ({loss_pct:.1f}%)"
    elif state["trades_today"] >= t["max_trades_per_day"]:
        halt = "max trades per day reached"
    elif blocked_time(now, t):
        halt = blocked_time(now, t)
    if t.get("min_balance") and acc["balance"] < t["min_balance"]:
        halt = f"balance below the {t['min_balance']} {acc['currency']} floor"
        if state.get("floor_alerted") != today:
            state["floor_alerted"] = today
            alert.telegram(f"[{label}] Balance {acc['balance']:.2f} {acc['currency']} is below the floor of "
                           f"{t['min_balance']}. No new trades until you raise the balance or change config.json.")

    positions = cap.positions()
    bot_signals = {}
    for sym, epic in t["epics"].items():
        try:
            c = candles(sym, t["timeframe"])
        except RuntimeError as e:
            print(f"{sym}: skipped, no price data ({e})"); continue
        fn = trend_signal if t["signal"] == "trend" else alert.analyse
        _, signal, score, r = fn([x["close"] for x in c])
        a = atr(c)
        mine = [p for p in positions if p["epic"] == epic]
        closes = [x["close"] for x in c]
        e20, e50 = alert.ema(closes, 20)[-1], alert.ema(closes, 50)[-1]
        mh = alert.macd_hist(closes)[-1]
        dp = alert.DP.get(sym, 4)
        info = bot_signals[sym] = {
            "signal": signal, "score": score, "timeframe": t["timeframe"], "rule": t["signal"],
            "long_only": t["long_only"], "candle": c[-1]["t"].strftime("%Y-%m-%dT%H:%MZ") if "t" in c[-1] else None,
            "close": round(closes[-1], dp), "ema20": round(e20, dp), "ema50": round(e50, dp),
            "macd_hist": round(mh, dp + 2), "atr": round(a, dp), "stop_atr": t["stop_atr"], "target_atr": t["target_atr"],
            "risk_pct": t["risk_pct"], "action": ""}
        print(f"{sym}: {t['timeframe']} {t['signal']} signal {signal} score {score:+d} ATR {a:.5f} open {len(mine)}")

        # Telegram when the bot's own signal changes (replaces the old 1h score alerts)
        prev = state.setdefault("bot_signal", {}).get(sym)
        if prev is not None and prev != signal and not live_run:   # demo run already announces it
            what = {"BUY": "all 3 trend rules agree. The bot buys if it has no gold position.",
                    "SELL": ("bearish. The bot closes any gold long and does not buy." if t["long_only"]
                             else "bearish. The bot may sell."),
                    "WAIT": "the rules no longer all agree. No new trades; open trades keep their stop/target."}[signal]
            alert.telegram(f"[{label}] {sym} {t['timeframe']} signal: {prev} → {signal}\n{what}\nPrice {closes[-1]:.{dp}f}")
        state["bot_signal"][sym] = signal

        # reset the 'already entered' flag once the signal goes away
        if state["entered"].get(sym) and state["entered"][sym] != signal:
            state["entered"].pop(sym)

        # close positions that now point the wrong way
        if t["close_on_opposite_signal"] and signal != "WAIT":
            for p in mine:
                if p["direction"] != signal:
                    cap.close(p["dealId"])
                    alert.telegram(f"[{label}] Closed {p['direction']} {sym} (size {p['size']}, P/L {p['upl']}) — signal flipped to {signal}")
                    positions = [q for q in positions if q["dealId"] != p["dealId"]]
                    mine = [q for q in mine if q["dealId"] != p["dealId"]]

        if mine:
            info["action"] = f"holding {mine[0]['direction']} position"; continue
        if signal == "WAIT":
            info["action"] = "waiting: trend rules not all agreeing" if t["signal"] == "trend" else "waiting: no clear signal"; continue
        if t["long_only"] and signal == "SELL":
            info["action"] = "bearish: no buys (buy-only)"; continue
        if state["entered"].get(sym) == signal:
            info["action"] = f"already traded this {signal} signal; waits for it to change"; continue
        if halt:
            info["action"] = f"entry blocked: {halt}"
            print(f"  skip entry: {halt}"); continue
        if len(positions) >= t["max_open_positions"]:
            info["action"] = "entry blocked: max open positions"
            print("  skip entry: max open positions"); continue

        m = cap.market(epic)
        if m["status"] != "TRADEABLE" or not m["bid"]:
            info["action"] = f"entry blocked: market {m['status']}"
            print(f"  skip entry: market status {m['status']}"); continue
        spread = m["offer"] - m["bid"]
        if spread > t["max_spread_atr"] * a:
            info["action"] = "entry blocked: spread too wide"
            print(f"  skip entry: spread {spread} too wide vs ATR"); continue

        entry = m["offer"] if signal == "BUY" else m["bid"]
        d = 1 if signal == "BUY" else -1
        stop_dist = t["stop_atr"] * a
        dp = alert.DP.get(sym, 4)
        stop = round(entry - d * stop_dist, dp)
        target = round(entry + d * t["target_atr"] * a, dp)
        risk_cash = acc["balance"] * t["risk_pct"] / 100
        # both instruments are quoted in USD: convert risk to USD if the account is in AED (pegged rate)
        risk_usd = risk_cash / 3.6725 if acc["currency"] == "AED" else risk_cash
        if acc["currency"] not in ("USD", "AED"):
            print(f"  note: account currency {acc['currency']} treated as USD for sizing")
        risk_cash = risk_usd
        size = min(risk_cash / stop_dist, t["max_size"].get(sym, 1))
        size = round_step(size, m["step"])
        # tiny accounts: allow the broker's minimum size if its risk stays within min_size_max_risk_pct
        bal_usd = acc["balance"] / 3.6725 if acc["currency"] == "AED" else acc["balance"]
        if size < m["min_size"] and m["min_size"] * stop_dist <= bal_usd * t.get("min_size_max_risk_pct", 0) / 100:
            size = m["min_size"]
            print(f"  using broker minimum size {size} (risk {100 * size * stop_dist / bal_usd:.1f}% of balance)")
        if size < m["min_size"]:
            info["action"] = f"entry blocked: size below broker minimum at {t['risk_pct']}% risk"
            print(f"  skip entry: size {size} below broker minimum {m['min_size']} at {t['risk_pct']}% risk"); continue

        conf = cap.open(epic, signal, size, stop, target)
        ok = conf.get("dealStatus") == "ACCEPTED"
        info["action"] = f"opened {signal} {size} (stop {stop}, target {target})" if ok else "order rejected"
        state["trades_today"] += 1 if ok else 0
        if ok:
            state["entered"][sym] = signal
            positions.append({"epic": epic, "direction": signal})
        alert.telegram(f"[{label}] {'Opened' if ok else 'REJECTED'} {signal} {sym}\n"
                       f"Size {size} @ ~{entry}\nStop {stop} | Target {target}\n"
                       f"Risk ≈ {size * stop_dist:.2f} USD (score {score:+d})"
                       + ("" if ok else f"\nReason: {conf.get('reason') or conf.get('status')}"))
        print("  order:", conf.get("dealStatus"), conf.get("dealId"))

    json.dump(state, open(state_file, "w"), indent=2)
    if not live_run:   # the public dashboard shows the demo account only
        snapshot(cap, label, {"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "items": bot_signals})


if __name__ == "__main__":
    main()
