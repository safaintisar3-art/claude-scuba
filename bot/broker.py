"""Thin client for the Alpaca trading API (paper trading by default)."""

import requests


class BrokerError(Exception):
    pass


class AlpacaBroker:
    def __init__(self, base_url: str, key: str, secret: str, timeout: float = 10.0):
        if not key or not secret:
            raise BrokerError("ALPACA_API_KEY and ALPACA_API_SECRET must be set.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
        })

    def _request(self, method: str, path: str, **kwargs):
        resp = self.session.request(method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs)
        if resp.status_code == 404 and method == "GET":
            return None
        if not resp.ok:
            raise BrokerError(f"{method} {path} failed ({resp.status_code}): {resp.text}")
        return resp.json() if resp.content else None

    def account(self) -> dict:
        return self._request("GET", "/v2/account")

    def is_market_open(self) -> bool:
        return bool(self._request("GET", "/v2/clock")["is_open"])

    def position_qty(self, symbol: str) -> float:
        """Signed quantity held (negative = short). 0 if no position."""
        pos = self._request("GET", f"/v2/positions/{symbol}")
        return float(pos["qty"]) if pos else 0.0

    def latest_price(self, symbol: str) -> float:
        """Last trade price, from Alpaca's market data API."""
        resp = self.session.get(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest",
            timeout=self.timeout,
        )
        if not resp.ok:
            raise BrokerError(f"price lookup for {symbol} failed ({resp.status_code}): {resp.text}")
        return float(resp.json()["trade"]["p"])

    def submit_market_order(self, symbol: str, qty: int, side: str) -> dict:
        return self._request("POST", "/v2/orders", json={
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "market",
            "time_in_force": "day",
        })

    def close_position(self, symbol: str):
        return self._request("DELETE", f"/v2/positions/{symbol}")

    def close_all_positions(self):
        return self._request("DELETE", "/v2/positions", params={"cancel_orders": "true"})
