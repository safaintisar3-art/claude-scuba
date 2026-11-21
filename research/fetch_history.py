"""Download BTC-USD history from Coinbase into research/data/ (free, no key).
15-min bars for 1 year and 5-min bars for 90 days. Takes about 2 minutes."""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests  # noqa: E402
from bot.btc_signals import fetch_candles  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class Polite:
    def get(self, *a, **k):
        time.sleep(0.2)  # stay under Coinbase's public rate limit
        return requests.get(*a, **k)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for gran, n in ((900, 35040), (300, 25920)):
        cs = fetch_candles("BTC-USD", gran, n, session=Polite())
        json.dump([[c.t, c.open, c.high, c.low, c.close] for c in cs], open(f"{OUT}/btc_{gran}.json", "w"))
        print(f"{gran // 60}-min: {len(cs)} bars")
