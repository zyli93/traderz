#!/usr/bin/env python3
"""
Trading Opportunity Screener
Scans for trading setups across multiple strategies using technical indicators.

Usage:
  python screener.py --scan oversold_bounce --universe sp500 --top 10
  python screener.py --scan all --tickers "AAPL,MSFT,NVDA,META" --top 5
  python screener.py --scan relative_strength --universe tech50
"""

import argparse
import json
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD
from ta.volatility import BollingerBands

TECH50 = [
    "AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSLA", "AMD", "CRM", "NFLX",
    "AVGO", "ORCL", "ADBE", "PLTR", "INTC", "QCOM", "MU", "AMAT", "LRCX", "KLAC",
    "MRVL", "PANW", "CRWD", "SNOW", "DDOG", "NET", "ZS", "FTNT", "TEAM", "NOW",
    "SHOP", "SQ", "COIN", "UBER", "LYFT", "ABNB", "DASH", "RBLX", "U", "TTD",
    "PINS", "SNAP", "ROKU", "SE", "MELI", "BIDU", "PDD", "JD", "GRAB", "CPNG",
]

SCAN_MODES = ["oversold_bounce", "breakout", "consolidation", "relative_strength", "gap_up", "all"]


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def get_sp500_tickers() -> list[str]:
    """Scrape S&P 500 tickers from Wikipedia."""
    log("Fetching S&P 500 ticker list from Wikipedia...")
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        df = tables[0]
        tickers = df["Symbol"].tolist()
        # Fix tickers with dots (e.g., BRK.B -> BRK-B for yfinance)
        tickers = [t.replace(".", "-") for t in tickers]
        log(f"Found {len(tickers)} S&P 500 tickers")
        return tickers
    except Exception as e:
        log(f"Error fetching S&P 500 list: {e}")
        return []


def resolve_tickers(args) -> list[str]:
    """Resolve ticker list from arguments."""
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.universe == "sp500":
        return get_sp500_tickers()
    if args.universe == "tech50":
        return list(TECH50)
    log("Error: provide --tickers or --universe")
    sys.exit(1)


def download_data(tickers: list[str], period: str, interval: str) -> dict[str, pd.DataFrame]:
    """Batch download price data for all tickers."""
    log(f"Downloading data for {len(tickers)} tickers (period={period}, interval={interval})...")

    # yf.download returns a DataFrame with MultiIndex columns when multiple tickers
    try:
        raw = yf.download(tickers, period=period, interval=interval, group_by="ticker", threads=True, progress=False)
    except Exception as e:
        log(f"Download error: {e}")
        return {}

    data = {}
    if len(tickers) == 1:
        # Single ticker: columns are just OHLCV
        ticker = tickers[0]
        if not raw.empty and len(raw) > 20:
            data[ticker] = raw.copy()
    else:
        for ticker in tickers:
            try:
                df = raw[ticker].copy()
                df = df.dropna(how="all")
                if len(df) > 20:
                    data[ticker] = df
            except (KeyError, Exception):
                continue

    log(f"Successfully loaded data for {len(data)} / {len(tickers)} tickers")
    return data


def scan_oversold_bounce(data: dict[str, pd.DataFrame], top: int) -> list[dict]:
    """RSI < 35, Stochastic < 20, MACD histogram turning positive."""
    log("Running oversold_bounce scan...")
    results = []
    for ticker, df in data.items():
        try:
            close = df["Close"].squeeze()
            high = df["High"].squeeze()
            low = df["Low"].squeeze()
            if len(close) < 30:
                continue

            rsi = RSIIndicator(close, window=14).rsi()
            stoch = StochasticOscillator(high, low, close, window=14, smooth_window=3)
            stoch_k = stoch.stoch()
            macd_ind = MACD(close)
            macd_hist = macd_ind.macd_diff()

            latest_rsi = rsi.iloc[-1]
            latest_stoch = stoch_k.iloc[-1]
            latest_hist = macd_hist.iloc[-1]
            prev_hist = macd_hist.iloc[-2]

            if pd.isna(latest_rsi) or pd.isna(latest_stoch) or pd.isna(latest_hist):
                continue

            hist_turning_positive = latest_hist > prev_hist and (latest_hist > 0 or prev_hist < 0)

            if latest_rsi < 35 and latest_stoch < 20 and hist_turning_positive:
                results.append({
                    "ticker": ticker,
                    "price": round(float(close.iloc[-1]), 2),
                    "rsi": round(float(latest_rsi), 2),
                    "stochastic_k": round(float(latest_stoch), 2),
                    "macd_histogram": round(float(latest_hist), 4),
                    "macd_hist_prev": round(float(prev_hist), 4),
                    "reason": f"Oversold (RSI={latest_rsi:.1f}, Stoch={latest_stoch:.1f}) with MACD histogram turning positive — mean-reversion candidate",
                })
        except Exception:
            continue

    results.sort(key=lambda x: x["rsi"])
    return results[:top]


def scan_breakout(data: dict[str, pd.DataFrame], top: int) -> list[dict]:
    """Price breaking above 20-day high on above-average volume."""
    log("Running breakout scan...")
    results = []
    for ticker, df in data.items():
        try:
            close = df["Close"].squeeze()
            high = df["High"].squeeze()
            volume = df["Volume"].squeeze()
            if len(close) < 21:
                continue

            high_20 = high.iloc[-21:-1].max()
            avg_vol_20 = volume.iloc[-21:-1].mean()
            latest_close = float(close.iloc[-1])
            latest_vol = float(volume.iloc[-1])

            if pd.isna(high_20) or pd.isna(avg_vol_20) or avg_vol_20 == 0:
                continue

            vol_ratio = latest_vol / avg_vol_20

            if latest_close > float(high_20) and vol_ratio > 1.5:
                pct_above = ((latest_close / float(high_20)) - 1) * 100
                results.append({
                    "ticker": ticker,
                    "price": round(latest_close, 2),
                    "twenty_day_high": round(float(high_20), 2),
                    "pct_above_high": round(pct_above, 2),
                    "volume_ratio": round(vol_ratio, 2),
                    "reason": f"Broke above 20-day high ({float(high_20):.2f}) by {pct_above:.1f}% on {vol_ratio:.1f}x avg volume — momentum breakout",
                })
        except Exception:
            continue

    results.sort(key=lambda x: x["volume_ratio"], reverse=True)
    return results[:top]


def scan_consolidation(data: dict[str, pd.DataFrame], top: int) -> list[dict]:
    """Bollinger Band width in bottom 20% of 50-day range (squeeze)."""
    log("Running consolidation scan...")
    results = []
    for ticker, df in data.items():
        try:
            close = df["Close"].squeeze()
            if len(close) < 50:
                continue

            bb = BollingerBands(close, window=20, window_dev=2)
            bb_high = bb.bollinger_hband()
            bb_low = bb.bollinger_lband()
            bb_mid = bb.bollinger_mavg()

            # Bandwidth = (upper - lower) / middle
            bandwidth = (bb_high - bb_low) / bb_mid
            bandwidth = bandwidth.dropna()

            if len(bandwidth) < 50:
                continue

            recent_bw = bandwidth.iloc[-50:]
            current_bw = float(bandwidth.iloc[-1])
            percentile = (recent_bw < current_bw).sum() / len(recent_bw) * 100

            if percentile <= 20:
                results.append({
                    "ticker": ticker,
                    "price": round(float(close.iloc[-1]), 2),
                    "bb_width": round(current_bw, 4),
                    "bb_width_percentile": round(percentile, 1),
                    "bb_upper": round(float(bb_high.iloc[-1]), 2),
                    "bb_lower": round(float(bb_low.iloc[-1]), 2),
                    "reason": f"Bollinger squeeze — bandwidth at {percentile:.0f}th percentile of 50-day range, big move likely incoming",
                })
        except Exception:
            continue

    results.sort(key=lambda x: x["bb_width_percentile"])
    return results[:top]


def scan_relative_strength(data: dict[str, pd.DataFrame], top: int) -> list[dict]:
    """Stocks outperforming SPY over 5 and 20 days."""
    log("Running relative_strength scan...")

    # Get SPY data
    try:
        spy_raw = yf.download("SPY", period="6mo", interval="1d", progress=False)
        spy_close = spy_raw["Close"].squeeze()
        spy_ret_5 = (float(spy_close.iloc[-1]) / float(spy_close.iloc[-6]) - 1) * 100
        spy_ret_20 = (float(spy_close.iloc[-1]) / float(spy_close.iloc[-21]) - 1) * 100
    except Exception as e:
        log(f"Could not download SPY data: {e}")
        return []

    results = []
    for ticker, df in data.items():
        if ticker == "SPY":
            continue
        try:
            close = df["Close"].squeeze()
            if len(close) < 21:
                continue

            ret_5 = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1) * 100
            ret_20 = (float(close.iloc[-1]) / float(close.iloc[-21]) - 1) * 100

            excess_5 = ret_5 - spy_ret_5
            excess_20 = ret_20 - spy_ret_20

            if excess_5 > 0 and excess_20 > 0:
                combined_excess = excess_5 + excess_20
                results.append({
                    "ticker": ticker,
                    "price": round(float(close.iloc[-1]), 2),
                    "return_5d": round(ret_5, 2),
                    "return_20d": round(ret_20, 2),
                    "spy_return_5d": round(spy_ret_5, 2),
                    "spy_return_20d": round(spy_ret_20, 2),
                    "excess_5d": round(excess_5, 2),
                    "excess_20d": round(excess_20, 2),
                    "reason": f"Outperforming SPY by {excess_5:.1f}% (5d) and {excess_20:.1f}% (20d) — relative strength leader",
                })
        except Exception:
            continue

    results.sort(key=lambda x: x["excess_5d"] + x["excess_20d"], reverse=True)
    return results[:top]


def scan_gap_up(data: dict[str, pd.DataFrame], top: int) -> list[dict]:
    """Stocks that gapped up > 2% from prior close."""
    log("Running gap_up scan...")
    results = []
    for ticker, df in data.items():
        try:
            close = df["Close"].squeeze()
            open_ = df["Open"].squeeze()
            volume = df["Volume"].squeeze()
            if len(close) < 2:
                continue

            prev_close = float(close.iloc[-2])
            today_open = float(open_.iloc[-1])
            current_price = float(close.iloc[-1])

            if prev_close == 0:
                continue

            gap_pct = ((today_open / prev_close) - 1) * 100

            if gap_pct > 2:
                # Check if gap is holding (current price >= open)
                gap_holding = current_price >= today_open
                avg_vol_20 = volume.iloc[-21:-1].mean() if len(volume) > 21 else volume.mean()
                vol_ratio = float(volume.iloc[-1]) / float(avg_vol_20) if float(avg_vol_20) > 0 else 0

                results.append({
                    "ticker": ticker,
                    "price": round(current_price, 2),
                    "prev_close": round(prev_close, 2),
                    "open": round(today_open, 2),
                    "gap_pct": round(gap_pct, 2),
                    "gap_holding": gap_holding,
                    "volume_ratio": round(vol_ratio, 2),
                    "reason": f"Gapped up {gap_pct:.1f}% from ${prev_close:.2f} — {'gap holding' if gap_holding else 'gap fading'}, {vol_ratio:.1f}x avg volume",
                })
        except Exception:
            continue

    results.sort(key=lambda x: x["gap_pct"], reverse=True)
    return results[:top]


def main():
    parser = argparse.ArgumentParser(description="Trading Opportunity Screener")
    parser.add_argument("--scan", required=True, choices=SCAN_MODES, help="Scan mode to run")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated list of tickers")
    parser.add_argument("--universe", type=str, choices=["sp500", "tech50", "custom"], default=None,
                        help="Predefined ticker universe")
    parser.add_argument("--top", type=int, default=10, help="Max results per scan (default 10)")
    parser.add_argument("--period", type=str, default="6mo", help="Data period (default 6mo)")
    parser.add_argument("--interval", type=str, default="1d", help="Data interval (default 1d)")
    args = parser.parse_args()

    if not args.tickers and not args.universe:
        log("Error: provide either --tickers or --universe")
        sys.exit(1)

    tickers = resolve_tickers(args)
    if not tickers:
        log("Error: no tickers resolved")
        sys.exit(1)

    data = download_data(tickers, args.period, args.interval)
    if not data:
        log("Error: no data downloaded")
        sys.exit(1)

    scan_funcs = {
        "oversold_bounce": scan_oversold_bounce,
        "breakout": scan_breakout,
        "consolidation": scan_consolidation,
        "relative_strength": scan_relative_strength,
        "gap_up": scan_gap_up,
    }

    if args.scan == "all":
        scans_to_run = list(scan_funcs.keys())
    else:
        scans_to_run = [args.scan]

    output = {
        "generated_at": datetime.now().isoformat(),
        "scan_modes": scans_to_run,
        "universe_size": len(tickers),
        "data_loaded": len(data),
        "period": args.period,
        "interval": args.interval,
        "results": {},
    }

    for scan_name in scans_to_run:
        func = scan_funcs[scan_name]
        try:
            hits = func(data, args.top)
            output["results"][scan_name] = {
                "count": len(hits),
                "hits": hits,
            }
            log(f"  {scan_name}: {len(hits)} hits")
        except Exception as e:
            log(f"  {scan_name}: error — {e}")
            output["results"][scan_name] = {"count": 0, "hits": [], "error": str(e)}

    json_str = json.dumps(output, indent=2)

    # Save to file
    with open("/tmp/screener_results.json", "w") as f:
        f.write(json_str)
    log(f"Results saved to /tmp/screener_results.json")

    # Print to stdout
    print(json_str)


if __name__ == "__main__":
    main()
