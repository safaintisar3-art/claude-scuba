"""Self-running trader: no TradingView needed.

Every CHECK_INTERVAL_SECONDS during market hours it:
  1. fetches the latest 1-minute price bars for each symbol in ALLOWED_SYMBOLS
  2. runs the strategy (bot/strategy.py)
  3. buys / sells through the same safety checks as the webhook bot
  4. sells everything FLATTEN_MINUTES_BEFORE_CLOSE minutes before the close

Run it:   python -m bot.autotrader
Test it:  python -m bot.autotrader --once     (one check, then exit)
Stop it:  Ctrl+C   (or create a file named STOP to block new buys)
"""

import argparse
import logging
import time
from datetime import datetime, timedelta

from .broker import AlpacaBroker, BrokerError
from .config import Settings, load_settings
from .risk import RiskManager, RiskRejected, TradeLog
from .strategy import signal

log = logging.getLogger("autotrader")


class AutoTrader:
    def __init__(self, settings: Settings, broker, trade_log: TradeLog):
        if not settings.allowed_symbols:
            raise ValueError("Set ALLOWED_SYMBOLS in .env to the tickers the bot should trade.")
        self.s = settings
        self.broker = broker
        self.trade_log = trade_log
        self.risk = RiskManager(settings, broker, trade_log)
        self.last_bar_time: dict[str, str] = {}  # so each new bar is acted on only once

    def tick(self) -> str:
        """One pass over all symbols. Returns a short status for logging/tests."""
        clock = self.broker.clock()
        if not clock["is_open"]:
            return "market closed"

        now = datetime.fromisoformat(clock["timestamp"])
        close = datetime.fromisoformat(clock["next_close"])
        if now >= close - timedelta(minutes=self.s.flatten_minutes_before_close):
            self.flatten()
            return "end of day: positions closed, no new trades"

        for symbol in self.s.allowed_symbols:
            try:
                self.check_symbol(symbol)
            except BrokerError as e:
                log.error("%s: broker error: %s", symbol, e)
        return "checked"

    def check_symbol(self, symbol: str) -> None:
        bars = self.broker.recent_bars(symbol, limit=self.s.slow_ema * 5)
        if not bars:
            return
        newest = bars[-1]["t"]
        if self.last_bar_time.get(symbol) == newest:
            return  # no new bar since last check
        self.last_bar_time[symbol] = newest

        sig = signal([float(b["c"]) for b in bars], self.s.fast_ema, self.s.slow_ema)
        held = self.broker.position_qty(symbol)

        if sig == "buy" and held == 0:
            try:
                self.risk.check_buy(symbol, self.s.trade_qty)
            except RiskRejected as e:
                log.info("%s: buy signal blocked: %s", symbol, e)
                return
            order = self.broker.submit_market_order(symbol, self.s.trade_qty, "buy")
            self.trade_log.record({"action": "buy", "symbol": symbol, "qty": self.s.trade_qty,
                                   "order_id": order.get("id"), "source": "autotrader"})
            log.info("%s: BUY %s", symbol, self.s.trade_qty)

        elif sig == "sell" and held > 0:
            self.broker.close_position(symbol)
            self.trade_log.record({"action": "close", "symbol": symbol, "qty": held,
                                   "source": "autotrader"})
            log.info("%s: SELL all (%s)", symbol, held)

    def flatten(self) -> None:
        for symbol in self.s.allowed_symbols:
            held = self.broker.position_qty(symbol)
            if held > 0:
                self.broker.close_position(symbol)
                self.trade_log.record({"action": "close", "symbol": symbol, "qty": held,
                                       "source": "autotrader-eod"})
                log.info("%s: end-of-day SELL all (%s)", symbol, held)

    def run(self) -> None:
        while True:
            try:
                log.info(self.tick())
            except Exception:
                log.exception("check failed; will retry next interval")
            time.sleep(self.s.check_interval_seconds)


def main():
    parser = argparse.ArgumentParser(description="Self-running EMA crossover day trader")
    parser.add_argument("--once", action="store_true", help="run one check and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings(require_webhook_secret=False)
    broker = AlpacaBroker(settings.base_url, settings.alpaca_key, settings.alpaca_secret)
    trader = AutoTrader(settings, broker, TradeLog())

    mode = "LIVE (real money)" if settings.live_trading else "PAPER (practice)"
    log.info("autotrader in %s mode | symbols %s | EMA %s/%s | %s shares per trade",
             mode, ",".join(settings.allowed_symbols), settings.fast_ema, settings.slow_ema,
             settings.trade_qty)

    if args.once:
        log.info(trader.tick())
    else:
        try:
            trader.run()
        except KeyboardInterrupt:
            log.info("stopped by user (open positions were NOT closed)")


if __name__ == "__main__":
    main()
