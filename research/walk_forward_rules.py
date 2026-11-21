"""Walk-forward test of the bot's rules: tune on a past window, test on the next unseen one.
Run from the repo root:  python -m research.walk_forward_rules rules"""
import os
import itertools, json, sys
import numpy as np

S = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DAY = 86400


def load(gran):
    a = np.array(json.load(open(f"{S}/btc_{gran}.json")), dtype=float)
    return {"t": a[:, 0].astype(int), "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4]}


def ema(x, n):
    k = 2 / (n + 1); out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out


_ema_cache = {}


def ema_c(d, n):
    key = (id(d), n)
    if key not in _ema_cache:
        _ema_cache[key] = ema(d["c"], n)
    return _ema_cache[key]


def sim_rules(d, p, start=0, end=None, fee=0.1):
    """Fast replica of bot.btc_strategy.backtest. Trades are counted if entered in [start, end)."""
    fast_n, slow_n, rb, al, sa, rr, short = p
    c, h, l, t = d["c"], d["h"], d["l"], d["t"]
    n = len(c); end = n if end is None else end
    fast, slow = ema_c(d, fast_n), ema_c(d, slow_n)
    tr = np.zeros(n)
    tr[1:] = np.maximum.reduce([h[1:] - l[1:], abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])])
    mb = max(slow_n, rb, al) + 2
    trades = []; pos = None
    for i in range(max(mb - 1, start), n):
        if pos is None and i >= end:
            break
        lo_tr = max(1, i - al + 1)
        a = tr[lo_tr:i + 1].mean()
        up, down = fast[i] > slow[i], fast[i] < slow[i]
        if pos is not None:
            side, entry, stop, tgt, ti = pos
            if side == 1:
                hs, ht, fl = l[i] <= stop, h[i] >= tgt, down
            else:
                hs, ht, fl = h[i] >= stop, l[i] <= tgt, up
            px = stop if hs else tgt if ht else c[i] if fl else None
            if px is not None:
                trades.append((ti, t[i], side, side * (px - entry) / entry * 100 - fee))
                pos = None
            continue
        rhi, rlo = h[i - rb:i].max(), l[i - rb:i].min()
        risk = sa * a
        if up and (c[i] > rhi or (l[i] <= fast[i] < c[i])):
            pos = (1, c[i], c[i] - risk, c[i] + rr * risk, t[i])
        elif down and short and (c[i] < rlo or (h[i] >= fast[i] > c[i])):
            pos = (-1, c[i], c[i] + risk, c[i] - rr * risk, t[i])
    return trades


def stats(rets):
    r = np.array(rets)
    if len(r) == 0:
        return "0 trades"
    return f"{len(r):4d} trades, win {np.mean(r > 0):4.0%}, total {r.sum():+7.2f}%, avg {r.mean():+.3f}%"


def verify():
    from bot.btc_strategy import Candle, Params, backtest
    d = load(300)
    m = 2500
    sub = {k: v[-m:] for k, v in d.items()}
    cs = [Candle(int(sub["t"][i]), sub["o"][i], sub["h"][i], sub["l"][i], sub["c"][i]) for i in range(m)]
    ref = [x["pnl_pct"] - 0.1 for x in backtest(cs, Params(), 0.1).trades]
    _ema_cache.clear()
    fast = [x[3] for x in sim_rules(sub, (20, 50, 24, 14, 1.5, 2.0, True))]
    print("verify: ref", stats(ref), "| fast", stats(fast), "| match", np.allclose(ref, fast))


GRID = list(itertools.product([10, 20], [50, 100], [24, 48], [14], [1.5, 2.5, 4.0], [1.0, 2.0, 3.0], [True, False]))


def walk_forward_rules(gran, train_days, test_days, fee):
    d = load(gran); _ema_cache.clear()
    t = d["t"]; t0 = t[0] + 3 * DAY  # warm-up
    idx = lambda ts: int(np.searchsorted(t, ts))
    out_rets, default_rets, chosen = [], [], []
    s = t0
    while s + (train_days + test_days) * DAY <= t[-1] + DAY:
        tr0, tr1, te1 = idx(s), idx(s + train_days * DAY), idx(s + (train_days + test_days) * DAY)
        best = max(GRID, key=lambda p: sum(x[3] for x in sim_rules(d, p, tr0, tr1, fee)))
        out = [x[3] for x in sim_rules(d, best, tr1, te1, fee)]
        dflt = [x[3] for x in sim_rules(d, (20, 50, 24, 14, 1.5, 2.0, True), tr1, te1, fee)]
        out_rets += out; default_rets += dflt
        chosen.append((best, sum(out)))
        s += test_days * DAY
    return out_rets, default_rets, chosen


if __name__ == "__main__":
    what = sys.argv[1]
    if what == "verify":
        verify()
    elif what == "rules":
        for gran, tr, te in ((300, 30, 7), (900, 90, 30)):
            for fee in (0.1, 0.0):
                o, dft, ch = walk_forward_rules(gran, tr, te, fee)
                print(f"\n{gran//60}-min bars, train {tr}d / test {te}d, fee {fee}%  ({len(ch)} test windows)")
                print("  current default settings :", stats(dft))
                print("  re-tuned each window     :", stats(o))
                print("  windows profitable       :", sum(1 for _, s in ch if s > 0), "/", len(ch))
