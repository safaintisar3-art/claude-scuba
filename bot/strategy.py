"""Trading signal: fast/slow EMA crossover (same idea as strategies/ema_cross.pine).

This is a simple example strategy, not a recommendation. Swap in your own logic
by changing `signal()`; it only needs to return "buy", "sell" or None.
"""


def ema(values: list[float], length: int) -> list[float]:
    """Exponential moving average, same formula as TradingView's ta.ema."""
    if not values:
        return []
    k = 2 / (length + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def signal(closes: list[float], fast_len: int, slow_len: int) -> str | None:
    """'buy' when the fast EMA crosses above the slow one on the latest bar,
    'sell' when it crosses below, otherwise None."""
    if len(closes) < slow_len + 2:
        return None  # not enough history yet
    fast = ema(closes, fast_len)
    slow = ema(closes, slow_len)
    if fast[-2] <= slow[-2] and fast[-1] > slow[-1]:
        return "buy"
    if fast[-2] >= slow[-2] and fast[-1] < slow[-1]:
        return "sell"
    return None
