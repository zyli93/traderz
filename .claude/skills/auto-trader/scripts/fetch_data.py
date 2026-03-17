#!/usr/bin/env python3
"""
fetch_data.py — Fetch stock data and compute technical indicators.

Usage:
    python fetch_data.py --ticker AAPL --period 6mo --interval 1d
    python fetch_data.py --ticker AAPL,TSLA,GOOGL --period 3mo --interval 1d
    python fetch_data.py --ticker SPY --period 1y --interval 1d --output /tmp/analysis_SPY.json

Outputs a JSON file with price data, technical indicators, and fundamentals.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
import ta


def compute_indicators(df: pd.DataFrame) -> dict:
    """Compute technical indicators on OHLCV DataFrame."""
    indicators = {}

    # --- Trend Indicators ---
    # Simple Moving Averages
    for window in [20, 50, 200]:
        col = f"SMA_{window}"
        df[col] = ta.trend.sma_indicator(df["Close"], window=window)
        val = df[col].iloc[-1]
        indicators[col] = round(val, 2) if pd.notna(val) else None

    # Exponential Moving Averages
    for window in [12, 26]:
        col = f"EMA_{window}"
        df[col] = ta.trend.ema_indicator(df["Close"], window=window)
        val = df[col].iloc[-1]
        indicators[col] = round(val, 2) if pd.notna(val) else None

    # MACD
    macd = ta.trend.MACD(df["Close"])
    df["MACD"] = macd.macd()
    df["MACD_signal"] = macd.macd_signal()
    df["MACD_hist"] = macd.macd_diff()
    indicators["MACD"] = round(df["MACD"].iloc[-1], 4) if pd.notna(df["MACD"].iloc[-1]) else None
    indicators["MACD_signal"] = round(df["MACD_signal"].iloc[-1], 4) if pd.notna(df["MACD_signal"].iloc[-1]) else None
    indicators["MACD_histogram"] = round(df["MACD_hist"].iloc[-1], 4) if pd.notna(df["MACD_hist"].iloc[-1]) else None

    # ADX
    adx = ta.trend.ADXIndicator(df["High"], df["Low"], df["Close"])
    df["ADX"] = adx.adx()
    indicators["ADX"] = round(df["ADX"].iloc[-1], 2) if pd.notna(df["ADX"].iloc[-1]) else None

    # --- Momentum Indicators ---
    # RSI
    df["RSI"] = ta.momentum.rsi(df["Close"], window=14)
    indicators["RSI_14"] = round(df["RSI"].iloc[-1], 2) if pd.notna(df["RSI"].iloc[-1]) else None

    # Stochastic
    stoch = ta.momentum.StochasticOscillator(df["High"], df["Low"], df["Close"])
    df["Stoch_K"] = stoch.stoch()
    df["Stoch_D"] = stoch.stoch_signal()
    indicators["Stochastic_K"] = round(df["Stoch_K"].iloc[-1], 2) if pd.notna(df["Stoch_K"].iloc[-1]) else None
    indicators["Stochastic_D"] = round(df["Stoch_D"].iloc[-1], 2) if pd.notna(df["Stoch_D"].iloc[-1]) else None

    # --- Volatility Indicators ---
    # Bollinger Bands
    bb = ta.volatility.BollingerBands(df["Close"])
    df["BB_upper"] = bb.bollinger_hband()
    df["BB_middle"] = bb.bollinger_mavg()
    df["BB_lower"] = bb.bollinger_lband()
    indicators["Bollinger_upper"] = round(df["BB_upper"].iloc[-1], 2) if pd.notna(df["BB_upper"].iloc[-1]) else None
    indicators["Bollinger_middle"] = round(df["BB_middle"].iloc[-1], 2) if pd.notna(df["BB_middle"].iloc[-1]) else None
    indicators["Bollinger_lower"] = round(df["BB_lower"].iloc[-1], 2) if pd.notna(df["BB_lower"].iloc[-1]) else None

    # ATR
    df["ATR"] = ta.volatility.average_true_range(df["High"], df["Low"], df["Close"])
    indicators["ATR_14"] = round(df["ATR"].iloc[-1], 2) if pd.notna(df["ATR"].iloc[-1]) else None

    # --- Volume Indicators ---
    df["OBV"] = ta.volume.on_balance_volume(df["Close"], df["Volume"])
    indicators["OBV"] = int(df["OBV"].iloc[-1]) if pd.notna(df["OBV"].iloc[-1]) else None

    # Volume SMA
    df["Vol_SMA_20"] = df["Volume"].rolling(window=20).mean()
    vol_ratio = df["Volume"].iloc[-1] / df["Vol_SMA_20"].iloc[-1] if pd.notna(df["Vol_SMA_20"].iloc[-1]) and df["Vol_SMA_20"].iloc[-1] > 0 else None
    indicators["volume_vs_avg"] = round(vol_ratio, 2) if vol_ratio else None

    return indicators


def find_support_resistance(df: pd.DataFrame, window: int = 20) -> dict:
    """Find approximate support and resistance levels using rolling min/max."""
    recent = df.tail(window)
    levels = {
        "recent_high": round(recent["High"].max(), 2),
        "recent_low": round(recent["Low"].min(), 2),
        "52w_high": round(df.tail(252)["High"].max(), 2) if len(df) >= 252 else round(df["High"].max(), 2),
        "52w_low": round(df.tail(252)["Low"].min(), 2) if len(df) >= 252 else round(df["Low"].min(), 2),
    }
    return levels


def get_fundamentals(ticker_obj) -> dict:
    """Extract key fundamental data from yfinance Ticker object."""
    info = ticker_obj.info
    fundamentals = {}
    fields = [
        "shortName", "sector", "industry", "marketCap", "trailingPE",
        "forwardPE", "dividendYield", "beta", "fiftyTwoWeekHigh",
        "fiftyTwoWeekLow", "averageVolume", "earningsDate",
        "recommendationKey", "targetMeanPrice", "currentPrice"
    ]
    for field in fields:
        val = info.get(field)
        if isinstance(val, (int, float)) and pd.notna(val):
            fundamentals[field] = val
        elif isinstance(val, str):
            fundamentals[field] = val
        elif isinstance(val, list):
            fundamentals[field] = [str(v) for v in val]
    return fundamentals


def get_analyst_and_news(ticker_obj) -> dict:
    """Extract analyst ratings, price targets, and recent news."""
    result = {}

    # Price targets
    try:
        apt = ticker_obj.analyst_price_targets
        if apt is not None and isinstance(apt, dict):
            result["price_targets"] = {
                "current": apt.get("current"),
                "mean": apt.get("mean"),
                "high": apt.get("high"),
                "low": apt.get("low"),
                "number_of_analysts": apt.get("numberOfAnalysts"),
            }
    except Exception:
        pass

    # Recommendations summary
    try:
        rs = ticker_obj.recommendations_summary
        if rs is not None and isinstance(rs, pd.DataFrame) and not rs.empty:
            latest = rs.iloc[0].to_dict()
            result["recommendations_summary"] = {
                "strongBuy": int(latest.get("strongBuy", 0)),
                "buy": int(latest.get("buy", 0)),
                "hold": int(latest.get("hold", 0)),
                "sell": int(latest.get("sell", 0)),
                "strongSell": int(latest.get("strongSell", 0)),
            }
    except Exception:
        pass

    # Recent rating changes (last 5)
    try:
        recs = ticker_obj.recommendations
        if recs is not None and isinstance(recs, pd.DataFrame) and not recs.empty:
            changes = []
            for _, row in recs.tail(5).iterrows():
                changes.append({
                    "firm": row.get("Firm", ""),
                    "grade": row.get("To Grade", ""),
                    "from_grade": row.get("From Grade", ""),
                    "action": row.get("Action", ""),
                })
            changes.reverse()
            result["recent_changes"] = changes
    except Exception:
        pass

    # Recent news (last 10 headlines)
    try:
        news = ticker_obj.news or []
        headlines = []
        for item in news[:10]:
            headlines.append({
                "title": item.get("title", ""),
                "publisher": item.get("publisher"),
            })
        result["recent_headlines"] = headlines
    except Exception:
        pass

    return result


def analyze_ticker(symbol: str, period: str, interval: str) -> dict:
    """Full analysis pipeline for a single ticker."""
    print(f"Fetching data for {symbol}...", file=sys.stderr)
    ticker = yf.Ticker(symbol)

    # Download OHLCV
    df = ticker.history(period=period, interval=interval)
    if df.empty:
        return {"error": f"No data returned for {symbol}. Check ticker symbol."}

    # Clean up index
    df.index = df.index.tz_localize(None) if df.index.tz else df.index

    # Current price info
    latest = df.iloc[-1]
    prev_close = df.iloc[-2]["Close"] if len(df) > 1 else latest["Close"]
    price_change = latest["Close"] - prev_close
    price_change_pct = (price_change / prev_close) * 100

    # Compute indicators
    indicators = compute_indicators(df)

    # Support/resistance
    levels = find_support_resistance(df)

    # Fundamentals
    fundamentals = get_fundamentals(ticker)

    # Analyst & news
    analyst_and_news = get_analyst_and_news(ticker)

    # Recent price action (last 10 days for context)
    recent_prices = []
    for idx, row in df.tail(10).iterrows():
        recent_prices.append({
            "date": idx.strftime("%Y-%m-%d"),
            "open": round(row["Open"], 2),
            "high": round(row["High"], 2),
            "low": round(row["Low"], 2),
            "close": round(row["Close"], 2),
            "volume": int(row["Volume"]),
        })

    # Signal summary (simple rule-based pre-screening)
    signals = []
    if indicators.get("RSI_14"):
        if indicators["RSI_14"] > 70:
            signals.append("RSI overbought (>70)")
        elif indicators["RSI_14"] < 30:
            signals.append("RSI oversold (<30)")

    if indicators.get("MACD") is not None and indicators.get("MACD_signal") is not None:
        if indicators["MACD"] > indicators["MACD_signal"]:
            signals.append("MACD bullish crossover")
        else:
            signals.append("MACD bearish crossover")

    if indicators.get("SMA_50") and indicators.get("SMA_200"):
        if indicators["SMA_50"] > indicators["SMA_200"]:
            signals.append("Golden cross (SMA50 > SMA200)")
        else:
            signals.append("Death cross (SMA50 < SMA200)")

    current_price = round(latest["Close"], 2)
    if indicators.get("BB_lower") and current_price < indicators["BB_lower"]:
        signals.append("Price below lower Bollinger Band")
    elif indicators.get("BB_upper") and current_price > indicators["BB_upper"]:
        signals.append("Price above upper Bollinger Band")

    # Analyst target upside signal
    mean_target = (analyst_and_news.get("price_targets") or {}).get("mean")
    if mean_target and current_price > 0:
        upside = (mean_target - current_price) / current_price * 100
        if upside > 20:
            signals.append(f"Analyst mean target implies {upside:.0f}% upside")

    result = {
        "ticker": symbol,
        "analysis_time": datetime.now().isoformat(),
        "current_price": current_price,
        "price_change": round(price_change, 2),
        "price_change_pct": round(price_change_pct, 2),
        "volume": int(latest["Volume"]),
        "indicators": indicators,
        "support_resistance": levels,
        "fundamentals": fundamentals,
        "analyst_and_news": analyst_and_news,
        "recent_prices": recent_prices,
        "signal_summary": signals,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Fetch stock data and compute indicators")
    parser.add_argument("--ticker", required=True, help="Ticker symbol(s), comma-separated")
    parser.add_argument("--period", default="6mo", help="Data period (1mo, 3mo, 6mo, 1y, 2y)")
    parser.add_argument("--interval", default="1d", help="Data interval (1m, 5m, 1h, 1d, 1wk)")
    parser.add_argument("--output", default=None, help="Output JSON path (default: /tmp/analysis_TICKER.json)")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.ticker.split(",")]
    results = {}

    for symbol in tickers:
        # Convert crypto Alpaca format (BTC/USD) to yfinance format (BTC-USD)
        yf_symbol = symbol.replace("/", "-")
        results[symbol] = analyze_ticker(yf_symbol, args.period, args.interval)
        # Preserve the original symbol key
        if yf_symbol != symbol:
            results[symbol]["ticker"] = symbol

    # Determine output path
    if args.output:
        output_path = args.output
    elif len(tickers) == 1:
        output_path = f"/tmp/analysis_{tickers[0]}.json"
    else:
        output_path = "/tmp/analysis_multi.json"

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"Analysis saved to {output_path}", file=sys.stderr)

    # Also print to stdout for direct reading
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
