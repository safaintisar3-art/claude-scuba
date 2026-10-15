# claude-scuba: TradingView → Alpaca day trading bot

A bot that places trades automatically when your TradingView alerts fire, so
it keeps working while you're away from the screen.

```
TradingView strategy ──alert webhook──▶  this bot (Flask)  ──API──▶  Alpaca broker
  (decides WHEN)                          (safety checks)            (places the order)
```

TradingView itself cannot place orders with a broker. It only sends alerts. This bot
receives those alerts, runs safety checks, and sends the order to
[Alpaca](https://alpaca.markets), a broker with a free API and a **paper trading**
(simulated money) mode. **The bot runs in paper mode by default.**

> ⚠️ Automated trading can lose real money quickly, through bugs, bad strategies,
> outages or fast markets. The included strategy is only a template, not advice.
> Run on paper for weeks before considering live mode.

## What you need

1. **Python 3.11+**. On Windows: `winget install Python.Python.3.12`
2. **An Alpaca account.** Use the *Paper Trading* API keys from the dashboard.
3. **A paid TradingView plan.** Webhook alerts need a paid plan (Essential or higher).
4. **A public HTTPS address** for the bot. TradingView only sends webhooks to ports
   80/443. For testing, use [ngrok](https://ngrok.com): `ngrok http 8000`.
   To keep the bot running while your computer is off, deploy it to a small cloud
   server (Railway, Render, a VPS, etc.).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # then edit .env
python -m bot.server
```

Check that it's running: `http://localhost:8000/health`

## Connect TradingView

1. Open the Pine Editor, paste in [`strategies/ema_cross.pine`](strategies/ema_cross.pine) and add it to a chart.
2. In the strategy settings, set **Webhook secret** to the same value as `WEBHOOK_SECRET`.
3. Create an alert. Set Condition to the strategy, then **Order fills only**.
   - **Webhook URL:** `https://<your-ngrok-or-server-address>/webhook`
   - **Message:** `{{strategy.order.alert_message}}`

You can also send hand-written alerts. Use any indicator with this message:

```json
{"secret": "your-secret", "symbol": "{{ticker}}", "action": "buy", "qty": 1}
```

| action      | what it does                                              |
|-------------|-----------------------------------------------------------|
| `buy`       | buy `qty` shares (all safety checks apply)                |
| `sell`      | sell up to `qty` shares of an existing long (never shorts)|
| `close`     | sell the entire position in `symbol`                      |
| `close_all` | sell everything, e.g. as an end-of-day alert              |

## Safety features

These are all set in `.env`:

- **Paper trading by default.** Nothing real happens until `LIVE_TRADING=true`.
- **Secret check.** Alerts without the right secret are rejected.
- **Symbol allow-list:** `ALLOWED_SYMBOLS`
- **Size limits:** `MAX_QTY_PER_ORDER`, `MAX_POSITION_VALUE`
- **Daily limits:** `MAX_TRADES_PER_DAY`, `MAX_DAILY_LOSS`. Once a limit is hit, new buys stop for the day.
- **Kill switch.** To block all new buys instantly, create an empty file named `STOP` in the
  bot folder, or set `TRADING_ENABLED=false`.
  Exits (`sell`, `close`, `close_all`) always go through, so you can still get out.
- **Long only.** The bot never short sells.
- **Trade log.** Every executed trade is appended to `trades.jsonl`.

## Things to know

- **Pattern Day Trader rule (US):** a margin account under $25,000 is limited to
  3 day trades in any 5 business days. Alpaca enforces this. A cash account avoids
  the rule but has to wait for settlement before reusing money.
- Alerts can arrive late or be missed, for example during TradingView outages or
  while your server is down. Check your positions in the Alpaca dashboard regularly.

## Tests

```bash
pytest
```
