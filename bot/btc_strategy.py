"""BTC buy/sell recommendation rules (no trading, advice only).

The rules, in plain words:

* **Trend** comes from two moving averages of the closing price: fast (default 20 bars)
  above slow (default 50 bars) = uptrend, below = downtrend.
* **Go long** in an uptrend when either
    - *breakout*: the bar closes above the highest high of the previous `range_bars` bars, or
    - *pullback*: the bar dipped to the fast average and closed back above it.
* **Go short** is the mirror image in a downtrend (if shorts are allowed).
* **Every entry gets a stop and a target**: stop = `stop_atr` x ATR away from the entry,
  target = `reward_risk` x that distance on the other side.
* **Exit** when the stop or target is hit, or when the trend flips against the position.

ATR (average true range) is how far price typically moves in one bar, so stops are
wider when the market is jumpy and tighter when it is calm.

This is a simple, mechanical rule set. It is not a forecast and it will have losing
streaks. Use `python -m bot.btc_signals --backtest` to see how it did recently.
"""

from dataclasses import dataclass, field

from .strategy import ema


@dataclass
class Candle:
    t: int  # unix seconds, start of the bar
    open: float
    high: float
    low: float
    close: float


@dataclass
class Params:
    fast: int = 20
    slow: int = 50
    range_bars: int = 24
    atr_len: int = 14
    stop_atr: float = 1.5
    reward_risk: float = 2.0
    allow_short: bool = True


@dataclass
class Position:
    side: str  # "long" or "short"
    entry: float
    stop: float
    target: float
    reason: str
    opened_t: int


@dataclass
class Advice:
    action: str  # "BUY", "SHORT", "SELL" (close long), "COVER" (close short), "HOLD", "WAIT"
    price: float
    message: str
    position: Position | None = None
    pnl_pct: float | None = None  # set on exits
    extras: dict = field(default_factory=dict)


def atr(candles: list[Candle], length: int) -> float:
    trs = []
    for prev, c in zip(candles, candles[1:]):
        trs.append(max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close)))
    if not trs:
        return 0.0
    window = trs[-length:]
    return sum(window) / len(window)


def min_bars(p: Params) -> int:
    return max(p.slow, p.range_bars, p.atr_len) + 2


def _open(side: str, price: float, a: float, p: Params, reason: str, t: int) -> Position:
    risk = p.stop_atr * a
    if side == "long":
        return Position(side, price, price - risk, price + p.reward_risk * risk, reason, t)
    return Position(side, price, price + risk, price - p.reward_risk * risk, reason, t)


def _pnl_pct(pos: Position, exit_price: float) -> float:
    move = (exit_price - pos.entry) / pos.entry * 100
    return move if pos.side == "long" else -move


def evaluate(candles: list[Candle], pos: Position | None, p: Params) -> Advice:
    """Look at closed candles (oldest first) and the current recommended position,
    and say what to do now. Uses only finished bars, so it never peeks ahead."""
    if len(candles) < min_bars(p):
        return Advice("WAIT", candles[-1].close if candles else 0.0,
                      f"Need {min_bars(p)} bars of history, have {len(candles)}.", pos)

    closes = [c.close for c in candles]
    fast = ema(closes, p.fast)[-1]
    slow = ema(closes, p.slow)[-1]
    a = atr(candles, p.atr_len)
    bar = candles[-1]
    prior = candles[-1 - p.range_bars:-1]
    range_hi = max(c.high for c in prior)
    range_lo = min(c.low for c in prior)
    up, down = fast > slow, fast < slow
    extras = {"fast_ema": fast, "slow_ema": slow, "atr": a,
              "range_high": range_hi, "range_low": range_lo,
              "trend": "up" if up else "down" if down else "flat"}

    # 1) Manage an open position first.
    if pos is not None:
        close_word = "SELL" if pos.side == "long" else "COVER"
        if pos.side == "long":
            hit_stop, hit_target, flipped = bar.low <= pos.stop, bar.high >= pos.target, down
        else:
            hit_stop, hit_target, flipped = bar.high >= pos.stop, bar.low <= pos.target, up
        if hit_stop:  # if both were touched in one bar, assume the worse one happened
            return Advice(close_word, pos.stop, f"Stop hit at {pos.stop:,.0f}. Close the {pos.side}.",
                          None, _pnl_pct(pos, pos.stop), extras)
        if hit_target:
            return Advice(close_word, pos.target, f"Target hit at {pos.target:,.0f}. Take profit on the {pos.side}.",
                          None, _pnl_pct(pos, pos.target), extras)
        if flipped:
            return Advice(close_word, bar.close, f"Trend flipped {extras['trend']}. Close the {pos.side}.",
                          None, _pnl_pct(pos, bar.close), extras)
        return Advice("HOLD", bar.close,
                      f"Keep the {pos.side}. Stop {pos.stop:,.0f}, target {pos.target:,.0f}.",
                      pos, _pnl_pct(pos, bar.close), extras)

    # 2) Flat: look for a new entry.
    if up:
        reason = None
        if bar.close > range_hi:
            reason = f"breakout above {range_hi:,.0f}"
        elif bar.low <= fast < bar.close:
            reason = f"pullback to the {p.fast}-bar average held"
        if reason:
            new = _open("long", bar.close, a, p, reason, bar.t)
            return Advice("BUY", bar.close,
                          f"Uptrend + {reason}. Buy ~{bar.close:,.0f}, stop {new.stop:,.0f}, target {new.target:,.0f}.",
                          new, None, extras)
    if down and p.allow_short:
        reason = None
        if bar.close < range_lo:
            reason = f"breakdown below {range_lo:,.0f}"
        elif bar.high >= fast > bar.close:
            reason = f"bounce to the {p.fast}-bar average rejected"
        if reason:
            new = _open("short", bar.close, a, p, reason, bar.t)
            return Advice("SHORT", bar.close,
                          f"Downtrend + {reason}. Short ~{bar.close:,.0f}, stop {new.stop:,.0f}, target {new.target:,.0f}.",
                          new, None, extras)

    return Advice("WAIT", bar.close,
                  f"No setup. Trend {extras['trend']}, range {range_lo:,.0f}-{range_hi:,.0f}.", None, None, extras)


@dataclass
class BacktestResult:
    trades: list[dict]
    fee_pct: float

    @property
    def net_returns(self) -> list[float]:
        return [t["pnl_pct"] - self.fee_pct for t in self.trades]

    def summary(self) -> str:
        n = len(self.trades)
        if n == 0:
            return "No trades in this period."
        r = self.net_returns
        wins = sum(1 for x in r if x > 0)
        return (f"{n} trades | {wins} wins, {n - wins} losses ({wins / n:.0%} win rate) | "
                f"total {sum(r):+.2f}% of price after {self.fee_pct:.2f}% round-trip fees per trade "
                f"| best {max(r):+.2f}%, worst {min(r):+.2f}% (before leverage)")


def backtest(candles: list[Candle], p: Params, fee_pct: float = 0.1) -> BacktestResult:
    """Replay the rules bar by bar over history. A still-open position at the end is ignored."""
    pos: Position | None = None
    trades = []
    for i in range(min_bars(p), len(candles) + 1):
        adv = evaluate(candles[:i], pos, p)
        if adv.action in ("SELL", "COVER") and pos is not None:
            trades.append({"side": pos.side, "entry": pos.entry, "exit": adv.price,
                           "opened_t": pos.opened_t, "closed_t": candles[i - 1].t,
                           "reason": pos.reason, "exit_reason": adv.message, "pnl_pct": adv.pnl_pct})
        pos = adv.position
    return BacktestResult(trades, fee_pct)
