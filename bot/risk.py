"""Safety checks that every signal must pass before an order is sent.

Rules:
- Opening trades (buy) must pass every check.
- Exits (sell / close_all) are allowed even when limits are hit or the kill
  switch is on, so the bot can always get you OUT of a position.
"""

import json
import os
from datetime import datetime, timezone

from .config import Settings


class RiskRejected(Exception):
    pass


class TradeLog:
    """Append-only log of executed trades; also used to count today's trades."""

    def __init__(self, path: str = "trades.jsonl"):
        self.path = path

    def record(self, entry: dict) -> None:
        entry = {"time": datetime.now(timezone.utc).isoformat(), **entry}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def count_today(self) -> int:
        if not os.path.exists(self.path):
            return 0
        today = datetime.now(timezone.utc).date().isoformat()
        with open(self.path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip() and json.loads(line)["time"].startswith(today))


class RiskManager:
    def __init__(self, settings: Settings, broker, log: TradeLog):
        self.s = settings
        self.broker = broker
        self.log = log

    def kill_switch_on(self) -> bool:
        return not self.s.trading_enabled or os.path.exists(self.s.kill_switch_file)

    def check_symbol(self, symbol: str) -> None:
        if self.s.allowed_symbols and symbol not in self.s.allowed_symbols:
            raise RiskRejected(f"{symbol} is not in ALLOWED_SYMBOLS")

    def check_market_open(self) -> None:
        if not self.broker.is_market_open():
            raise RiskRejected("market is closed")

    def check_buy(self, symbol: str, qty: int) -> None:
        if self.kill_switch_on():
            raise RiskRejected("kill switch is on; new trades are blocked")
        self.check_symbol(symbol)
        if qty < 1 or qty > self.s.max_qty_per_order:
            raise RiskRejected(f"qty {qty} outside 1..{self.s.max_qty_per_order}")
        if self.log.count_today() >= self.s.max_trades_per_day:
            raise RiskRejected(f"daily trade limit ({self.s.max_trades_per_day}) reached")

        acct = self.broker.account()
        day_pnl = float(acct["equity"]) - float(acct["last_equity"])
        if day_pnl <= -self.s.max_daily_loss:
            raise RiskRejected(f"daily loss limit hit (today's P&L {day_pnl:.2f})")

        self.check_market_open()

        held = self.broker.position_qty(symbol)
        price = self.broker.latest_price(symbol)
        new_value = (held + qty) * price
        if new_value > self.s.max_position_value:
            raise RiskRejected(
                f"position would be worth {new_value:.2f}, above MAX_POSITION_VALUE {self.s.max_position_value:.2f}"
            )
