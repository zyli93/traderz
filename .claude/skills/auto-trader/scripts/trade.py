#!/usr/bin/env python3
"""
trade.py — Execute paper trades and manage portfolio via Alpaca API.

Supports both stocks and crypto. Crypto symbols use slash format (BTC/USD).

Usage:
    # Buy shares
    python trade.py --action buy --ticker AAPL --qty 10 --order-type market

    # Sell shares
    python trade.py --action sell --ticker AAPL --qty 5 --order-type limit --limit-price 185.00

    # Bracket order (buy with stop-loss and take-profit) — stocks only
    python trade.py --action buy --ticker AAPL --qty 10 \
        --order-type bracket --stop-loss 170.00 --take-profit 195.00

    # Buy crypto (fractional supported)
    python trade.py --action buy --ticker BTC/USD --qty 0.01 --order-type market
    python trade.py --action buy --ticker ETH/USD --notional 500 --order-type market
    python trade.py --action buy --ticker SOL/USD --qty 5 --order-type limit --limit-price 140.00

    # Crypto stop-limit order (manual stop-loss)
    python trade.py --action sell --ticker BTC/USD --qty 0.01 \
        --order-type stop-limit --stop-loss 80000 --limit-price 79500

    # View portfolio
    python trade.py --action portfolio

    # View account info
    python trade.py --action account

    # View open orders
    python trade.py --action orders

    # Cancel all open orders
    python trade.py --action cancel-all

    # Close a specific position
    python trade.py --action close --ticker AAPL
    python trade.py --action close --ticker BTCUSD

Environment variables required:
    ALPACA_API_KEY — Paper trading API key
    ALPACA_SECRET_KEY — Paper trading secret key
"""

import argparse
import json
import os
import sys


def load_credentials():
    """Load Alpaca credentials from ~/.config/traderz/credentials.json or env vars.

    Priority: environment variables > config file.
    """
    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")

    if api_key and secret_key:
        return api_key, secret_key

    config_path = os.path.expanduser("~/.config/traderz/credentials.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            creds = json.load(f)
        api_key = creds.get("ALPACA_API_KEY")
        secret_key = creds.get("ALPACA_SECRET_KEY")
        if api_key and secret_key:
            return api_key, secret_key

    return None, None


def get_client():
    """Create and return Alpaca trading client."""
    from alpaca.trading.client import TradingClient

    api_key, secret_key = load_credentials()

    if not api_key or not secret_key:
        print(json.dumps({
            "error": "Missing Alpaca credentials",
            "message": "Set env vars ALPACA_API_KEY/ALPACA_SECRET_KEY, or create "
                       "~/.config/traderz/credentials.json with those keys. "
                       "Get free paper trading keys at https://alpaca.markets"
        }))
        sys.exit(1)

    # paper=True ensures we never hit the live endpoint
    return TradingClient(api_key, secret_key, paper=True)


def get_account(client):
    """Get account information."""
    account = client.get_account()
    return {
        "account_id": str(account.id),
        "status": str(account.status),
        "cash": str(account.cash),
        "buying_power": str(account.buying_power),
        "portfolio_value": str(account.portfolio_value),
        "equity": str(account.equity),
        "long_market_value": str(account.long_market_value),
        "short_market_value": str(account.short_market_value),
        "initial_margin": str(account.initial_margin),
        "maintenance_margin": str(account.maintenance_margin),
        "daytrade_count": str(account.daytrade_count),
        "pattern_day_trader": account.pattern_day_trader,
    }


def get_positions(client):
    """Get all open positions."""
    positions = client.get_all_positions()
    result = []
    for pos in positions:
        result.append({
            "symbol": pos.symbol,
            "qty": str(pos.qty),
            "side": str(pos.side),
            "avg_entry_price": str(pos.avg_entry_price),
            "current_price": str(pos.current_price),
            "market_value": str(pos.market_value),
            "unrealized_pl": str(pos.unrealized_pl),
            "unrealized_plpc": str(pos.unrealized_plpc),
            "change_today": str(pos.change_today),
        })
    return result


def get_orders(client):
    """Get open orders."""
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus

    request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
    orders = client.get_orders(filter=request)
    result = []
    for order in orders:
        result.append({
            "id": str(order.id),
            "symbol": order.symbol,
            "side": str(order.side),
            "type": str(order.type),
            "qty": str(order.qty),
            "filled_qty": str(order.filled_qty),
            "status": str(order.status),
            "limit_price": str(order.limit_price) if order.limit_price else None,
            "stop_price": str(order.stop_price) if order.stop_price else None,
            "created_at": str(order.created_at),
        })
    return result


def is_crypto(ticker):
    """Check if a ticker is a crypto pair (e.g., BTC/USD, ETHUSD)."""
    crypto_bases = [
        "BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "AVAX", "DOT",
        "LTC", "UNI", "SHIB", "PEPE", "AAVE", "BCH", "CRV", "GRT",
        "BAT", "SUSHI", "XTZ", "YFI", "TRUMP", "USDC", "USDT", "USDG", "SKY",
    ]
    normalized = ticker.replace("/", "").upper()
    return any(normalized.startswith(base) and normalized.endswith(("USD", "USDT", "USDC", "BTC"))
               for base in crypto_bases)


def place_order(client, ticker, qty, side, order_type, limit_price=None,
                stop_loss=None, take_profit=None, notional=None):
    """Place a paper trade order. Handles both stocks and crypto."""
    from alpaca.trading.requests import (
        MarketOrderRequest, LimitOrderRequest, StopOrderRequest,
        StopLimitOrderRequest
    )
    from alpaca.trading.enums import OrderSide, TimeInForce

    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
    crypto = is_crypto(ticker)

    # Crypto uses GTC; stocks use DAY
    tif = TimeInForce.GTC if crypto else TimeInForce.DAY

    # Build qty/notional kwargs
    size_kwargs = {}
    if notional:
        size_kwargs["notional"] = notional
    elif qty:
        size_kwargs["qty"] = qty
    else:
        return {"error": "Either qty or notional required"}

    try:
        if order_type == "market":
            request = MarketOrderRequest(
                symbol=ticker,
                side=order_side,
                time_in_force=tif,
                **size_kwargs,
            )
            order = client.submit_order(order_data=request)

        elif order_type == "limit":
            if not limit_price:
                return {"error": "Limit price required for limit orders"}
            request = LimitOrderRequest(
                symbol=ticker,
                side=order_side,
                time_in_force=tif,
                limit_price=limit_price,
                **size_kwargs,
            )
            order = client.submit_order(order_data=request)

        elif order_type == "stop":
            if crypto:
                return {"error": "Crypto does not support plain stop orders. Use stop-limit instead."}
            if not stop_loss:
                return {"error": "Stop price required for stop orders"}
            request = StopOrderRequest(
                symbol=ticker,
                side=order_side,
                time_in_force=tif,
                stop_price=stop_loss,
                **size_kwargs,
            )
            order = client.submit_order(order_data=request)

        elif order_type == "stop-limit":
            if not stop_loss or not limit_price:
                return {"error": "Both stop-loss and limit-price required for stop-limit orders"}
            request = StopLimitOrderRequest(
                symbol=ticker,
                side=order_side,
                time_in_force=tif,
                stop_price=stop_loss,
                limit_price=limit_price,
                **size_kwargs,
            )
            order = client.submit_order(order_data=request)

        elif order_type == "bracket":
            if crypto:
                return {"error": "Crypto does not support bracket orders. Use separate market + stop-limit orders instead."}
            if not stop_loss or not take_profit:
                return {"error": "Both stop-loss and take-profit required for bracket orders"}
            request = MarketOrderRequest(
                symbol=ticker,
                side=order_side,
                time_in_force=tif,
                order_class="bracket",
                take_profit={"limit_price": take_profit},
                stop_loss={"stop_price": stop_loss},
                **size_kwargs,
            )
            order = client.submit_order(order_data=request)

        else:
            return {"error": f"Unknown order type: {order_type}"}

        return {
            "status": "submitted",
            "order_id": str(order.id),
            "symbol": order.symbol,
            "side": str(order.side),
            "type": str(order.type),
            "qty": str(order.qty) if order.qty else None,
            "notional": str(order.notional) if hasattr(order, "notional") and order.notional else None,
            "time_in_force": str(order.time_in_force),
            "asset_class": "crypto" if crypto else "stock",
            "created_at": str(order.created_at),
        }

    except Exception as e:
        return {"error": str(e)}


def close_position(client, ticker):
    """Close a specific position."""
    try:
        client.close_position(ticker)
        return {"status": "closed", "symbol": ticker}
    except Exception as e:
        return {"error": str(e)}


def cancel_all_orders(client):
    """Cancel all open orders."""
    try:
        client.cancel_orders()
        return {"status": "all_orders_cancelled"}
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Alpaca Paper Trading")
    parser.add_argument("--action", required=True,
                        choices=["buy", "sell", "portfolio", "account",
                                 "orders", "close", "cancel-all"],
                        help="Trading action to perform")
    parser.add_argument("--ticker", default=None, help="Stock ticker symbol")
    parser.add_argument("--qty", type=float, default=None, help="Number of shares/coins")
    parser.add_argument("--notional", type=float, default=None,
                        help="Dollar amount to buy (crypto/fractional). Use instead of --qty.")
    parser.add_argument("--order-type", default="market",
                        choices=["market", "limit", "stop", "stop-limit", "bracket"],
                        help="Order type")
    parser.add_argument("--limit-price", type=float, default=None, help="Limit price")
    parser.add_argument("--stop-loss", type=float, default=None, help="Stop loss price")
    parser.add_argument("--take-profit", type=float, default=None, help="Take profit price")
    args = parser.parse_args()

    client = get_client()

    if args.action == "account":
        result = get_account(client)
    elif args.action == "portfolio":
        positions = get_positions(client)
        account = get_account(client)
        result = {
            "account_summary": {
                "portfolio_value": account["portfolio_value"],
                "cash": account["cash"],
                "buying_power": account["buying_power"],
            },
            "positions": positions,
            "position_count": len(positions),
        }
    elif args.action == "orders":
        result = {"open_orders": get_orders(client)}
    elif args.action in ("buy", "sell"):
        if not args.ticker or (not args.qty and not args.notional):
            result = {"error": "Ticker and quantity (or notional) required for buy/sell"}
        else:
            result = place_order(
                client, args.ticker.upper(), args.qty, args.action,
                args.order_type, args.limit_price, args.stop_loss,
                args.take_profit, args.notional
            )
    elif args.action == "close":
        if not args.ticker:
            result = {"error": "Ticker required to close a position"}
        else:
            result = close_position(client, args.ticker.upper())
    elif args.action == "cancel-all":
        result = cancel_all_orders(client)
    else:
        result = {"error": f"Unknown action: {args.action}"}

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
