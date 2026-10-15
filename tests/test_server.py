import pytest

from bot.config import Settings
from bot.risk import TradeLog
from bot.server import create_app

SECRET = "test-secret-1234567890"


class FakeBroker:
    def __init__(self):
        self.market_open = True
        self.positions = {}
        self.price = 100.0
        self.equity = 10_000.0
        self.last_equity = 10_000.0
        self.orders = []
        self.closed_all = False

    def account(self):
        return {"equity": str(self.equity), "last_equity": str(self.last_equity)}

    def is_market_open(self):
        return self.market_open

    def position_qty(self, symbol):
        return self.positions.get(symbol, 0.0)

    def latest_price(self, symbol):
        return self.price

    def submit_market_order(self, symbol, qty, side):
        self.orders.append((symbol, qty, side))
        return {"id": f"order-{len(self.orders)}"}

    def close_position(self, symbol):
        self.orders.append((symbol, self.positions.pop(symbol), "close"))
        return {"id": "close"}

    def close_all_positions(self):
        self.closed_all = True


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # keeps trades.jsonl and STOP inside the temp dir
    settings = Settings(
        webhook_secret=SECRET, alpaca_key="k", alpaca_secret="s",
        allowed_symbols=["AAPL", "SPY"], max_qty_per_order=5,
        max_position_value=1000, max_trades_per_day=3, max_daily_loss=100,
    )
    broker = FakeBroker()
    app = create_app(settings, broker, TradeLog(str(tmp_path / "trades.jsonl")))
    return app.test_client(), broker, settings


def send(client, **body):
    body.setdefault("secret", SECRET)
    return client.post("/webhook", json=body)


def test_buy_places_order(setup):
    client, broker, _ = setup
    r = send(client, symbol="NASDAQ:AAPL", action="buy", qty=2)
    assert r.json["status"] == "submitted"
    assert broker.orders == [("AAPL", 2, "buy")]


def test_bad_secret_rejected(setup):
    client, broker, _ = setup
    r = send(client, secret="wrong", symbol="AAPL", action="buy", qty=1)
    assert r.status_code == 401
    assert broker.orders == []


def test_symbol_not_allowed(setup):
    client, broker, _ = setup
    r = send(client, symbol="TSLA", action="buy", qty=1)
    assert r.json["status"] == "rejected"
    assert broker.orders == []


def test_qty_over_limit(setup):
    client, broker, _ = setup
    assert send(client, symbol="AAPL", action="buy", qty=6).json["status"] == "rejected"
    assert broker.orders == []


def test_position_value_limit(setup):
    client, broker, _ = setup
    broker.positions["AAPL"] = 8  # 8 + 3 shares at $100 = $1100 > $1000
    assert send(client, symbol="AAPL", action="buy", qty=3).json["status"] == "rejected"


def test_daily_trade_limit(setup):
    client, broker, _ = setup
    for _ in range(3):
        assert send(client, symbol="SPY", action="buy", qty=1).json["status"] == "submitted"
    r = send(client, symbol="SPY", action="buy", qty=1)
    assert r.json["status"] == "rejected"
    assert "trade limit" in r.json["reason"]


def test_daily_loss_limit(setup):
    client, broker, _ = setup
    broker.equity = 9_850.0
    r = send(client, symbol="AAPL", action="buy", qty=1)
    assert "loss limit" in r.json["reason"]


def test_market_closed(setup):
    client, broker, _ = setup
    broker.market_open = False
    assert send(client, symbol="AAPL", action="buy", qty=1).json["reason"] == "market is closed"


def test_kill_switch_blocks_buys_but_allows_exits(setup, tmp_path):
    client, broker, _ = setup
    (tmp_path / "STOP").write_text("")
    broker.positions["AAPL"] = 4
    assert send(client, symbol="AAPL", action="buy", qty=1).json["status"] == "rejected"
    assert send(client, symbol="AAPL", action="close").json["status"] == "submitted"
    assert broker.orders == [("AAPL", 4, "close")]


def test_sell_never_goes_short(setup):
    client, broker, _ = setup
    broker.positions["AAPL"] = 2
    send(client, symbol="AAPL", action="sell", qty=10)
    assert broker.orders == [("AAPL", 2, "sell")]


def test_sell_without_position_ignored(setup):
    client, broker, _ = setup
    assert send(client, symbol="AAPL", action="sell", qty=1).json["status"] == "ignored"
    assert broker.orders == []


def test_close_all(setup):
    client, broker, _ = setup
    assert send(client, action="close_all").json["status"] == "closed_all"
    assert broker.closed_all


def test_unknown_action_and_bad_qty(setup):
    client, _, _ = setup
    assert send(client, symbol="AAPL", action="moon").status_code == 400
    assert send(client, symbol="AAPL", action="buy", qty="lots").status_code == 400


def test_health(setup):
    client, _, _ = setup
    assert client.get("/health").json == {"ok": True, "live": False, "kill_switch": False}
