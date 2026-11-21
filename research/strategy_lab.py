"""Strategy lab: search many strategy families on many timeframes, honestly.

Protocol
  1. The last HOLDOUT_DAYS of data are locked away. Nothing in the search sees them.
  2. On the rest ("development" data) every family is walk-forward tested: pick the best
     settings on a trailing training window, trade the next unseen window with them, roll on.
  3. The family/timeframe with the best unseen-data Sharpe ratio on development data is chosen.
  4. Only then is that one choice run on the locked holdout, once.

Positions are decided at a bar's close and earn the NEXT bar's return (no peeking).
Fees are charged per side on every position change (a long->short flip pays twice).

Run from the repo root:  python -m research.strategy_lab
"""
import itertools
import json
import os
import sys

import numpy as np

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DAY = 86400
HOLDOUT_DAYS = 90
FEE_PER_SIDE = 0.0005  # 0.05% per side = 0.1% round trip

# timeframe: (bar seconds, train days, test days)
TIMEFRAMES = {"15m": (900, 120, 30), "1h": (3600, 365, 90), "6h": (21600, 365, 90), "1d": (86400, 3 * 365, 182)}


def day(ts):
    return str(np.datetime64(int(ts), 's'))[:10]


def load(gran):
    a = np.array(json.load(open(f"{DATA}/btc_{gran}.json")), dtype=float)
    return {"t": a[:, 0].astype(int), "h": a[:, 2], "l": a[:, 3], "c": a[:, 4]}


def ema(x, n):
    k = 2 / (n + 1); out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out


def rolling_max(x, n):
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full_like(x, np.nan); out[n - 1:] = sliding_window_view(x, n).max(1); return out


def rolling_min(x, n):
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full_like(x, np.nan); out[n - 1:] = sliding_window_view(x, n).min(1); return out


def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = np.clip(d, 0, None); dn = np.clip(-d, 0, None)
    k = 1 / n; au = np.zeros_like(c); ad = np.zeros_like(c)
    for i in range(1, len(c)):
        au[i] = au[i - 1] * (1 - k) + up[i] * k; ad[i] = ad[i - 1] * (1 - k) + dn[i] * k
    return 100 - 100 / (1 + au / np.maximum(ad, 1e-12))


class Cache(dict):
    def get_or(self, key, fn):
        if key not in self:
            self[key] = fn()
        return self[key]


# ---------- strategy families: each returns a position array in {-1, 0, 1} ----------

def trend_ema(d, C, n, short):
    e = C.get_or(("ema", n), lambda: ema(d["c"], n))
    return np.where(d["c"] > e, 1, -1 if short else 0)


def ema_cross(d, C, f, s, short):
    if f >= s:
        return None
    ef = C.get_or(("ema", f), lambda: ema(d["c"], f)); es = C.get_or(("ema", s), lambda: ema(d["c"], s))
    return np.where(ef > es, 1, -1 if short else 0)


def momentum(d, C, n, short):
    c = d["c"]; r = np.zeros_like(c); r[n:] = c[n:] / c[:-n] - 1
    return np.where(r > 0, 1, -1 if short else 0)


def donchian(d, C, n_in, n_out, short):
    if n_out >= n_in:
        return None
    c = d["c"]
    hi = C.get_or(("hi", n_in), lambda: np.r_[np.nan, rolling_max(d["h"], n_in)[:-1]])
    lo = C.get_or(("lo", n_in), lambda: np.r_[np.nan, rolling_min(d["l"], n_in)[:-1]])
    xhi = C.get_or(("hi", n_out), lambda: np.r_[np.nan, rolling_max(d["h"], n_out)[:-1]])
    xlo = C.get_or(("lo", n_out), lambda: np.r_[np.nan, rolling_min(d["l"], n_out)[:-1]])
    p = np.zeros(len(c)); s = 0
    for i in range(len(c)):
        if s == 1 and c[i] < xlo[i]: s = 0
        elif s == -1 and c[i] > xhi[i]: s = 0
        if s <= 0 and c[i] > hi[i]: s = 1
        elif s >= 0 and short and c[i] < lo[i]: s = -1
        p[i] = s
    return p


def rsi_revert(d, C, n, band, short):
    r = C.get_or(("rsi", n), lambda: rsi(d["c"], n))
    p = np.zeros(len(r)); s = 0
    for i in range(len(r)):
        if s == 1 and r[i] >= 50: s = 0
        elif s == -1 and r[i] <= 50: s = 0
        if s == 0 and r[i] < band: s = 1
        elif s == 0 and short and r[i] > 100 - band: s = -1
        p[i] = s
    return p


def trend_volfilter(d, C, n, vol_n, short):
    """EMA trend, but stand aside when recent volatility is above its 1-year-ish median."""
    base = trend_ema(d, C, n, short)
    lr = np.diff(np.log(d["c"]), prepend=np.log(d["c"][0]))
    v = C.get_or(("vol", vol_n), lambda: np.array([lr[max(0, i - vol_n + 1):i + 1].std() for i in range(len(lr))]))
    med = C.get_or(("volmed", vol_n), lambda: np.array([np.median(v[max(0, i - 8 * vol_n):i + 1]) for i in range(len(v))]))
    return np.where(v <= med, base, 0)


FAMILIES = {
    "trend (price vs EMA)": (trend_ema, {"n": [10, 20, 50, 100, 200], "short": [False, True]}),
    "EMA crossover": (ema_cross, {"f": [5, 10, 20, 50], "s": [20, 50, 100, 200], "short": [False, True]}),
    "momentum": (momentum, {"n": [5, 10, 20, 50, 100], "short": [False, True]}),
    "breakout (Donchian)": (donchian, {"n_in": [20, 55, 100], "n_out": [10, 20, 50], "short": [False, True]}),
    "mean reversion (RSI)": (rsi_revert, {"n": [2, 7, 14], "band": [10, 20, 30], "short": [False, True]}),
    "trend + calm-market filter": (trend_volfilter, {"n": [20, 50, 100], "vol_n": [20, 50], "short": [False, True]}),
}


def grid(spec):
    keys = list(spec)
    return [dict(zip(keys, vals)) for vals in itertools.product(*spec.values())]


def bar_returns(pos, c, fee=FEE_PER_SIDE):
    """Strategy return of each bar i (position held from close i-1 to close i), net of fees."""
    r = np.zeros(len(c)); r[1:] = c[1:] / c[:-1] - 1
    held = np.r_[0, pos[:-1]]
    turns = np.abs(np.diff(np.r_[0, pos]))  # change at close i, paid at i
    return held * r - turns * fee


def sharpe(r, bars_per_year):
    return 0.0 if r.std() == 0 else r.mean() / r.std() * np.sqrt(bars_per_year)


def summarize(r, bars_per_year, pos=None):
    eq = np.cumprod(1 + r); dd = (eq / np.maximum.accumulate(eq) - 1).min()
    years = len(r) / bars_per_year
    out = {"return": eq[-1] - 1, "per_year": eq[-1] ** (1 / years) - 1 if years > 0 else 0,
           "sharpe": sharpe(r, bars_per_year), "max_drawdown": dd}
    if pos is not None:
        out["trades"] = int((np.abs(np.diff(pos)) > 0).sum())
    return out


def walk_forward(d, family, tf, start_t, end_t, C):
    """Out-of-sample bar returns between start_t and end_t, with settings re-picked on each
    trailing training window. Returns (returns, positions, chosen settings per window)."""
    fn, spec = FAMILIES[family]
    gran, train_days, test_days = TIMEFRAMES[tf]
    bpy = 365 * DAY / gran
    t = d["t"]; idx = lambda ts: int(np.searchsorted(t, ts))
    params = [p for p in grid(spec)]
    positions = {}
    for p in params:
        pos = fn(d, C, **p)
        if pos is not None:
            positions[tuple(p.items())] = pos
    rets = {k: bar_returns(v, d["c"]) for k, v in positions.items()}
    out_r, out_p, chosen = [], [], []
    s = start_t
    while s < end_t:
        a, b = idx(s - train_days * DAY), idx(s)
        e = idx(min(s + test_days * DAY, end_t))
        if b - a < 50 or e <= b:
            s += test_days * DAY; continue
        best = max(rets, key=lambda k: sharpe(rets[k][a:b], bpy))
        out_r.append(rets[best][b:e]); out_p.append(positions[best][b:e]); chosen.append(dict(best))
        s += test_days * DAY
    if not out_r:
        return np.array([]), np.array([]), []
    return np.concatenate(out_r), np.concatenate(out_p), chosen


def fmt(s):
    return (f"return {s['return']:+8.1%}  per-year {s['per_year']:+7.1%}  Sharpe {s['sharpe']:+5.2f}  "
            f"max drawdown {s['max_drawdown']:6.1%}" + (f"  trades {s['trades']:5d}" if "trades" in s else ""))


def main():
    end_all = min(load(g)["t"][-1] for g, _, _ in TIMEFRAMES.values())
    holdout_start = end_all - HOLDOUT_DAYS * DAY
    results = []
    print(f"Holdout (locked) starts {day(holdout_start)}; development data is everything before.\n")
    for tf, (gran, train_days, test_days) in TIMEFRAMES.items():
        d = load(gran); C = Cache(); bpy = 365 * DAY / gran
        dev_start = d["t"][0] + train_days * DAY
        m = (d["t"] >= dev_start) & (d["t"] < holdout_start)
        bh = summarize(np.r_[0, d["c"][1:] / d["c"][:-1] - 1][m], bpy)
        print(f"== {tf} bars | development {day(dev_start)} -> {day(holdout_start)} "
              f"(train {train_days}d, test {test_days}d)")
        print(f"   {'buy and hold':28s} {fmt(bh)}")
        for fam in FAMILIES:
            r, p, ch = walk_forward(d, fam, tf, dev_start, holdout_start, C)
            if len(r) == 0:
                continue
            s = summarize(r, bpy, p)
            results.append((s["sharpe"], tf, fam, s))
            print(f"   {fam:28s} {fmt(s)}")
        print()
        sys.stdout.flush()

    results.sort(reverse=True)
    print("Top 5 on development (unseen walk-forward windows only):")
    for sh, tf, fam, s in results[:5]:
        print(f"   {tf:4s} {fam:28s} {fmt(s)}")
    json.dump([(tf, fam) for _, tf, fam, _ in results], open(f"{DATA}/ranking.json", "w"))


def holdout(tf, fam):
    gran, train_days, test_days = TIMEFRAMES[tf]
    d = load(gran); C = Cache(); bpy = 365 * DAY / gran
    end_all = min(load(g)["t"][-1] for g, _, _ in TIMEFRAMES.values())
    hs = end_all - HOLDOUT_DAYS * DAY
    r, p, ch = walk_forward(d, fam, tf, hs, end_all + 1, C)
    m = d["t"] >= hs
    bh = summarize(np.r_[0, d["c"][1:] / d["c"][:-1] - 1][m], bpy)
    print(f"HOLDOUT {day(hs)} -> {day(end_all)}  ({tf}, {fam})")
    print(f"   settings picked from training data: {ch}")
    print(f"   {'strategy':14s} {fmt(summarize(r, bpy, p))}")
    print(f"   {'buy and hold':14s} {fmt(bh)}")
    for f in (0.0, 0.001):
        print(f"   fee {f*2:.2%} round trip: return {np.prod(1 + bar_returns(p, d['c'][m], f)) - 1:+.1%}")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "holdout":
        holdout(sys.argv[2], sys.argv[3])
    else:
        main()
