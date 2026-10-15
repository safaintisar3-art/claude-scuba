import pytest
from fakes import FakeBroker

from bot.autotrader import AutoTrader
from bot.config import Settings
from bot.risk import TradeLog
from bot.strategy import ema, signal

# Prices that drift down, then jump up on the last bar -> fast EMA crosses above slow.
CROSS_UP = [100 - i * 0.1 for i in range(40)] + [110]
# Prices that drift up, then drop on the last bar -> fast EMA crosses below slow.
CROSS_DOWN = [100 + i * 0.1 for i in range(40)] + [90]
FLAT = [100.0] * 41


def bars(closes, start_minute=0):
    return [{"t": f"2026-10-14T14:{(start_minute + i) % 60:02d}:00Z", "c": c} for i, c in enumerate(closes)]


def test_ema_matches_known_values():
    assert ema([1, 2, 3], 3) == [1, 1.5, 2.25]


def test_signal():
    assert signal(CROSS_UP, 9, 21) == "buy"
    assert signal(CROSS_DOWN, 9, 21) == "sell"
    assert signal(FLAT, 9, 21) is None
    assert signal([100] * 5, 9, 21) is None  # not enough history


@pytest.fixture
def trader(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        webhook_secret="", alpaca_key="k", alpaca_secret="s",
        allowed_symbols=["SPY"], max_position_value=1000, trade_qty=2,
    )
    broker = FakeBroker()
    return AutoTrader(settings, broker, TradeLog(str(tmp_path / "trades.jsonl"))), broker


def test_buys_on_cross_up(trader):
    t, broker = trader
    broker.bars["SPY"] = bars(CROSS_UP)
    assert t.tick() == "checked"
    assert broker.orders == [("SPY", 2, "buy")]


def test_does_not_buy_twice_on_same_bar(trader):
    t, broker = trader
    broker.bars["SPY"] = bars(CROSS_UP)
    t.tick()
    broker.positions.clear()  # even if the position were gone, the same bar isn't re-used
    t.tick()
    assert broker.orders == [("SPY", 2, "buy")]


def test_does_not_add_when_already_holding(trader):
    t, broker = trader
    broker.positions["SPY"] = 2
    broker.bars["SPY"] = bars(CROSS_UP)
    t.tick()
    assert broker.orders == []


def test_sells_on_cross_down(trader):
    t, broker = trader
    broker.positions["SPY"] = 2
    broker.bars["SPY"] = bars(CROSS_DOWN)
    t.tick()
    assert broker.orders == [("SPY", 2, "close")]


def test_risk_limits_still_apply(trader, tmp_path):
    t, broker = trader
    (tmp_path / "STOP").write_text("")
    broker.bars["SPY"] = bars(CROSS_UP)
    t.tick()
    assert broker.orders == []


def test_nothing_happens_when_market_closed(trader):
    t, broker = trader
    broker.market_open = False
    broker.bars["SPY"] = bars(CROSS_UP)
    assert t.tick() == "market closed"
    assert broker.orders == []


def test_flattens_before_close_and_stops_buying(trader):
    t, broker = trader
    broker.now = "2026-10-14T15:55:00-04:00"  # 5 min before 16:00 close
    broker.positions["SPY"] = 2
    broker.bars["SPY"] = bars(CROSS_UP)
    assert "end of day" in t.tick()
    assert broker.orders == [("SPY", 2, "close")]


def test_requires_symbols(tmp_path):
    with pytest.raises(ValueError):
        AutoTrader(Settings(webhook_secret="", alpaca_key="k", alpaca_secret="s"),
                   FakeBroker(), TradeLog(str(tmp_path / "t.jsonl")))
