# Gold & EUR/USD Signals

A free tool for watching **XAU/USD (gold)** and **EUR/USD**:

- **Dashboard** (`index.html`, hosted on GitHub Pages) — live price, 1-hour chart, indicator signal (BUY bias / SELL bias / WAIT), example stop-loss and take-profit, and position size based on your risk.
- **Background alerts** (GitHub Actions + Telegram) — messages your phone when a price target is hit or the signal flips, even when the dashboard is closed.

> Signals are mechanical readings of EMA, MACD, RSI and Bollinger Bands. They are not financial advice and will often be wrong. Use a stop loss on every trade and confirm prices on Capital.com.

---

## 1. Get a free price-data key (2 min)
1. Sign up at <https://twelvedata.com> → **API Keys** → copy your key.
2. Free plan: 8 calls/minute, 800/day.

## 2. Put the files on GitHub (5 min)
1. github.com → **New repository** → name it `gold-fx-signals` → **Public** → Create.
2. **Add file → Upload files** → drag in `index.html`, `alert.py`, `config.json`, `README.md`.
3. The workflow file must sit in a folder: **Add file → Create new file**, name it `.github/workflows/alerts.yml`, paste the contents of `alerts.yml`, commit.

## 3. Turn on the dashboard (GitHub Pages)
1. Repo **Settings → Pages** → Source: **Deploy from a branch** → Branch: `main` / `(root)` → Save.
2. After ~1 minute it is live at `https://<your-username>.github.io/gold-fx-signals/`.
3. Open it, paste your Twelve Data key, set your balance and risk %, click **Save & start**, then **Enable notifications**.

Your API key is saved only in your own browser, never in the repository.

## 4. Turn on phone alerts (Telegram)
1. In Telegram, message **@BotFather** → `/newbot` → follow the steps → copy the **bot token**.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the number after `"chat":{"id":` — that is your **chat ID**.
3. Repo **Settings → Secrets and variables → Actions → New repository secret**, add three:
   - `TWELVEDATA_KEY`
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. **Actions** tab → enable workflows → **Price alerts → Run workflow** to test.

## 5. Set your price targets
Edit `config.json` on GitHub (pencil icon), for example:

```json
{
  "signal_alerts": true,
  "symbols": {
    "XAU/USD": { "above": [4250], "below": [4100, 4050] },
    "EUR/USD": { "above": [1.1800], "below": [1.1550] }
  }
}
```
(The numbers above are placeholders — use your own levels.) An alert fires once when a target is crossed and re-arms if price moves back. Set `signal_alerts` to `false` to receive only target alerts.

---

## How "instant" is it?

| Method | Speed | Works when page closed |
|---|---|---|
| Capital.com app price alerts | Seconds | Yes — **use these for critical levels** |
| Dashboard (page open) | Every 60 s (slower in background tabs) | No |
| GitHub Actions → Telegram | Every 15 min, GitHub often adds 5–15 min delay | Yes |

GitHub's scheduler cannot be truly instant. For entries/exits that matter, set the same level as a price alert (or a limit/stop order) inside Capital.com.

## Credit budget (free plan, 800/day)
- Dashboard: 2 credits per poll + 2 per candle refresh (every 30 min). At 60 s polling ≈ 120 credits/hour of viewing.
- Actions: 2 credits per run × 96 runs/day ≈ 192/day (weekends skipped).
- If you hit the limit, raise the poll interval to 120–180 s.

## How the signal is scored (1-hour candles)
| Condition | Points |
|---|---|
| EMA20 above / below EMA50 | +1 / −1 |
| Price above / below EMA50 | +1 / −1 |
| MACD histogram positive / negative | +1 / −1 |
| Fresh MACD cross up / down | +1 / −1 |
| RSI < 30 / > 70 | +1 / −1 |
| Price below lower / above upper Bollinger band | +1 / −1 |

Score ≥ +3 → **BUY bias**, ≤ −3 → **SELL bias**, otherwise **WAIT**.
Example setup: stop = 1.5 × ATR, target = 3 × ATR (2:1 reward/risk). Position size = (balance × risk %) ÷ stop distance, assuming 1 unit = 1 oz gold / 1 EUR — confirm the unit size on Capital.com's deal ticket.

## Notes
- Capital.com quotes **EUR/USD** (not USD/EUR). The tool uses EUR/USD.
- Data-feed prices differ slightly from Capital.com's bid/ask; leave room for the spread.
- GitHub pauses scheduled workflows after 60 days with no repository activity — re-enable from the Actions tab if alerts stop.

---

## 6. Demo auto-trading on Capital.com (`trade.py`)

**Starts OFF and on DEMO.** Every order is sent with a stop loss and a take profit.

### Setup
1. Add these repo secrets (**Settings → Secrets and variables → Actions**):
   - `CAPITAL_API_KEY` — the API key you generated
   - `CAPITAL_IDENTIFIER` — your Capital.com login email
   - `CAPITAL_PASSWORD` — the **custom password** you set for the API key (not your login password)
2. **Actions → Price alerts and demo trading → Run workflow** with "Connection check only" ticked.
   Open the run log and confirm it shows your **demo** balance plus a price for `GOLD` and `EURUSD`.
   If an epic says NOT FOUND, the log lists the correct names; put them in `config.json → trading.epics`.
3. Turn it on: edit `config.json` and set `"trading": { "enabled": true, ... }`. From then on it runs every 15 minutes.

### What it does each run
- Reads 1-hour **closed** candles and calculates the same score as the dashboard.
- **BUY / SELL signal + no open position** → opens one trade:
  stop = 1.5 × ATR, target = 3 × ATR, size = (balance × `risk_pct`) ÷ stop distance, capped by `max_size`.
- Only one entry per signal. If the trade is stopped out, it waits for the signal to reset before trading again.
- Signal flips to the opposite side → closes the open trade (`close_on_opposite_signal`).
- Sends every open, close and rejection to Telegram.

### Built-in safety limits (`config.json → trading`)
| Setting | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Master switch, and your kill switch |
| `mode` | `demo` | `live` also needs the secret `CAPITAL_LIVE_CONFIRM` = `YES` |
| `risk_pct` | 1.0 | % of balance lost if the stop is hit |
| `max_size` | 1 oz gold / 10,000 EUR | Hard cap per order |
| `max_open_positions` | 2 | |
| `max_trades_per_day` | 4 | |
| `max_daily_loss_pct` | 3.0 | No new trades after this loss today |
| `max_spread_atr` | 0.3 | Skips trading when the spread is wide |
| `no_trade_hours_utc` | 12–15 | No new entries during US data releases (16:00–19:00 Dubai) |
| `no_trade_friday_after_utc` | 18 | No new trades before the weekend gap |

**To stop everything immediately:** set `enabled` to `false`, or disable the workflow in the Actions tab. Then close any open trades in the Capital.com app.

### Before you ever switch to live
Run demo for at least 4–6 weeks (around 30+ trades). Go live only if:
- The total result is positive after spreads and overnight fees.
- The worst losing streak would be acceptable with real money.
- You understand every trade it took.

Then set `mode` to `live`, add the `CAPITAL_LIVE_CONFIRM` secret, and start with `risk_pct` at 0.5.

Trade state (daily counters) is stored in `trade_state.json`. Price-alert state is stored in `state.json`.
