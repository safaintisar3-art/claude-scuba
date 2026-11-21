"""Walk-forward ML test: does any model predict BTC direction out of sample?"""
import os
import json, sys, warnings
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
S = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DAY = 86400


def ema(x, n):
    k = 2 / (n + 1); out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out


def roll(x, n, f):
    out = np.full_like(x, np.nan)
    for i in range(n - 1, len(x)):
        out[i] = f(x[i - n + 1:i + 1])
    return out


def features(gran):
    a = np.array(json.load(open(f"{S}/btc_{gran}.json")), dtype=float)
    t, h, l, c = a[:, 0].astype(int), a[:, 2], a[:, 3], a[:, 4]
    lc = np.log(c)
    tr = np.r_[h[0] - l[0], np.maximum.reduce([h[1:] - l[1:], abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])])]
    atr = np.convolve(tr, np.ones(14) / 14, "full")[:len(tr)]
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    hi48, lo48 = roll(h, 48, np.max), roll(l, 48, np.min)
    cols = []
    for k in (1, 2, 4, 8, 16, 32, 96):
        r = np.full_like(c, np.nan); r[k:] = lc[k:] - lc[:-k]; cols.append(r)
    hour = (t % DAY) / DAY * 2 * np.pi
    cols += [(c - e20) / atr, (c - e50) / atr, (c - e200) / atr, (e20 - e50) / atr,
             atr / c, (c - lo48) / (hi48 - lo48 + 1e-9), np.sin(hour), np.cos(hour),
             roll(np.r_[0, np.diff(lc)], 32, np.std)]
    X = np.column_stack(cols)
    return t, c, X


def run(gran, horizon, train_days, test_days, fees=(0.1, 0.05, 0.0), thrs=(0.5, 0.55, 0.6)):
    t, c, X = features(gran)
    fwd = np.full_like(c, np.nan); fwd[:-horizon] = c[horizon:] / c[:-horizon] - 1
    ok = ~np.isnan(X).any(1)
    y = (fwd > 0).astype(int)
    idx = lambda ts: int(np.searchsorted(t, ts))
    models = {"logistic": lambda: LogisticRegression(C=0.05, max_iter=2000),
              "boosted trees": lambda: HistGradientBoostingClassifier(max_depth=3, max_iter=150,
                                                                      learning_rate=0.05, l2_regularization=1.0)}
    print(f"\n=== {gran//60}-min bars, predict next {horizon} bar(s) ({horizon*gran//60} min), "
          f"train {train_days}d -> test {test_days}d, rolling ===")
    for name, mk in models.items():
        probs = np.full(len(c), np.nan)
        s = t[0] + 3 * DAY; windows = 0
        while s + (train_days + test_days) * DAY <= t[-1]:
            a, b, e = idx(s), idx(s + train_days * DAY), idx(s + (train_days + test_days) * DAY)
            tr = np.arange(a, b - horizon)  # no label overlap into the test window
            tr = tr[ok[tr]]
            te = np.arange(b, min(e, len(c) - horizon)); te = te[ok[te]]
            sc = StandardScaler().fit(X[tr]); m = mk().fit(sc.transform(X[tr]), y[tr])
            probs[te] = m.predict_proba(sc.transform(X[te]))[:, 1]
            windows += 1; s += test_days * DAY
        m = ~np.isnan(probs)
        acc = np.mean((probs[m] > 0.5) == y[m]); base = max(y[m].mean(), 1 - y[m].mean())
        auc = roc_auc_score(y[m], probs[m])
        days = (t[m][-1] - t[m][0]) / DAY
        print(f"{name:14s}: {windows} windows, {days:.0f} unseen days | accuracy {acc:.1%} "
              f"(coin-flip baseline {base:.1%}) | AUC {auc:.3f} (0.500 = no skill)")
        for thr in thrs:
            # non-overlapping trades: decide, hold `horizon` bars, decide again
            rets = []; i = np.argmax(m)
            while i < len(c) - horizon:
                if m[i] and (probs[i] > thr or probs[i] < 1 - thr) and (thr > 0.5 or probs[i] != 0.5):
                    side = 1 if probs[i] > 0.5 else -1
                    rets.append(side * fwd[i] * 100); i += horizon
                else:
                    i += 1
            r = np.array(rets)
            line = " | ".join(f"fee {f:.2f}%: {np.sum(r - f):+8.1f}%" for f in fees)
            print(f"    trade when confidence >{thr:.0%}: {len(r):5d} trades, win {np.mean(r > 0.1):.0%} after fee "
                  f"| total return {line}")


if __name__ == "__main__":
    run(900, 1, 90, 30)
    run(900, 4, 90, 30)
    run(900, 16, 90, 30)
    run(300, 3, 30, 7)
