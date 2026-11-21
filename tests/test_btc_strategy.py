from bot.btc_strategy import Candle, Params, Position, atr, backtest, evaluate

P = Params(fast=5, slow=10, range_bars=5, atr_len=5)


def series(closes, wiggle=1.0):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append(Candle(i * 300, prev, max(prev, c) + wiggle, min(prev, c) - wiggle, c))
        prev = c
    return out


UP = [100 + i for i in range(20)]       # steady climb
DOWN = [100 - i for i in range(20)]     # steady fall


def test_atr():
    assert atr(series([100, 100, 100], wiggle=1), 5) == 2


def test_waits_without_enough_history():
    assert evaluate(series(UP[:5]), None, P).action == "WAIT"


def test_buy_on_breakout_in_uptrend():
    adv = evaluate(series(UP + [125]), None, P)
    assert adv.action == "BUY"
    assert adv.position.stop < 125 < adv.position.target
    assert "breakout" in adv.position.reason


def test_short_on_breakdown_in_downtrend():
    adv = evaluate(series(DOWN + [75]), None, P)
    assert adv.action == "SHORT"
    assert adv.position.target < 75 < adv.position.stop


def test_no_short_when_disabled():
    adv = evaluate(series(DOWN + [75]), None, Params(fast=5, slow=10, range_bars=5, atr_len=5, allow_short=False))
    assert adv.action == "WAIT"


def test_long_stop_hit():
    pos = Position("long", 120, 118, 124, "test", 0)
    candles = series(UP + [117])
    adv = evaluate(candles, pos, P)
    assert adv.action == "SELL" and adv.price == 118 and adv.position is None
    assert adv.pnl_pct < 0


def test_long_target_hit():
    pos = Position("long", 110, 105, 120, "test", 0)
    adv = evaluate(series(UP + [121]), pos, P)
    assert adv.action == "SELL" and adv.price == 120 and adv.pnl_pct > 0


def test_hold_keeps_position():
    pos = Position("long", 119, 100, 200, "test", 0)
    adv = evaluate(series(UP), pos, P)
    assert adv.action == "HOLD" and adv.position is pos


def test_short_closed_when_trend_turns_up():
    pos = Position("short", 110, 200, 50, "test", 0)
    adv = evaluate(series(UP), pos, P)
    assert adv.action == "COVER" and adv.position is None


def test_backtest_records_round_trips():
    closes = UP + [125, 126, 127] + [127 - 3 * i for i in range(15)]
    res = backtest(series(closes), P, fee_pct=0.1)
    assert res.trades, "expected at least one completed trade"
    assert all(t["side"] in ("long", "short") for t in res.trades)
    assert "trades" in res.summary()


class FakeResp:
    def __init__(self, rows):
        self.rows = rows

    def raise_for_status(self):
        pass

    def json(self):
        return self.rows


class FakeSession:
    """Serves Coinbase-style rows (newest first) for whatever window is asked for."""

    def __init__(self, now_bar):
        self.now_bar = now_bar  # start time of the still-forming bar
        self.calls = 0

    def get(self, url, timeout, params):
        from datetime import datetime
        self.calls += 1
        g = params["granularity"]
        start = int(datetime.fromisoformat(params["start"]).timestamp())
        end = int(datetime.fromisoformat(params["end"]).timestamp())
        rows = [[t, 99.0, 101.0, 100.0, 100.0 + t / g, 1.0]
                for t in range(start, min(end, self.now_bar) + 1, g)]
        rows.append([self.now_bar, 0, 0, 0, 0, 0])  # unfinished bar sneaks in
        return FakeResp(sorted(rows, reverse=True))


def test_fetch_candles_paginates_and_drops_unfinished_bar(monkeypatch):
    import bot.btc_signals as bs
    now = 1_800_000_000
    monkeypatch.setattr(bs.time, "time", lambda: now)
    sess = FakeSession(now // 300 * 300)
    candles = bs.fetch_candles("BTC-USD", 300, 450, session=sess)
    assert len(candles) == 450 and sess.calls == 2
    ts = [c.t for c in candles]
    assert ts == sorted(ts) and len(set(ts)) == 450
    assert ts[-1] == sess.now_bar - 300  # newest *closed* bar


from bot.btc_strategy import evaluate_daily_breakout  # noqa: E402


def days(closes):
    return [Candle(i * 86400, c, c + 1, c - 1, c) for i, c in enumerate(closes)]


def test_daily_breakout_buy_hold_sell():
    flat = [100.0] * 60
    adv = evaluate_daily_breakout(days(flat + [105]), None, 55, 10)
    assert adv.action == "BUY" and adv.position.side == "long"
    pos = adv.position
    climb = flat + [105, 108, 112]
    adv = evaluate_daily_breakout(days(climb), pos, 55, 10)
    assert adv.action == "HOLD" and adv.position is pos
    adv = evaluate_daily_breakout(days(climb + [95]), pos, 55, 10)
    assert adv.action == "SELL" and adv.position is None and adv.pnl_pct < 0


def test_daily_breakout_waits_inside_range():
    assert evaluate_daily_breakout(days([100.0] * 60 + [100.5]), None, 55, 10).action == "WAIT"
    assert evaluate_daily_breakout(days([100.0] * 10), None, 55, 10).action == "WAIT"
