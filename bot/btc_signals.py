"""BTC signal bot: tells you when to buy, sell or wait. It never places trades.

Two modes (set BTC_MODE in .env):
  daily  (default) slow trend breakout on daily candles. The only approach that held up
                   in walk-forward testing; expect a few signals per year.
  fast             the original 5-minute rules. Lost money in testing; kept for comparison.

Prices come from Coinbase's free public data (BTC-USD, no account or key needed).
Kalshi's BTC perp tracks the same market, so levels will be very close but not identical.

Run it:
    python -m bot.btc_signals              # watch live, alert on every new recommendation
    python -m bot.btc_signals --once       # print the current recommendation and exit
    python -m bot.btc_signals --backtest   # replay the rules over history

Phone alerts (optional, free): install the "ntfy" app, subscribe to a topic name that
only you know (e.g. btc-alerts-<random letters>), and put it in .env as NTFY_TOPIC.
"""

import argparse
import json
import logging
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import requests
import truststore
from dotenv import load_dotenv

from .btc_strategy import Candle, Params, Position, backtest, evaluate, evaluate_daily_breakout, min_bars

truststore.inject_into_ssl()  # use the computer's certificate store (fixes SSL errors on Windows)

log = logging.getLogger("btc_signals")

COINBASE_URL = "https://api.exchange.coinbase.com/products/{product}/candles"
VALID_GRANULARITIES = (60, 300, 900, 3600, 21600, 86400)
STATE_FILE = Path("btc_signal_state.json")  # replaced per mode in main()


def fetch_candles(product: str, granularity: int, count: int, session=requests) -> list[Candle]:
    """Closed candles, oldest first. Coinbase returns at most 300 per request, newest first,
    as [time, low, high, open, close, volume]."""
    if granularity not in VALID_GRANULARITIES:
        raise ValueError(f"granularity must be one of {VALID_GRANULARITIES}")
    end = int(time.time()) // granularity * granularity  # start of the still-forming bar
    by_time: dict[int, Candle] = {}
    while len(by_time) < count:
        start = end - min(300, count - len(by_time)) * granularity
        resp = session.get(COINBASE_URL.format(product=product), timeout=15, params={
            "granularity": granularity,
            "start": datetime.fromtimestamp(start, timezone.utc).isoformat(),
            "end": datetime.fromtimestamp(end - 1, timezone.utc).isoformat(),
        })
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        for t, low, high, op, close, _vol in rows:
            if t < end:  # drop the unfinished bar if Coinbase includes it
                by_time[int(t)] = Candle(int(t), float(op), float(high), float(low), float(close))
        end = start
    return [by_time[t] for t in sorted(by_time)][-count:]


def notify(topic: str, title: str, message: str) -> None:
    if not topic:
        return
    try:
        requests.post(f"https://ntfy.sh/{topic}", data=message.encode(), timeout=10,
                      headers={"Title": title, "Tags": "chart_with_upwards_trend"})
    except requests.RequestException as e:
        log.warning("phone alert failed: %s", e)


def load_position() -> Position | None:
    try:
        data = json.loads(STATE_FILE.read_text())
        return Position(**data) if data else None
    except (FileNotFoundError, ValueError, TypeError):
        return None


def save_position(pos: Position | None) -> None:
    STATE_FILE.write_text(json.dumps(asdict(pos) if pos else None))


def params_from_env() -> Params:
    return Params(
        fast=int(os.getenv("BTC_FAST_EMA", "20")),
        slow=int(os.getenv("BTC_SLOW_EMA", "50")),
        range_bars=int(os.getenv("BTC_RANGE_BARS", "24")),
        stop_atr=float(os.getenv("BTC_STOP_ATR", "1.5")),
        reward_risk=float(os.getenv("BTC_REWARD_RISK", "2")),
        allow_short=os.getenv("BTC_ALLOW_SHORT", "true").lower() in ("1", "true", "yes", "on"),
    )


def fmt_time(t: int) -> str:
    return datetime.fromtimestamp(t).strftime("%m-%d %H:%M")


def main():
    parser = argparse.ArgumentParser(description="BTC buy/sell recommendations (no trading)")
    parser.add_argument("--once", action="store_true", help="print the current advice and exit")
    parser.add_argument("--backtest", action="store_true", help="replay the rules over recent history")
    parser.add_argument("--bars", type=int, default=1000, help="history length for --backtest")
    parser.add_argument("--fee", type=float, default=0.1, help="round-trip fee %% for --backtest")
    parser.add_argument("--reset", action="store_true", help="forget the tracked position")
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    global STATE_FILE
    p = params_from_env()
    product = os.getenv("BTC_PRODUCT", "BTC-USD")
    mode = os.getenv("BTC_MODE", "daily").lower()
    topic = os.getenv("NTFY_TOPIC", "")
    coin = product.split("-")[0]
    if mode == "daily":
        gran, history, poll = 86400, 80, 600
        entry_days = int(os.getenv("BTC_ENTRY_DAYS", "55"))
        exit_days = int(os.getenv("BTC_EXIT_DAYS", "10"))
        evaluator = lambda cs, pos: evaluate_daily_breakout(cs, pos, entry_days, exit_days)  # noqa: E731
        start = entry_days + 1
        label = f"daily breakout ({entry_days}-day high in, {exit_days}-day low out)"
        STATE_FILE = Path(f"btc_signal_state_daily_{coin}.json")
    else:
        gran, history, poll = int(os.getenv("BTC_GRANULARITY", "300")), min_bars(p) + 100, 30
        evaluator = lambda cs, pos: evaluate(cs, pos, p)  # noqa: E731
        start = min_bars(p)
        label = f"fast {gran // 60}-min rules (lost money in testing)"
        STATE_FILE = Path(f"btc_signal_state_fast_{coin}.json")
    bar_min = gran // 60
    stamp = (lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d")) if mode == "daily" else fmt_time

    if args.reset:
        save_position(None)

    if args.backtest:
        bars = args.bars if mode != "daily" or args.bars != 1000 else 3000
        candles = fetch_candles(product, gran, bars)
        res = backtest(candles, None, args.fee, evaluator=evaluator, start=start)
        print(f"{product} {label}, {stamp(candles[0].t)} to {stamp(candles[-1].t)}")
        for tr in res.trades:
            print(f"  {tr['side']:5} {stamp(tr['opened_t'])} @ {tr['entry']:>9,.0f} -> "
                  f"{stamp(tr['closed_t'])} @ {tr['exit']:>9,.0f}  {tr['pnl_pct'] - args.fee:+.2f}%  "
                  f"({tr['reason']})")
        print(res.summary())
        return

    pos = load_position()
    last_bar = None
    log.info("watching %s | %s | alerts to phone: %s", product, label,
             "on" if topic else "off (set NTFY_TOPIC)")
    while True:
        try:
            candles = fetch_candles(product, gran, history)
            if candles and candles[-1].t != last_bar:
                last_bar = candles[-1].t
                adv = evaluator(candles, pos)
                line = f"{adv.action:5} {coin} {adv.price:,.0f} | {adv.message}"
                if adv.pnl_pct is not None:
                    line += f" ({adv.pnl_pct:+.2f}% before fees/leverage)"
                log.info(line)
                if adv.action not in ("HOLD", "WAIT"):
                    print("\a", end="", flush=True)  # terminal beep
                    notify(topic, f"{coin}: {adv.action}", line)
                pos = adv.position
                save_position(pos)
        except (requests.RequestException, ValueError) as e:
            log.warning("price check failed, retrying: %s", e)
        if args.once:
            return
        try:
            time.sleep(poll)
        except KeyboardInterrupt:
            log.info("stopped")
            return


if __name__ == "__main__":
    main()
