# claude-scuba: automatic day trading bot (Alpaca)

A bot that buys and sells for you while you're away from the screen. There are two ways
to run it:

| | **A. Self-running** (simplest) | **B. TradingView alerts** |
|---|---|---|
| Who decides when to trade | the bot's own Python strategy | your TradingView strategy |
| Needs paid TradingView | no | yes |
| Needs a public web address | no | yes (ngrok or a server) |
| Start it with | `python -m bot.autotrader` | `python -m bot.server` |

Both use the same Alpaca account, the same `.env` settings and the same safety limits.

## A. Self-running mode (no TradingView)

```bash
python -m bot.autotrader --once   # one check, then exit (good first test)
python -m bot.autotrader          # keep running; Ctrl+C to stop
```

During market hours it checks every `CHECK_INTERVAL_SECONDS` (default 60). For each ticker
in `ALLOWED_SYMBOLS`, it pulls the latest 1-minute prices from Alpaca's free (IEX) data feed
and runs the strategy in [`bot/strategy.py`](bot/strategy.py):

- **Buy** `TRADE_QTY` shares when the 9-period average crosses above the 21-period average
  and you don't already hold the stock.
- **Sell everything** in that stock when the averages cross back down.
- **Sell everything** `FLATTEN_MINUTES_BEFORE_CLOSE` minutes before the market closes, so
  nothing is held overnight.

All the safety limits below still apply. Stopping the bot with Ctrl+C does **not** sell
what you hold. Close positions in the Alpaca dashboard if you need to.
The computer must stay on and awake during market hours (9:30–16:00 New York time).

## B. TradingView mode

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

## C. BTC signal bot (advice only, for Kalshi or any exchange)

Tells you **when to buy or sell** Bitcoin. It **never places trades**: you make the trade
yourself in Kalshi (or anywhere). No account or API key needed. Prices come from Coinbase's
free BTC-USD data, which tracks the same market as Kalshi's BTC perp.

```bash
python -m bot.btc_signals --backtest   # replay the rules over ~8 years
python -m bot.btc_signals --once       # current recommendation, then exit
python -m bot.btc_signals              # keep watching; phone alert on every BUY / SELL
python -m bot.btc_signals --reset      # forget the position the bot thinks you hold
```

**Default mode: daily breakout** (`BTC_MODE=daily`). This was the winner of the walk-forward search below:

| Signal | When |
|---|---|
| **BUY** | a day closes above the highest price of the previous **55 days** |
| **SELL** | a day closes below the lowest price of the previous **10 days** (this level rises as the trend continues) |
| **WAIT / HOLD** | anything else |

It trades a **few times a year**, sits out downtrends, and makes its money from a few
big trends. Half its trades lose, usually by 2-13%. It is a slow, swing-trading strategy,
not day trading, and it's built for **no or low leverage**.

`BTC_MODE=fast` switches back to the original 5-minute rules. Those **lost money** in testing
and are kept only for comparison.

**Phone alerts:** install the free **ntfy** app, subscribe to a topic name nobody would
guess, and set `NTFY_TOPIC` to the same name in `.env`.

### Does it actually work? (walk-forward test, Nov 2026)

We tested the rules and two machine-learning models (logistic regression and boosted
trees) the honest way: **train on a past window, then test on the next window the model
has never seen, and roll forward**, over one year of real BTC prices (270 unseen days).

| Approach | Unseen-data result, 0.1% fees per trade |
|---|---|
| Bot's current rules, 5-min bars (56 days) | 898 trades, 30% wins, **-98%** (sum of trade %, no leverage) |
| Bot's rules re-tuned every window, 15-min bars | 424 trades, 28% wins, **-59%** |
| Logistic regression, best setting | accuracy 52% vs 50% coin flip, **loses after fees** |
| Boosted trees, best setting | accuracy 52% vs 50% coin flip, **loses after fees** |

The models are only slightly better than a coin flip, and fees cost more than that small
edge in every setup we tried.

**Wider search** (`python -m research.strategy_lab`): 6 strategy families (trend, crossover,
momentum, breakout, mean reversion, volatility-filtered trend) on 15-min, 1-hour, 6-hour and
daily bars, all walk-forward, with the last 90 days locked away until the end.

- Every 15-minute and 1-hour strategy lost money on unseen data.
- Daily trend strategies did best. Daily breakout made **+38.8%/year vs +33.9% for
  buy-and-hold (2018-2026)**, with a smaller worst drop (-51% vs -77%).
- On the locked 90-day holdout it **lost 9.1% while buy-and-hold lost 24.9%** (3 trades).
  That's a small sample, and the gain over buy-and-hold is modest.

**Use the signals as a second opinion, not a guarantee.**
Re-run it yourself: `pip install -r research/requirements.txt`, `python research/fetch_history.py`,
`python -m research.walk_forward_rules rules`, `python research/walk_forward_ml.py`.

## What you need

1. **Python 3.11+**. On Windows: `winget install Python.Python.3.12`
2. **An Alpaca account.** Use the *Paper Trading* API keys from the dashboard.
3. *(TradingView mode only)* **A paid TradingView plan.** Webhook alerts need a paid plan (Essential or higher).
4. *(TradingView mode only)* **A public HTTPS address** for the bot. TradingView only sends webhooks to ports
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
