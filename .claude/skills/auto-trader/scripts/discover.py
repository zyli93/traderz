#!/usr/bin/env python3
"""
discover.py — Discover trending stocks beyond fixed watchlists.

Finds trading opportunities using multiple discovery modes: gainers, trending
stocks, new highs, momentum leaders, and volume surges.

Usage:
    python discover.py --mode gainers --top 15
    python discover.py --mode trending_up --universe broad --top 20
    python discover.py --mode all --universe all --top 10
    python discover.py --mode momentum_leaders --tickers "AAPL,MSFT,NVDA" --top 5
"""

import argparse
import json
import sys
import re
from datetime import datetime

import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Broad universe: ~200 interesting mid/small-cap stocks NOT in S&P 500
# Spanning tech, biotech, fintech, EVs, AI, cybersecurity, cloud, consumer,
# crypto-adjacent, space, and more.
# ---------------------------------------------------------------------------
BROAD_UNIVERSE = [
    # AI / ML / Data
    "AI", "BBAI", "SOUN", "ASAN", "PATH", "BRZE", "MNDY", "FRSH",
    "CFLT", "MDB", "GTLB", "ESTC", "DOCN", "S", "PCOR",
    # Storage / Hardware / Misc tech
    "SNDK", "DAWN", "IONQ", "RGTI", "QUBT", "OKLO", "SMR", "NNE", "LEU",
    # Fintech
    "AFRM", "UPST", "BILL", "SOFI", "HOOD", "NU", "STNE", "XP",
    "DLO", "PAYO", "FOUR", "RELY", "HCP", "VTEX",
    # Cloud / SaaS
    "TWLO", "OKTA", "DDOG", "ZI", "GLOB", "WIX", "FVRR",
    "BOX", "DOCU", "FSLY", "NET", "AKAM", "FFIV",
    # Cybersecurity
    "RBRK", "ZS", "CYBR", "TENB", "VRNS", "RPD", "QLYS",
    "FTNT", "CHKP", "PANW", "CRWD",
    # Tech-adjacent consumer / platforms
    "ETSY", "DUOL", "RDDT", "HIMS",
    # Gaming tech
    "RBLX", "U",
    # EV tech / batteries
    "RIVN", "LCID", "QS", "ENVX",
    # Semis / Hardware
    "SMCI", "ARM", "CRDO", "VRT", "ANET", "PSTG", "NTAP",
    "AMBA", "CRNC", "CDNS", "SNPS", "ANSS", "KEYS", "TER",
    "ENTG", "ONTO", "ACLS", "WOLF", "SLAB", "SITM", "FORM",
    "CRUS", "SWKS", "MCHP", "NXPI", "MPWR", "RMBS", "ALGM",
    "DIOD", "INDI", "LSCC", "MTSI", "PI", "SMTC", "ACMR",
    "UCTT", "ICHR",
    # Biotech / Health
    "AEHR", "NNOX", "LUNG", "NUVB", "RXRX", "DNA", "TWST",
    "PACB", "BFLY", "TALK", "GDRX", "OSCR", "ACCD", "DOCS",
    "TDOC", "AMWL",
    # Space / Defense
    "RKLB", "JOBY", "ASTS", "SPCE", "LUNR", "RDW",
    # Crypto-adjacent
    "MSTR", "COIN", "MARA", "RIOT", "CLSK", "HUT", "BITF",
    # App / Marketplace / Social
    "APP", "TOST", "COUR", "UDMY", "SKIL", "GDS", "KC",
    # Misc growth / special situations
    "IOT", "CLOV", "OPEN", "VNET", "APLT", "GENI", "STEM",
    "DNMR", "OUST", "LAZR", "INVZ", "LIDR",
    # Additional interesting mid-caps
    "TMDX", "NARI", "ISRG", "TXG", "LEGN", "BMRN", "MRNA",
    "ARCT", "KRYS", "IONS", "REGN", "BGNE", "ZLAB",
    "PCVX", "VKTX", "PLRX", "GPCR", "DAWN",
    # Robotics / med-tech
    "IRTC", "NVCR", "MTTR", "PRCT", "RBOT",
]

# Large-cap tech/biotech for the "all" universe (combined with BROAD)
LARGE_TECH = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSLA", "AMD",
    "CRM", "NFLX", "AVGO", "ORCL", "ADBE", "PLTR", "INTC", "QCOM",
    "MU", "AMAT", "LRCX", "KLAC", "MRVL", "NOW", "SHOP", "SQ",
    "UBER", "ABNB", "DASH", "TTD", "ROKU",
    # Large-cap SaaS / enterprise
    "ACN", "IBM", "CSCO", "TXN", "APH", "SNPS", "CDNS", "ANSS",
    "FICO", "IT", "EPAM", "PAYC", "ADP", "FI", "FISV",
    # Biotech / health-tech large caps
    "LLY", "TMO", "DHR", "GILD", "AMGN", "VRTX", "REGN", "ISRG",
    "MRNA", "BMRN",
    # Tech ETFs
    "QQQ", "SMH", "XLK", "ARKK", "IBB",
    # Broad market ETFs
    "SPY", "IWM", "DIA", "VTI", "VOO", "RSP",
    # International / EM
    "EFA", "EEM", "VWO", "KWEB", "FXI",
    # Bond ETFs — Treasuries
    "TLT",   # 20+ year Treasury (rate-sensitive, big moves)
    "IEF",   # 7-10 year Treasury
    "SHY",   # 1-3 year Treasury (safe haven)
    "BIL",   # T-Bills (cash equivalent, ~5% yield)
    "SHV",   # Short-term Treasury
    "GOVT",  # All-maturity Treasury
    "TIP",   # TIPS (inflation-protected)
    # Bond ETFs — Corporate / Other
    "LQD",   # Investment-grade corporate
    "HYG",   # High-yield corporate (junk)
    "JNK",   # High-yield (alternative)
    "BNDX",  # International bonds
    "EMB",   # Emerging market bonds
    "MBB",   # Mortgage-backed
    # Commodity / Real asset ETFs
    "GLD",   # Gold
    "SLV",   # Silver
    "USO",   # Oil
    "UNG",   # Natural gas
    "DBA",   # Agriculture
    # Volatility / Hedging
    "UVXY",  # 1.5x VIX short-term futures
    "VIXY",  # VIX short-term futures
    # Leveraged (for short-term trades only)
    "TQQQ",  # 3x Nasdaq
    "SQQQ",  # -3x Nasdaq (hedge)
    "SOXL",  # 3x Semiconductors
    "SOXS",  # -3x Semiconductors
    "TMF",   # 3x 20+ year Treasury
    "TBT",   # -2x 20+ year Treasury
]

MODES = ["gainers", "trending_up", "new_highs", "momentum_leaders", "volume_surge", "all"]


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def resolve_tickers(args) -> list[str]:
    """Resolve ticker list from arguments."""
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.universe == "broad":
        return list(BROAD_UNIVERSE)
    if args.universe == "all":
        combined = list(BROAD_UNIVERSE)
        seen = set(t.upper() for t in combined)
        for t in LARGE_TECH:
            if t.upper() not in seen:
                combined.append(t)
                seen.add(t.upper())
        return combined
    return list(BROAD_UNIVERSE)


def download_data(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Batch download price data. Returns dict of ticker -> DataFrame."""
    log(f"Downloading data for {len(tickers)} tickers (period={period})...")

    # Process in chunks to avoid overwhelming yfinance
    chunk_size = 100
    data = {}
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i : i + chunk_size]
        log(f"  Downloading chunk {i // chunk_size + 1} ({len(chunk)} tickers)...")
        try:
            raw = yf.download(
                chunk,
                period=period,
                interval="1d",
                group_by="ticker",
                threads=True,
                progress=False,
            )
        except Exception as e:
            log(f"  Download error for chunk: {e}")
            continue

        if len(chunk) == 1:
            ticker = chunk[0]
            if not raw.empty and len(raw) > 20:
                data[ticker] = raw.copy()
        else:
            for ticker in chunk:
                try:
                    df = raw[ticker].copy()
                    df = df.dropna(how="all")
                    if len(df) > 20:
                        data[ticker] = df
                except (KeyError, Exception):
                    continue

    log(f"Successfully loaded data for {len(data)} / {len(tickers)} tickers")
    return data


def compute_sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def compute_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(window=window, min_periods=window).mean()
    avg_loss = loss.rolling(window=window, min_periods=window).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


# ---------------------------------------------------------------------------
# Discovery Mode: gainers
# ---------------------------------------------------------------------------
def discover_gainers(top: int) -> list[dict]:
    """Find top gaining stocks using yfinance screener or web scraping fallback."""
    log("Running gainers discovery...")
    results = []

    # Strategy 1: Try yfinance's built-in screener
    try:
        log("  Trying yf.screen('day_gainers')...")
        screener_result = yf.screen("day_gainers")
        if screener_result and "quotes" in screener_result:
            quotes = screener_result["quotes"]
            for q in quotes[:top]:
                sym = q.get("symbol", "")
                results.append({
                    "ticker": sym,
                    "price": round(q.get("regularMarketPrice", 0), 2),
                    "change_pct": round(q.get("regularMarketChangePercent", 0), 2),
                    "volume": q.get("regularMarketVolume", 0),
                    "reason": f"Day gainer: +{q.get('regularMarketChangePercent', 0):.1f}%",
                })
            if results:
                log(f"  Found {len(results)} gainers via yf.screen()")
                return results[:top]
    except Exception as e:
        log(f"  yf.screen() not available or failed: {e}")

    # Strategy 2: Try yfinance Screener class
    try:
        log("  Trying yf.Screener()...")
        sc = yf.Screener()
        sc.set_default_body({"query": "day_gainers"})
        resp = sc.response
        if resp and "quotes" in resp:
            for q in resp["quotes"][:top]:
                sym = q.get("symbol", "")
                results.append({
                    "ticker": sym,
                    "price": round(q.get("regularMarketPrice", 0), 2),
                    "change_pct": round(q.get("regularMarketChangePercent", 0), 2),
                    "volume": q.get("regularMarketVolume", 0),
                    "reason": f"Day gainer: +{q.get('regularMarketChangePercent', 0):.1f}%",
                })
            if results:
                log(f"  Found {len(results)} gainers via yf.Screener()")
                return results[:top]
    except Exception as e:
        log(f"  yf.Screener() not available or failed: {e}")

    # Strategy 3: Try web scraping Yahoo Finance pages
    try:
        import requests

        log("  Trying web scrape of Yahoo Finance gainers page...")
        urls = [
            ("gainers", "https://finance.yahoo.com/markets/stocks/gainers/"),
            ("most_active", "https://finance.yahoo.com/markets/stocks/most-active/"),
            ("trending", "https://finance.yahoo.com/markets/stocks/trending/"),
        ]
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }

        for label, url in urls:
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code != 200:
                    continue
                text = resp.text

                # Try to parse tickers from the page using regex
                # Yahoo Finance pages contain ticker symbols in various formats
                # Look for patterns like "data-symbol=\"AAPL\"" or "/quote/AAPL"
                symbol_matches = re.findall(r'data-symbol="([A-Z]{1,5})"', text)
                if not symbol_matches:
                    symbol_matches = re.findall(r'/quote/([A-Z]{1,5})["\?/]', text)

                if symbol_matches:
                    # Deduplicate while preserving order
                    seen = set()
                    unique_symbols = []
                    for s in symbol_matches:
                        if s not in seen and len(s) <= 5:
                            seen.add(s)
                            unique_symbols.append(s)

                    log(f"  Found {len(unique_symbols)} tickers from {label} page")

                    # Fetch current data for these tickers
                    if unique_symbols:
                        tickers_to_check = unique_symbols[:30]
                        data = download_data(tickers_to_check, period="5d")
                        for ticker, df in data.items():
                            try:
                                close = df["Close"].squeeze()
                                if len(close) < 2:
                                    continue
                                current = float(close.iloc[-1])
                                prev = float(close.iloc[-2])
                                change_pct = ((current / prev) - 1) * 100
                                vol = float(df["Volume"].squeeze().iloc[-1])
                                results.append({
                                    "ticker": ticker,
                                    "price": round(current, 2),
                                    "change_pct": round(change_pct, 2),
                                    "volume": int(vol),
                                    "reason": f"Found on Yahoo {label}: {change_pct:+.1f}% today",
                                })
                            except Exception:
                                continue

                    if results:
                        results.sort(key=lambda x: x["change_pct"], reverse=True)
                        return results[:top]

            except Exception as e:
                log(f"  Failed to scrape {label}: {e}")
                continue

    except ImportError:
        log("  requests not available for web scraping")

    # Strategy 4: Fallback — scan a broader universe for today's biggest movers
    log("  Falling back to scanning broad universe for today's gainers...")
    fallback_tickers = BROAD_UNIVERSE[:100]
    data = download_data(fallback_tickers, period="5d")
    for ticker, df in data.items():
        try:
            close = df["Close"].squeeze()
            if len(close) < 2:
                continue
            current = float(close.iloc[-1])
            prev = float(close.iloc[-2])
            change_pct = ((current / prev) - 1) * 100
            vol = float(df["Volume"].squeeze().iloc[-1])
            results.append({
                "ticker": ticker,
                "price": round(current, 2),
                "change_pct": round(change_pct, 2),
                "volume": int(vol),
                "reason": f"Today's change: {change_pct:+.1f}%",
            })
        except Exception:
            continue

    results.sort(key=lambda x: x["change_pct"], reverse=True)
    return results[:top]


# ---------------------------------------------------------------------------
# Discovery Mode: trending_up (Minervini trend template)
# ---------------------------------------------------------------------------
def discover_trending_up(data: dict[str, pd.DataFrame], top: int) -> list[dict]:
    """Find stocks in strong uptrends using Mark Minervini's trend template."""
    log("Running trending_up discovery (Minervini template)...")
    results = []

    for ticker, df in data.items():
        try:
            close = df["Close"].squeeze()
            if len(close) < 200:
                continue

            current_price = float(close.iloc[-1])
            sma_50 = float(compute_sma(close, 50).iloc[-1])
            sma_200 = float(compute_sma(close, 200).iloc[-1])
            rsi = float(compute_rsi(close).iloc[-1])

            if pd.isna(sma_50) or pd.isna(sma_200) or pd.isna(rsi):
                continue

            high_52w = float(close.iloc[-252:].max())
            low_52w = float(close.iloc[-252:].min())

            if low_52w <= 0:
                continue

            # Minervini criteria
            # 1. Price > SMA_50 > SMA_200
            if not (current_price > sma_50 > sma_200):
                continue
            # 2. RSI between 50-80 (strong but not overbought)
            if not (50 <= rsi <= 80):
                continue
            # 3. Price within 25% of 52-week high
            if current_price < high_52w * 0.75:
                continue
            # 4. Price at least 50% above 52-week low
            if current_price < low_52w * 1.50:
                continue

            pct_from_high = ((current_price / high_52w) - 1) * 100
            pct_from_low = ((current_price / low_52w) - 1) * 100

            # Composite score: closer to high + higher RSI + wider MA spread
            ma_spread = ((sma_50 / sma_200) - 1) * 100
            score = (100 + pct_from_high) + rsi * 0.5 + ma_spread * 2

            results.append({
                "ticker": ticker,
                "price": round(current_price, 2),
                "sma_50": round(sma_50, 2),
                "sma_200": round(sma_200, 2),
                "rsi": round(rsi, 2),
                "pct_from_52w_high": round(pct_from_high, 2),
                "pct_above_52w_low": round(pct_from_low, 2),
                "ma_spread_pct": round(ma_spread, 2),
                "score": round(score, 2),
                "reason": (
                    f"Minervini trend: Price ${current_price:.2f} > SMA50 ${sma_50:.2f} > SMA200 ${sma_200:.2f}, "
                    f"RSI={rsi:.0f}, {pct_from_high:.1f}% from 52w high, {pct_from_low:.0f}% above 52w low"
                ),
            })
        except Exception:
            continue

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top]


# ---------------------------------------------------------------------------
# Discovery Mode: new_highs
# ---------------------------------------------------------------------------
def discover_new_highs(data: dict[str, pd.DataFrame], top: int) -> list[dict]:
    """Find stocks making new 52-week highs (within 2% of high)."""
    log("Running new_highs discovery...")
    results = []

    for ticker, df in data.items():
        try:
            close = df["Close"].squeeze()
            if len(close) < 200:
                continue

            current_price = float(close.iloc[-1])
            high_52w = float(close.iloc[-252:].max())
            low_52w = float(close.iloc[-252:].min())

            if high_52w <= 0 or low_52w <= 0:
                continue

            pct_from_high = ((current_price / high_52w) - 1) * 100

            # Within 2% of 52-week high
            if pct_from_high < -2.0:
                continue

            pct_range = ((current_price - low_52w) / (high_52w - low_52w)) * 100 if high_52w != low_52w else 100
            vol = float(df["Volume"].squeeze().iloc[-1])
            avg_vol = float(df["Volume"].squeeze().iloc[-20:].mean())
            vol_ratio = vol / avg_vol if avg_vol > 0 else 1.0

            results.append({
                "ticker": ticker,
                "price": round(current_price, 2),
                "high_52w": round(high_52w, 2),
                "low_52w": round(low_52w, 2),
                "pct_from_high": round(pct_from_high, 2),
                "pct_of_52w_range": round(pct_range, 2),
                "volume_ratio": round(vol_ratio, 2),
                "reason": (
                    f"Near 52-week high: ${current_price:.2f} vs high ${high_52w:.2f} "
                    f"({pct_from_high:+.1f}%), volume {vol_ratio:.1f}x avg"
                ),
            })
        except Exception:
            continue

    results.sort(key=lambda x: x["pct_from_high"], reverse=True)
    return results[:top]


# ---------------------------------------------------------------------------
# Discovery Mode: momentum_leaders
# ---------------------------------------------------------------------------
def discover_momentum_leaders(data: dict[str, pd.DataFrame], top: int) -> list[dict]:
    """Rank by 3-month return, filtered to stocks above their 50-day MA."""
    log("Running momentum_leaders discovery...")
    results = []

    for ticker, df in data.items():
        try:
            close = df["Close"].squeeze()
            if len(close) < 63:  # ~3 months
                continue

            current_price = float(close.iloc[-1])
            price_3m_ago = float(close.iloc[-63])
            sma_50 = float(compute_sma(close, 50).iloc[-1])

            if pd.isna(sma_50) or price_3m_ago <= 0:
                continue

            # Must be above 50-day MA
            if current_price <= sma_50:
                continue

            return_3m = ((current_price / price_3m_ago) - 1) * 100

            # Also compute 1-month return for context
            if len(close) >= 21:
                price_1m_ago = float(close.iloc[-21])
                return_1m = ((current_price / price_1m_ago) - 1) * 100
            else:
                return_1m = 0.0

            results.append({
                "ticker": ticker,
                "price": round(current_price, 2),
                "sma_50": round(sma_50, 2),
                "return_3m_pct": round(return_3m, 2),
                "return_1m_pct": round(return_1m, 2),
                "pct_above_sma50": round(((current_price / sma_50) - 1) * 100, 2),
                "reason": (
                    f"Momentum leader: +{return_3m:.1f}% (3mo), +{return_1m:.1f}% (1mo), "
                    f"{((current_price / sma_50) - 1) * 100:.1f}% above SMA50"
                ),
            })
        except Exception:
            continue

    results.sort(key=lambda x: x["return_3m_pct"], reverse=True)
    return results[:top]


# ---------------------------------------------------------------------------
# Discovery Mode: volume_surge
# ---------------------------------------------------------------------------
def discover_volume_surge(data: dict[str, pd.DataFrame], top: int) -> list[dict]:
    """Find stocks with today's volume > 3x their 20-day average volume."""
    log("Running volume_surge discovery...")
    results = []

    for ticker, df in data.items():
        try:
            close = df["Close"].squeeze()
            volume = df["Volume"].squeeze()
            if len(close) < 21:
                continue

            current_price = float(close.iloc[-1])
            prev_price = float(close.iloc[-2])
            current_vol = float(volume.iloc[-1])
            avg_vol_20 = float(volume.iloc[-21:-1].mean())

            if avg_vol_20 <= 0 or current_vol <= 0:
                continue

            vol_ratio = current_vol / avg_vol_20

            # Volume must be > 3x average
            if vol_ratio < 3.0:
                continue

            price_change_pct = ((current_price / prev_price) - 1) * 100

            results.append({
                "ticker": ticker,
                "price": round(current_price, 2),
                "change_pct": round(price_change_pct, 2),
                "volume": int(current_vol),
                "avg_volume_20d": int(avg_vol_20),
                "volume_ratio": round(vol_ratio, 2),
                "reason": (
                    f"Volume surge: {vol_ratio:.1f}x average ({int(current_vol):,} vs "
                    f"{int(avg_vol_20):,} avg), price {price_change_pct:+.1f}%"
                ),
            })
        except Exception:
            continue

    results.sort(key=lambda x: x["volume_ratio"], reverse=True)
    return results[:top]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Discover trending stocks beyond fixed watchlists"
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=MODES,
        help="Discovery mode to run",
    )
    parser.add_argument(
        "--universe",
        default="broad",
        choices=["broad", "all"],
        help="Ticker universe: 'broad' (~200 non-SP500), 'all' (~700 broad+SP500)",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated ticker override (replaces universe)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Max results per mode (default: 15)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="/tmp/discover_results.json",
        help="Output file path (default: /tmp/discover_results.json)",
    )
    args = parser.parse_args()

    modes_to_run = MODES[:-1] if args.mode == "all" else [args.mode]
    tickers = resolve_tickers(args)

    log(f"=== Stock Discovery ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")
    log(f"Modes: {', '.join(modes_to_run)}")
    log(f"Universe: {len(tickers)} tickers")

    # gainers mode does its own data fetching; others share a batch download
    needs_bulk_data = any(m != "gainers" for m in modes_to_run)
    data = {}
    if needs_bulk_data:
        data = download_data(tickers, period="1y")

    all_results = {}

    for mode in modes_to_run:
        log(f"\n--- Mode: {mode} ---")
        try:
            if mode == "gainers":
                results = discover_gainers(args.top)
            elif mode == "trending_up":
                results = discover_trending_up(data, args.top)
            elif mode == "new_highs":
                results = discover_new_highs(data, args.top)
            elif mode == "momentum_leaders":
                results = discover_momentum_leaders(data, args.top)
            elif mode == "volume_surge":
                results = discover_volume_surge(data, args.top)
            else:
                results = []

            all_results[mode] = results
            log(f"  Found {len(results)} results for {mode}")
        except Exception as e:
            log(f"  Error in {mode}: {e}")
            all_results[mode] = []

    # Build output
    output = {
        "timestamp": datetime.now().isoformat(),
        "modes": list(all_results.keys()),
        "universe_size": len(tickers),
        "results": all_results,
        "summary": {
            mode: {
                "count": len(res),
                "tickers": [r["ticker"] for r in res],
            }
            for mode, res in all_results.items()
        },
    }

    # Save to file
    try:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2, default=str)
        log(f"\nResults saved to {args.output}")
    except Exception as e:
        log(f"Error saving to {args.output}: {e}")

    # Print to stdout
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
