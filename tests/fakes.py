class FakeBroker:
    """Stands in for AlpacaBroker in tests; records orders instead of sending them."""

    def __init__(self):
        self.market_open = True
        self.now = "2026-10-14T11:00:00-04:00"
        self.next_close = "2026-10-14T16:00:00-04:00"
        self.positions = {}
        self.bars = {}
        self.price = 100.0
        self.equity = 10_000.0
        self.last_equity = 10_000.0
        self.orders = []
        self.closed_all = False

    def account(self):
        return {"equity": str(self.equity), "last_equity": str(self.last_equity)}

    def clock(self):
        return {"is_open": self.market_open, "timestamp": self.now, "next_close": self.next_close}

    def is_market_open(self):
        return self.market_open

    def recent_bars(self, symbol, limit=100, timeframe="1Min"):
        return self.bars.get(symbol, [])[-limit:]

    def position_qty(self, symbol):
        return self.positions.get(symbol, 0.0)

    def latest_price(self, symbol):
        return self.price

    def submit_market_order(self, symbol, qty, side):
        self.orders.append((symbol, qty, side))
        if side == "buy":
            self.positions[symbol] = self.positions.get(symbol, 0) + qty
        return {"id": f"order-{len(self.orders)}"}

    def close_position(self, symbol):
        self.orders.append((symbol, self.positions.pop(symbol), "close"))
        return {"id": "close"}

    def close_all_positions(self):
        self.closed_all = True
