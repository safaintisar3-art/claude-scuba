"""Webhook server that receives TradingView alerts and places orders.

TradingView alert message (JSON):
    {"secret": "...", "symbol": "AAPL", "action": "buy", "qty": 1}

action is one of:
    buy        open / add to a long position
    sell       sell up to `qty` shares of an existing long (never goes short)
    close      sell the whole position in `symbol`
    close_all  flatten every position (e.g. send one near the market close)
"""

import hmac
import logging
import os

from flask import Flask, jsonify, request

from .broker import AlpacaBroker, BrokerError
from .config import Settings, load_settings
from .risk import RiskManager, RiskRejected, TradeLog

log = logging.getLogger("bot")


def create_app(settings: Settings, broker, trade_log: TradeLog) -> Flask:
    app = Flask(__name__)
    risk = RiskManager(settings, broker, trade_log)

    @app.get("/health")
    def health():
        return jsonify(ok=True, live=settings.live_trading, kill_switch=risk.kill_switch_on())

    @app.post("/webhook")
    def webhook():
        data = request.get_json(silent=True, force=True)
        if not isinstance(data, dict):
            return jsonify(error="body must be JSON"), 400
        if not hmac.compare_digest(str(data.get("secret", "")), settings.webhook_secret):
            log.warning("rejected webhook with bad secret from %s", request.remote_addr)
            return jsonify(error="unauthorized"), 401

        action = str(data.get("action", "")).lower()
        symbol = str(data.get("symbol", "")).upper().split(":")[-1]  # "NASDAQ:AAPL" -> "AAPL"

        try:
            if action == "close_all":
                broker.close_all_positions()
                trade_log.record({"action": "close_all"})
                return jsonify(status="closed_all")

            if not symbol:
                return jsonify(error="symbol is required"), 400
            risk.check_symbol(symbol)

            if action == "buy":
                qty = int(data.get("qty", 0))
                risk.check_buy(symbol, qty)
                order = broker.submit_market_order(symbol, qty, "buy")
            elif action in ("sell", "close"):
                risk.check_market_open()
                held = broker.position_qty(symbol)
                if held <= 0:
                    return jsonify(status="ignored", reason=f"no long position in {symbol}")
                if action == "close":
                    order = broker.close_position(symbol)
                    qty = held
                else:
                    qty = min(int(data.get("qty", 0)), int(held))
                    if qty < 1:
                        return jsonify(error="qty must be at least 1"), 400
                    order = broker.submit_market_order(symbol, qty, "sell")
            else:
                return jsonify(error=f"unknown action '{action}'"), 400

        except RiskRejected as e:
            log.info("blocked %s %s: %s", action, symbol, e)
            return jsonify(status="rejected", reason=str(e)), 200
        except (ValueError, TypeError):
            return jsonify(error="qty must be a whole number"), 400
        except BrokerError as e:
            log.error("broker error: %s", e)
            return jsonify(error="broker error", detail=str(e)), 502

        trade_log.record({"action": action, "symbol": symbol, "qty": qty,
                          "order_id": (order or {}).get("id")})
        log.info("%s %s x%s", action, symbol, qty)
        return jsonify(status="submitted", action=action, symbol=symbol, qty=qty)

    return app


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    broker = AlpacaBroker(settings.base_url, settings.alpaca_key, settings.alpaca_secret)
    mode = "LIVE (real money)" if settings.live_trading else "PAPER (simulated)"
    log.info("starting bot in %s mode", mode)
    port = int(os.getenv("PORT", "8000"))
    create_app(settings, broker, TradeLog()).run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
