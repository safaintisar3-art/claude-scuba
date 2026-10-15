"""Settings loaded from environment variables (or a local .env file)."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _list(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [s.strip().upper() for s in value.split(",") if s.strip()]


@dataclass
class Settings:
    webhook_secret: str
    alpaca_key: str
    alpaca_secret: str
    live_trading: bool = False
    allowed_symbols: list[str] = field(default_factory=list)
    max_qty_per_order: int = 10
    max_position_value: float = 1000.0
    max_trades_per_day: int = 10
    max_daily_loss: float = 100.0
    trading_enabled: bool = True
    kill_switch_file: str = "STOP"

    @property
    def base_url(self) -> str:
        return LIVE_URL if self.live_trading else PAPER_URL


def load_settings() -> Settings:
    load_dotenv()
    secret = os.getenv("WEBHOOK_SECRET", "")
    if len(secret) < 16:
        raise RuntimeError("WEBHOOK_SECRET must be set and at least 16 characters long.")
    return Settings(
        webhook_secret=secret,
        alpaca_key=os.getenv("ALPACA_API_KEY", ""),
        alpaca_secret=os.getenv("ALPACA_API_SECRET", ""),
        live_trading=_bool("LIVE_TRADING", False),
        allowed_symbols=_list("ALLOWED_SYMBOLS"),
        max_qty_per_order=int(os.getenv("MAX_QTY_PER_ORDER", "10")),
        max_position_value=float(os.getenv("MAX_POSITION_VALUE", "1000")),
        max_trades_per_day=int(os.getenv("MAX_TRADES_PER_DAY", "10")),
        max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", "100")),
        trading_enabled=_bool("TRADING_ENABLED", True),
        kill_switch_file=os.getenv("KILL_SWITCH_FILE", "STOP"),
    )
