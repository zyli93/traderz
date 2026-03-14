#!/usr/bin/env python3
"""
market_intel.py — Gather market intelligence from free sources.

Usage:
    python market_intel.py --mode sectors
    python market_intel.py --mode earnings --tickers "AAPL,MSFT,NVDA,TSLA,META"
    python market_intel.py --mode all --tickers "AAPL,MSFT,NVDA,META,GOOGL,AMZN"

Modes:
    earnings        — Flag tickers reporting earnings within 5 trading days.
    sectors         — Sector ETF performance comparison (1d, 5d, 20d).
    movers          — Biggest percentage movers from a ticker list.
    correlation     — Correlation of each ticker to SPY over 20 days.
    volatility_rank — Rank tickers by ATR as % of price.
    all             — Run all modes.

Outputs JSON to stdout and saves to /tmp/market_intel.json.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSLA"]

SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLP": "Consumer Staples",
    "XLY": "Consumer Discretionary",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communications",
}

OUTPUT_PATH = "/tmp/market_intel.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    """Print progress to stderr."""
    print(f"[market_intel] {msg}", file=sys.stderr)


def safe_round(val, decimals=4):
    """Round a value, returning None if not numeric."""
    try:
        return round(float(val), decimals)
    except (TypeError, ValueError):
        return None


def pct_change_over(series: pd.Series, days: int):
    """Return percentage change over the last N trading days."""
    if series is None or len(series) < days + 1:
        return None
    current = series.iloc[-1]
    prior = series.iloc[-(days + 1)]
    if prior == 0:
        return None
    return (current - prior) / prior * 100


# ---------------------------------------------------------------------------
# Mode: earnings
# ---------------------------------------------------------------------------

def mode_earnings(tickers: list[str]) -> dict:
    """Check upcoming earnings dates for tickers.

    Flags any reporting within the next 5 trading days (~7 calendar days).
    """
    log("Fetching earnings dates...")
    results = []
    today = datetime.now().date()
    horizon = today + timedelta(days=9)  # ~5 trading days ≈ 7-9 calendar days

    for ticker_sym in tickers:
        try:
            tk = yf.Ticker(ticker_sym)
            cal = tk.calendar
            earnings_date = None

            if cal is not None:
                # yfinance returns calendar as a dict or DataFrame depending on version
                if isinstance(cal, pd.DataFrame):
                    if "Earnings Date" in cal.index:
                        raw = cal.loc["Earnings Date"].iloc[0]
                        if hasattr(raw, "date"):
                            earnings_date = raw.date()
                elif isinstance(cal, dict):
                    raw = cal.get("Earnings Date")
                    if raw is not None:
                        if isinstance(raw, list) and len(raw) > 0:
                            raw = raw[0]
                        if hasattr(raw, "date"):
                            earnings_date = raw.date()
                        elif isinstance(raw, str):
                            earnings_date = datetime.strptime(raw, "%Y-%m-%d").date()

            within_window = False
            days_until = None
            if earnings_date is not None:
                days_until = (earnings_date - today).days
                within_window = today <= earnings_date <= horizon

            results.append({
                "ticker": ticker_sym,
                "earnings_date": str(earnings_date) if earnings_date else None,
                "days_until": days_until,
                "within_5_trading_days": within_window,
            })
        except Exception as e:
            log(f"  {ticker_sym}: error fetching earnings — {e}")
            results.append({
                "ticker": ticker_sym,
                "earnings_date": None,
                "days_until": None,
                "within_5_trading_days": False,
                "error": str(e),
            })

    # Sort: soonest earnings first, unknowns last
    results.sort(key=lambda r: (r["days_until"] is None, r["days_until"] or 9999))
    flagged = [r["ticker"] for r in results if r["within_5_trading_days"]]
    if flagged:
        log(f"  WARNING — earnings within 5 trading days: {', '.join(flagged)}")
    else:
        log("  No tickers reporting within 5 trading days.")

    return {"earnings": results}


# ---------------------------------------------------------------------------
# Mode: sectors
# ---------------------------------------------------------------------------

def mode_sectors() -> dict:
    """Compare sector ETF performance over 1d, 5d, 20d."""
    log("Fetching sector ETF data...")
    etf_symbols = list(SECTOR_ETFS.keys())

    try:
        data = yf.download(etf_symbols, period="2mo", interval="1d",
                           group_by="ticker", progress=False)
    except Exception as e:
        log(f"  Error downloading sector data: {e}")
        return {"sectors": {"error": str(e)}}

    rows = []
    for sym in etf_symbols:
        try:
            if len(etf_symbols) == 1:
                close = data["Close"]
            else:
                close = data[sym]["Close"] if sym in data.columns.get_level_values(0) else data[(sym, "Close")]
            close = close.dropna()

            pct_1d = safe_round(pct_change_over(close, 1), 2)
            pct_5d = safe_round(pct_change_over(close, 5), 2)
            pct_20d = safe_round(pct_change_over(close, 20), 2)

            rows.append({
                "ticker": sym,
                "sector": SECTOR_ETFS[sym],
                "pct_1d": pct_1d,
                "pct_5d": pct_5d,
                "pct_20d": pct_20d,
            })
        except Exception as e:
            log(f"  {sym}: error — {e}")
            rows.append({
                "ticker": sym,
                "sector": SECTOR_ETFS[sym],
                "pct_1d": None,
                "pct_5d": None,
                "pct_20d": None,
                "error": str(e),
            })

    # Rank by each timeframe
    for period in ["pct_1d", "pct_5d", "pct_20d"]:
        ranked = sorted(
            [r for r in rows if r[period] is not None],
            key=lambda r: r[period],
            reverse=True,
        )
        for i, r in enumerate(ranked, 1):
            r[f"rank_{period}"] = i

    rows.sort(key=lambda r: (r.get("rank_pct_1d") or 99))

    return {"sectors": rows}


# ---------------------------------------------------------------------------
# Mode: movers
# ---------------------------------------------------------------------------

def mode_movers(tickers: list[str]) -> dict:
    """Find biggest percentage movers (up and down) from a ticker list."""
    log("Fetching mover data...")

    try:
        data = yf.download(tickers, period="5d", interval="1d",
                           group_by="ticker", progress=False)
    except Exception as e:
        log(f"  Error downloading mover data: {e}")
        return {"movers": {"error": str(e)}}

    rows = []
    for sym in tickers:
        try:
            if len(tickers) == 1:
                close = data["Close"]
            else:
                close = data[sym]["Close"] if sym in data.columns.get_level_values(0) else data[(sym, "Close")]
            close = close.dropna()

            if len(close) < 2:
                continue

            pct_1d = safe_round(pct_change_over(close, 1), 2)
            last_price = safe_round(close.iloc[-1], 2)

            rows.append({
                "ticker": sym,
                "last_price": last_price,
                "pct_1d": pct_1d,
            })
        except Exception as e:
            log(f"  {sym}: error — {e}")

    # Sort by absolute move
    rows.sort(key=lambda r: abs(r["pct_1d"] or 0), reverse=True)

    top_gainers = sorted(
        [r for r in rows if (r["pct_1d"] or 0) > 0],
        key=lambda r: r["pct_1d"],
        reverse=True,
    )[:5]
    top_losers = sorted(
        [r for r in rows if (r["pct_1d"] or 0) < 0],
        key=lambda r: r["pct_1d"],
    )[:5]

    return {
        "movers": {
            "all": rows,
            "top_gainers": top_gainers,
            "top_losers": top_losers,
        }
    }


# ---------------------------------------------------------------------------
# Mode: correlation
# ---------------------------------------------------------------------------

def mode_correlation(tickers: list[str]) -> dict:
    """Show correlation of each stock to SPY over the last 20 trading days."""
    log("Computing correlations to SPY...")

    all_syms = list(set(tickers + ["SPY"]))
    try:
        data = yf.download(all_syms, period="2mo", interval="1d",
                           group_by="ticker", progress=False)
    except Exception as e:
        log(f"  Error downloading correlation data: {e}")
        return {"correlation": {"error": str(e)}}

    # Extract close prices into a DataFrame
    closes = pd.DataFrame()
    for sym in all_syms:
        try:
            if len(all_syms) == 1:
                closes[sym] = data["Close"]
            else:
                closes[sym] = data[sym]["Close"] if sym in data.columns.get_level_values(0) else data[(sym, "Close")]
        except Exception:
            log(f"  {sym}: could not extract close prices")

    # Use last 20 trading days
    closes = closes.dropna().tail(20)
    if "SPY" not in closes.columns or len(closes) < 5:
        return {"correlation": {"error": "Insufficient SPY data"}}

    daily_returns = closes.pct_change().dropna()
    spy_returns = daily_returns["SPY"]

    rows = []
    for sym in tickers:
        if sym not in daily_returns.columns:
            continue
        corr = daily_returns[sym].corr(spy_returns)
        rows.append({
            "ticker": sym,
            "correlation_to_spy_20d": safe_round(corr, 3),
        })

    rows.sort(key=lambda r: abs(r["correlation_to_spy_20d"] or 0))

    return {"correlation": rows}


# ---------------------------------------------------------------------------
# Mode: volatility_rank
# ---------------------------------------------------------------------------

def mode_volatility_rank(tickers: list[str]) -> dict:
    """Rank stocks by ATR as a percentage of price (ATR%)."""
    log("Computing volatility ranks (ATR%)...")

    try:
        data = yf.download(tickers, period="2mo", interval="1d",
                           group_by="ticker", progress=False)
    except Exception as e:
        log(f"  Error downloading volatility data: {e}")
        return {"volatility_rank": {"error": str(e)}}

    atr_period = 14
    rows = []

    for sym in tickers:
        try:
            if len(tickers) == 1:
                ohlc = data[["High", "Low", "Close"]].copy()
            else:
                ohlc = data[sym][["High", "Low", "Close"]].copy()

            ohlc = ohlc.dropna()
            if len(ohlc) < atr_period + 1:
                continue

            high = ohlc["High"]
            low = ohlc["Low"]
            close = ohlc["Close"]

            # True Range
            prev_close = close.shift(1)
            tr = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ], axis=1).max(axis=1)

            atr = tr.rolling(window=atr_period).mean().iloc[-1]
            last_price = close.iloc[-1]
            atr_pct = (atr / last_price) * 100 if last_price > 0 else None

            rows.append({
                "ticker": sym,
                "last_price": safe_round(last_price, 2),
                "atr_14": safe_round(atr, 2),
                "atr_pct": safe_round(atr_pct, 2),
            })
        except Exception as e:
            log(f"  {sym}: error — {e}")

    rows.sort(key=lambda r: r["atr_pct"] or 0, reverse=True)

    # Add rank
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    return {"volatility_rank": rows}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Market intelligence scanner."
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["earnings", "sectors", "movers", "correlation",
                 "volatility_rank", "all"],
        help="Intelligence mode to run.",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated ticker list (default: %(default)s).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=OUTPUT_PATH,
        help="Output file path (default: %(default)s).",
    )
    args = parser.parse_args()

    tickers = (
        [t.strip().upper() for t in args.tickers.split(",")]
        if args.tickers
        else DEFAULT_TICKERS
    )

    log(f"Mode: {args.mode} | Tickers: {', '.join(tickers)}")
    log(f"Run time: {datetime.now().isoformat()}")

    results = {
        "generated_at": datetime.now().isoformat(),
        "mode": args.mode,
        "tickers": tickers,
    }

    mode = args.mode

    if mode in ("earnings", "all"):
        results.update(mode_earnings(tickers))

    if mode in ("sectors", "all"):
        results.update(mode_sectors())

    if mode in ("movers", "all"):
        results.update(mode_movers(tickers))

    if mode in ("correlation", "all"):
        results.update(mode_correlation(tickers))

    if mode in ("volatility_rank", "all"):
        results.update(mode_volatility_rank(tickers))

    # Write to file
    try:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2, default=str)
        log(f"Results saved to {args.output}")
    except Exception as e:
        log(f"Error saving results: {e}")

    # Also print to stdout
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
