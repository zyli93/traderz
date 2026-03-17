#!/usr/bin/env python3
"""
research_digest.py — Comprehensive research digest for any stock or crypto.

Usage:
    python research_digest.py --ticker NVDA
    python research_digest.py --ticker BTC-USD
    python research_digest.py --ticker AAPL --period 1y

Outputs:
    - Human-readable digest to stdout
    - JSON data to /tmp/research_TICKER.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
import ta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[research] {msg}", file=sys.stderr)


def safe_round(val, decimals=2):
    try:
        return round(float(val), decimals)
    except (TypeError, ValueError):
        return None


def pct_change_over(series: pd.Series, days: int):
    if series is None or len(series) < days + 1:
        return None
    current = series.iloc[-1]
    prior = series.iloc[-(days + 1)]
    if prior == 0:
        return None
    return (current - prior) / prior * 100


def load_credentials():
    creds = {}
    config_path = os.path.expanduser("~/.config/traderz/credentials.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            stored = json.load(f)
        creds.update(stored)
    # Env vars override
    for key in ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "FRED_API_KEY"]:
        val = os.environ.get(key)
        if val:
            creds[key] = val
    return creds


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def fetch_price_and_technicals(symbol: str, period: str) -> dict:
    """Fetch OHLCV data and compute technical indicators."""
    log(f"Fetching price data for {symbol}...")
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval="1d")

    if df.empty:
        return {"error": f"No data for {symbol}"}

    df.index = df.index.tz_localize(None) if df.index.tz else df.index

    latest = df.iloc[-1]
    prev = df.iloc[-2]["Close"] if len(df) > 1 else latest["Close"]
    close = df["Close"]

    # Performance
    perf = {}
    for label, days in [("1d", 1), ("5d", 5), ("20d", 20), ("3mo", 63)]:
        perf[label] = safe_round(pct_change_over(close, days))

    # Technical indicators
    ind = {}

    # Moving averages
    for w in [20, 50, 200]:
        sma = ta.trend.sma_indicator(close, window=w)
        val = sma.iloc[-1] if pd.notna(sma.iloc[-1]) else None
        ind[f"SMA_{w}"] = safe_round(val)

    for w in [12, 26]:
        ema = ta.trend.ema_indicator(close, window=w)
        val = ema.iloc[-1] if pd.notna(ema.iloc[-1]) else None
        ind[f"EMA_{w}"] = safe_round(val)

    # MACD
    macd = ta.trend.MACD(close)
    ind["MACD"] = safe_round(macd.macd().iloc[-1], 4)
    ind["MACD_signal"] = safe_round(macd.macd_signal().iloc[-1], 4)
    ind["MACD_histogram"] = safe_round(macd.macd_diff().iloc[-1], 4)

    # RSI
    rsi = ta.momentum.rsi(close, window=14)
    ind["RSI_14"] = safe_round(rsi.iloc[-1])

    # Stochastic
    stoch = ta.momentum.StochasticOscillator(df["High"], df["Low"], close)
    ind["Stochastic_K"] = safe_round(stoch.stoch().iloc[-1])
    ind["Stochastic_D"] = safe_round(stoch.stoch_signal().iloc[-1])

    # ADX
    adx = ta.trend.ADXIndicator(df["High"], df["Low"], close)
    ind["ADX"] = safe_round(adx.adx().iloc[-1])

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(close)
    ind["BB_upper"] = safe_round(bb.bollinger_hband().iloc[-1])
    ind["BB_lower"] = safe_round(bb.bollinger_lband().iloc[-1])

    # ATR
    atr = ta.volatility.average_true_range(df["High"], df["Low"], close)
    ind["ATR_14"] = safe_round(atr.iloc[-1])

    # Volume
    vol_sma = df["Volume"].rolling(20).mean()
    vol_ratio = df["Volume"].iloc[-1] / vol_sma.iloc[-1] if pd.notna(vol_sma.iloc[-1]) and vol_sma.iloc[-1] > 0 else None
    ind["volume_vs_avg"] = safe_round(vol_ratio)

    # Support/Resistance
    recent = df.tail(20)
    levels = {
        "recent_high": safe_round(recent["High"].max()),
        "recent_low": safe_round(recent["Low"].min()),
        "52w_high": safe_round(df.tail(252)["High"].max()) if len(df) >= 252 else safe_round(df["High"].max()),
        "52w_low": safe_round(df.tail(252)["Low"].min()) if len(df) >= 252 else safe_round(df["Low"].min()),
    }

    # Recent prices (last 5 days)
    recent_prices = []
    for idx, row in df.tail(5).iterrows():
        recent_prices.append({
            "date": idx.strftime("%Y-%m-%d"),
            "close": safe_round(row["Close"]),
            "volume": int(row["Volume"]),
        })

    # Signal summary
    signals = []
    price = safe_round(latest["Close"])

    if ind["RSI_14"] and ind["RSI_14"] > 70:
        signals.append("RSI overbought (>70)")
    elif ind["RSI_14"] and ind["RSI_14"] < 30:
        signals.append("RSI oversold (<30)")

    if ind["MACD"] is not None and ind["MACD_signal"] is not None:
        if ind["MACD"] > ind["MACD_signal"]:
            signals.append("MACD bullish crossover")
        else:
            signals.append("MACD bearish crossover")

    if ind["SMA_50"] and ind["SMA_200"]:
        if ind["SMA_50"] > ind["SMA_200"]:
            signals.append("Golden cross (SMA50 > SMA200)")
        else:
            signals.append("Death cross (SMA50 < SMA200)")

    if ind["SMA_50"] and price:
        pct_from_sma50 = (price - ind["SMA_50"]) / ind["SMA_50"] * 100
        if pct_from_sma50 < -5:
            signals.append(f"Price {pct_from_sma50:.1f}% below SMA50")
        elif pct_from_sma50 > 5:
            signals.append(f"Price {pct_from_sma50:.1f}% above SMA50")

    if ind["BB_lower"] and price and price < ind["BB_lower"]:
        signals.append("Below lower Bollinger Band")
    elif ind["BB_upper"] and price and price > ind["BB_upper"]:
        signals.append("Above upper Bollinger Band")

    return {
        "current_price": price,
        "price_change": safe_round(latest["Close"] - prev),
        "price_change_pct": safe_round((latest["Close"] - prev) / prev * 100),
        "volume": int(latest["Volume"]),
        "performance": perf,
        "indicators": ind,
        "support_resistance": levels,
        "signals": signals,
        "recent_prices": recent_prices,
    }


def fetch_fundamentals(symbol: str) -> dict:
    """Fetch fundamental data."""
    log(f"Fetching fundamentals for {symbol}...")
    try:
        tk = yf.Ticker(symbol)
        info = tk.info
        fields = [
            "shortName", "longName", "sector", "industry", "marketCap",
            "trailingPE", "forwardPE", "dividendYield", "beta",
            "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "averageVolume",
            "earningsDate", "revenueGrowth", "profitMargins",
            "returnOnEquity", "debtToEquity", "freeCashflow",
            "currentPrice", "description",
        ]
        result = {}
        for f in fields:
            val = info.get(f)
            if val is not None:
                if isinstance(val, (int, float)) and pd.notna(val):
                    result[f] = val
                elif isinstance(val, str):
                    result[f] = val
                elif isinstance(val, list):
                    result[f] = [str(v) for v in val]
        return result
    except Exception as e:
        log(f"  Fundamentals error: {e}")
        return {}


def fetch_analyst(symbol: str) -> dict:
    """Fetch analyst consensus data."""
    log(f"Fetching analyst data for {symbol}...")
    result = {}
    try:
        tk = yf.Ticker(symbol)
        info = tk.info
        current_price = info.get("currentPrice") or info.get("regularMarketPrice")

        # Price targets
        try:
            apt = tk.analyst_price_targets
            if apt and isinstance(apt, dict):
                result["price_targets"] = {
                    "current": apt.get("current"),
                    "mean": apt.get("mean"),
                    "high": apt.get("high"),
                    "low": apt.get("low"),
                }
        except Exception:
            pass

        # Recommendations summary
        try:
            rs = tk.recommendations_summary
            if rs is not None and isinstance(rs, pd.DataFrame) and not rs.empty:
                latest = rs.iloc[0].to_dict()
                result["ratings"] = {
                    "strongBuy": int(latest.get("strongBuy", 0)),
                    "buy": int(latest.get("buy", 0)),
                    "hold": int(latest.get("hold", 0)),
                    "sell": int(latest.get("sell", 0)),
                    "strongSell": int(latest.get("strongSell", 0)),
                }
        except Exception:
            pass

        # Recent changes
        try:
            recs = tk.recommendations
            if recs is not None and isinstance(recs, pd.DataFrame) and not recs.empty:
                changes = []
                for _, row in recs.tail(5).iterrows():
                    firm = row.get("Firm", "")
                    grade = row.get("To Grade", "")
                    action = row.get("Action", "")
                    if firm or grade:
                        changes.append(f"{firm}: {action} -> {grade}")
                changes.reverse()
                if changes:
                    result["recent_changes"] = changes
        except Exception:
            pass

        # Derived
        mean_target = (result.get("price_targets") or {}).get("mean")
        if mean_target and current_price and current_price > 0:
            result["upside_pct"] = safe_round((mean_target - current_price) / current_price * 100, 1)

        ratings = result.get("ratings", {})
        total = sum(ratings.values())
        if total > 0:
            weighted = (
                ratings.get("strongBuy", 0) * 5
                + ratings.get("buy", 0) * 4
                + ratings.get("hold", 0) * 3
                + ratings.get("sell", 0) * 2
                + ratings.get("strongSell", 0) * 1
            )
            result["consensus_score"] = safe_round(weighted / total)
            buy_count = ratings.get("strongBuy", 0) + ratings.get("buy", 0)
            result["buy_pct"] = round(buy_count / total * 100)

    except Exception as e:
        log(f"  Analyst error: {e}")

    return result


def fetch_news(symbol: str) -> dict:
    """Fetch news headlines."""
    log(f"Fetching news for {symbol}...")
    headlines = []
    source = "none"

    # Try Alpaca first
    creds = load_credentials()
    if creds.get("ALPACA_API_KEY") and creds.get("ALPACA_SECRET_KEY"):
        try:
            from alpaca.data import NewsClient
            from alpaca.data.requests import NewsRequest

            client = NewsClient(
                api_key=creds["ALPACA_API_KEY"],
                secret_key=creds["ALPACA_SECRET_KEY"],
            )
            # Strip -USD suffix for crypto tickers in Alpaca format
            alpaca_sym = symbol.replace("-USD", "USD")
            request = NewsRequest(symbols=alpaca_sym, limit=20)
            news_set = client.get_news(request)
            news_items = news_set.data.get("news", []) if news_set.data else []

            seen = set()
            for item in news_items:
                title = item.headline
                if title in seen:
                    continue
                seen.add(title)
                headlines.append({
                    "title": title,
                    "summary": (item.summary or "")[:200].strip() or None,
                    "source": item.source if hasattr(item, "source") else None,
                    "published": str(item.created_at)[:19] if item.created_at else None,
                    "url": item.url if hasattr(item, "url") else None,
                })
            source = "alpaca"
        except Exception as e:
            log(f"  Alpaca news failed: {e}")

    # Fallback: yfinance
    if not headlines:
        try:
            tk = yf.Ticker(symbol)
            news_items = tk.news or []
            seen = set()
            for item in news_items[:15]:
                title = item.get("title", "")
                if not title or title in seen:
                    continue
                seen.add(title)
                pub = item.get("providerPublishTime")
                if pub and isinstance(pub, (int, float)):
                    pub = datetime.fromtimestamp(pub).strftime("%Y-%m-%d %H:%M")
                headlines.append({
                    "title": title,
                    "summary": None,
                    "source": item.get("publisher"),
                    "published": str(pub) if pub else None,
                    "url": item.get("link"),
                })
            source = "yfinance"
        except Exception as e:
            log(f"  yfinance news failed: {e}")

    return {"headlines": headlines[:15], "source": source, "count": len(headlines[:15])}


def compute_sentiment(headlines: list[dict], symbol: str) -> dict:
    """Keyword-based headline sentiment."""
    BULLISH = [
        "upgrade", "beat", "surge", "rally", "buy", "record", "growth",
        "outperform", "bullish", "soar", "breakout", "boost", "gain",
        "strong", "positive", "optimistic", "raises guidance", "accelerate",
        "momentum", "overweight", "top pick", "exceeds", "partnership",
        "expands", "launches", "innovation",
    ]
    BEARISH = [
        "downgrade", "miss", "cut", "crash", "recession", "layoff",
        "sell", "plunge", "bearish", "decline", "drop", "slump", "weak",
        "negative", "warning", "risk", "loss", "underperform", "underweight",
        "lowers guidance", "disappointing", "worst", "falls", "tumble",
        "investigation", "lawsuit", "fine",
    ]

    bull_hits = 0
    bear_hits = 0
    for h in headlines:
        title = (h.get("title") or "").lower()
        bull_hits += sum(1 for w in BULLISH if w in title)
        bear_hits += sum(1 for w in BEARISH if w in title)

    total = bull_hits + bear_hits
    ratio = safe_round(bull_hits / total) if total > 0 else 0.5
    if ratio > 0.6:
        classification = "bullish"
    elif ratio < 0.4:
        classification = "bearish"
    else:
        classification = "neutral"

    return {
        "bullish_hits": bull_hits,
        "bearish_hits": bear_hits,
        "ratio": ratio,
        "classification": classification,
    }


def fetch_macro_snapshot() -> dict:
    """Quick macro regime check via ETF proxies."""
    log("Fetching macro snapshot...")
    etfs = ["^VIX", "TLT", "SHY", "UUP", "HYG", "LQD", "RSP", "SPY"]
    try:
        data = yf.download(etfs, period="1mo", interval="1d",
                           group_by="ticker", progress=False)
    except Exception as e:
        return {"error": str(e)}

    def get_close(sym):
        try:
            return data[sym]["Close"].dropna()
        except Exception:
            return pd.Series(dtype=float)

    signals = {}

    # VIX
    vix = get_close("^VIX")
    if len(vix) >= 2:
        level = safe_round(vix.iloc[-1])
        if level < 15: regime = "low"
        elif level < 20: regime = "normal"
        elif level < 30: regime = "elevated"
        else: regime = "extreme"
        signals["VIX"] = f"{level} ({regime})"

    # Yields
    tlt = get_close("TLT")
    if len(tlt) >= 6:
        chg = safe_round(pct_change_over(tlt, 5))
        signals["Long rates"] = "falling (risk-on)" if chg and chg > 0 else "rising (risk-off)"

    # Dollar
    uup = get_close("UUP")
    if len(uup) >= 6:
        chg = safe_round(pct_change_over(uup, 5))
        if chg and chg > 0.3: signals["Dollar"] = "strengthening (headwind)"
        elif chg and chg < -0.3: signals["Dollar"] = "weakening (tailwind)"
        else: signals["Dollar"] = "stable"

    # Credit
    hyg = get_close("HYG")
    lqd = get_close("LQD")
    if len(hyg) >= 6 and len(lqd) >= 6:
        hyg_chg = pct_change_over(hyg, 5)
        lqd_chg = pct_change_over(lqd, 5)
        if hyg_chg is not None and lqd_chg is not None:
            spread = hyg_chg - lqd_chg
            if spread < -0.5: signals["Credit"] = "stress"
            elif spread > 0.5: signals["Credit"] = "healthy"
            else: signals["Credit"] = "neutral"

    # Breadth
    rsp = get_close("RSP")
    spy = get_close("SPY")
    if len(rsp) >= 6 and len(spy) >= 6:
        rsp_chg = pct_change_over(rsp, 5)
        spy_chg = pct_change_over(spy, 5)
        if rsp_chg is not None and spy_chg is not None:
            diff = rsp_chg - spy_chg
            if diff > 0.5: signals["Breadth"] = "broad (healthy)"
            elif diff < -0.5: signals["Breadth"] = "narrow (fragile)"
            else: signals["Breadth"] = "balanced"

    return signals


def fetch_calendar(symbol: str) -> list:
    """Check upcoming events."""
    today = datetime.now().date()
    horizon = today + timedelta(days=14)
    events = []

    # Earnings
    try:
        tk = yf.Ticker(symbol)
        cal = tk.calendar
        earnings_date = None
        if cal is not None:
            if isinstance(cal, pd.DataFrame):
                if "Earnings Date" in cal.index:
                    raw = cal.loc["Earnings Date"].iloc[0]
                    if hasattr(raw, "date"):
                        earnings_date = raw.date()
            elif isinstance(cal, dict):
                raw = cal.get("Earnings Date")
                if raw:
                    if isinstance(raw, list) and len(raw) > 0:
                        raw = raw[0]
                    if hasattr(raw, "date"):
                        earnings_date = raw.date()
        if earnings_date and today <= earnings_date <= horizon:
            days = (earnings_date - today).days
            events.append(f"EARNINGS in {days}d ({earnings_date}) — binary event risk")
    except Exception:
        pass

    # Hard-coded 2026 dates
    # TODO: Update for 2027
    FOMC = ["2026-01-28","2026-03-18","2026-05-06","2026-06-17","2026-07-29","2026-09-16","2026-11-04","2026-12-16"]
    CPI = ["2026-01-14","2026-02-11","2026-03-11","2026-04-14","2026-05-12","2026-06-10","2026-07-14","2026-08-12","2026-09-15","2026-10-13","2026-11-12","2026-12-09"]
    JOBS = ["2026-01-09","2026-02-06","2026-03-06","2026-04-03","2026-05-08","2026-06-05","2026-07-02","2026-08-07","2026-09-04","2026-10-02","2026-11-06","2026-12-04"]

    for dates, label in [(FOMC, "FOMC"), (CPI, "CPI"), (JOBS, "JOBS")]:
        for ds in dates:
            d = datetime.strptime(ds, "%Y-%m-%d").date()
            if today <= d <= horizon:
                days = (d - today).days
                events.append(f"{label} in {days}d ({ds})")

    return events


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_verdict(technicals: dict, analyst: dict, sentiment: dict, macro: dict, calendar: list) -> dict:
    """Generate an overall verdict."""
    bull_points = []
    bear_points = []
    caution_points = []

    ind = technicals.get("indicators", {})
    perf = technicals.get("performance", {})

    # Technicals
    rsi = ind.get("RSI_14")
    if rsi and rsi < 30:
        bull_points.append(f"RSI oversold ({rsi})")
    elif rsi and rsi > 70:
        bear_points.append(f"RSI overbought ({rsi})")

    macd_h = ind.get("MACD_histogram")
    if macd_h and macd_h > 0:
        bull_points.append("MACD bullish")
    elif macd_h and macd_h < 0:
        bear_points.append("MACD bearish")

    # Trend
    price = technicals.get("current_price")
    sma50 = ind.get("SMA_50")
    if price and sma50:
        if price > sma50:
            bull_points.append("Above SMA50")
        else:
            bear_points.append("Below SMA50")

    # Performance
    p5d = perf.get("5d")
    if p5d and p5d > 3:
        bull_points.append(f"Strong 5d momentum (+{p5d}%)")
    elif p5d and p5d < -3:
        bear_points.append(f"Weak 5d momentum ({p5d}%)")

    # Analyst
    upside = analyst.get("upside_pct")
    if upside and upside > 20:
        bull_points.append(f"Analyst target +{upside}% upside")
    buy_pct = analyst.get("buy_pct")
    if buy_pct and buy_pct > 70:
        bull_points.append(f"{buy_pct}% analysts say Buy")

    # Sentiment
    sent_class = sentiment.get("classification")
    if sent_class == "bullish":
        bull_points.append("News sentiment bullish")
    elif sent_class == "bearish":
        bear_points.append("News sentiment bearish")

    # Macro
    vix_str = macro.get("VIX", "")
    if "extreme" in vix_str:
        caution_points.append("VIX extreme — high volatility")
    elif "elevated" in vix_str:
        caution_points.append("VIX elevated")

    # Calendar
    for e in calendar:
        if "FOMC" in e or "EARNINGS" in e:
            days_str = e.split("in ")[1].split("d")[0] if "in " in e else "?"
            try:
                if int(days_str) <= 3:
                    caution_points.append(e)
            except ValueError:
                caution_points.append(e)

    # Overall
    bull_score = len(bull_points)
    bear_score = len(bear_points)
    if caution_points:
        overall = "CAUTIOUS"
        summary = "Mixed signals with near-term event risk"
    elif bull_score >= bear_score + 2:
        overall = "BULLISH"
        summary = "Multiple bullish signals aligned"
    elif bear_score >= bull_score + 2:
        overall = "BEARISH"
        summary = "Multiple bearish signals aligned"
    else:
        overall = "NEUTRAL"
        summary = "No clear directional edge"

    return {
        "overall": overall,
        "summary": summary,
        "bullish_factors": bull_points,
        "bearish_factors": bear_points,
        "caution_factors": caution_points,
    }


def print_report(symbol: str, data: dict) -> None:
    """Print a human-readable digest to stdout."""
    t = data["technicals"]
    f = data["fundamentals"]
    a = data["analyst"]
    n = data["news"]
    s = data["sentiment"]
    m = data["macro"]
    c = data["calendar"]
    v = data["verdict"]

    ind = t["indicators"]
    perf = t["performance"]
    lvl = t["support_resistance"]

    name = f.get("shortName") or f.get("longName") or symbol

    print("=" * 70)
    print(f"  RESEARCH DIGEST: {name} ({symbol})")
    print(f"  Generated: {data['generated_at'][:19]}")
    print("=" * 70)

    # Price
    print()
    print(f"  PRICE: ${t['current_price']}  ({t['price_change_pct']:+.1f}% today)")
    print(f"  Performance:  1d {perf.get('1d') or '?':>6}%  |  5d {perf.get('5d') or '?':>6}%  |  20d {perf.get('20d') or '?':>6}%  |  3mo {perf.get('3mo') or '?':>6}%")
    print(f"  Range (20d):  ${lvl['recent_low']} - ${lvl['recent_high']}")
    print(f"  Range (52w):  ${lvl['52w_low']} - ${lvl['52w_high']}")

    # Fundamentals
    if f:
        print()
        print("  FUNDAMENTALS")
        parts = []
        if f.get("sector"): parts.append(f"Sector: {f['sector']}")
        if f.get("marketCap"): parts.append(f"Mkt Cap: ${f['marketCap']/1e9:.0f}B")
        if f.get("trailingPE"): parts.append(f"P/E: {f['trailingPE']:.1f}")
        if f.get("forwardPE"): parts.append(f"Fwd P/E: {f['forwardPE']:.1f}")
        if f.get("beta"): parts.append(f"Beta: {f['beta']:.2f}")
        if f.get("dividendYield"): parts.append(f"Div: {f['dividendYield']*100:.2f}%")
        if f.get("revenueGrowth"): parts.append(f"Rev Growth: {f['revenueGrowth']*100:.1f}%")
        if f.get("profitMargins"): parts.append(f"Margin: {f['profitMargins']*100:.1f}%")
        for p in parts:
            print(f"    {p}")

    # Technicals
    print()
    print("  TECHNICAL INDICATORS")
    print(f"    RSI(14): {ind.get('RSI_14')}  |  StochK: {ind.get('Stochastic_K')}  |  ADX: {ind.get('ADX')}")
    print(f"    MACD: {ind.get('MACD')}  sig: {ind.get('MACD_signal')}  hist: {ind.get('MACD_histogram')}")
    print(f"    SMA20: {ind.get('SMA_20')}  SMA50: {ind.get('SMA_50')}  SMA200: {ind.get('SMA_200')}")
    print(f"    Bollinger: [{ind.get('BB_lower')} - {ind.get('BB_upper')}]  ATR: {ind.get('ATR_14')}")
    print(f"    Volume vs avg: {ind.get('volume_vs_avg')}x")
    if t["signals"]:
        print(f"    Signals: {', '.join(t['signals'])}")

    # Analyst
    if a:
        print()
        print("  ANALYST CONSENSUS")
        pt = a.get("price_targets", {})
        if pt:
            print(f"    Target: ${pt.get('mean', '?'):.0f} (range ${pt.get('low', '?'):.0f}-${pt.get('high', '?'):.0f})")
            if a.get("upside_pct"):
                print(f"    Implied upside: {a['upside_pct']:+.1f}%")
        r = a.get("ratings", {})
        if r:
            total = sum(r.values())
            print(f"    Ratings ({total} analysts): {r.get('strongBuy',0)} SB | {r.get('buy',0)} Buy | {r.get('hold',0)} Hold | {r.get('sell',0)} Sell")
            if a.get("consensus_score"):
                print(f"    Consensus score: {a['consensus_score']}/5.0  |  Buy rate: {a.get('buy_pct', '?')}%")
        if a.get("recent_changes"):
            print("    Recent changes:")
            for ch in a["recent_changes"][:3]:
                print(f"      {ch}")

    # News
    if n.get("headlines"):
        print()
        print(f"  NEWS ({n['count']} headlines from {n['source']})")
        for h in n["headlines"][:8]:
            ts = (h.get("published") or "")[:10]
            print(f"    [{ts}] {h['title'][:80]}")

    # Sentiment
    print()
    print(f"  SENTIMENT: {s['classification'].upper()} (ratio={s['ratio']}, {s['bullish_hits']} bullish / {s['bearish_hits']} bearish keywords)")

    # Macro
    if m:
        print()
        print("  MACRO CONTEXT")
        for k, val in m.items():
            print(f"    {k}: {val}")

    # Calendar
    if c:
        print()
        print("  UPCOMING EVENTS")
        for e in c:
            print(f"    >> {e}")

    # Verdict
    print()
    print("=" * 70)
    print(f"  VERDICT: {v['overall']} — {v['summary']}")
    print("=" * 70)
    if v["bullish_factors"]:
        print(f"    Bullish:  {', '.join(v['bullish_factors'])}")
    if v["bearish_factors"]:
        print(f"    Bearish:  {', '.join(v['bearish_factors'])}")
    if v["caution_factors"]:
        print(f"    Caution:  {', '.join(v['caution_factors'])}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Research digest for any stock or crypto")
    parser.add_argument("--ticker", required=True, help="Ticker symbol (e.g. NVDA, BTC-USD, AAPL)")
    parser.add_argument("--period", default="6mo", help="Price history period (default: 6mo)")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    symbol = args.ticker.strip().upper()
    # Normalize crypto: BTC/USD -> BTC-USD
    yf_symbol = symbol.replace("/", "-")

    log(f"Starting research digest for {symbol}")
    log(f"Time: {datetime.now().isoformat()}")

    # Collect all data
    technicals = fetch_price_and_technicals(yf_symbol, args.period)
    if "error" in technicals:
        print(json.dumps(technicals), file=sys.stderr)
        sys.exit(1)

    fundamentals = fetch_fundamentals(yf_symbol)
    analyst = fetch_analyst(yf_symbol)
    news = fetch_news(yf_symbol)
    sentiment = compute_sentiment(news.get("headlines", []), yf_symbol)
    macro = fetch_macro_snapshot()
    calendar = fetch_calendar(yf_symbol)
    verdict = generate_verdict(technicals, analyst, sentiment, macro, calendar)

    result = {
        "ticker": symbol,
        "generated_at": datetime.now().isoformat(),
        "technicals": technicals,
        "fundamentals": fundamentals,
        "analyst": analyst,
        "news": news,
        "sentiment": sentiment,
        "macro": macro,
        "calendar": calendar,
        "verdict": verdict,
    }

    # Save JSON
    output_path = args.output or f"/tmp/research_{symbol.replace('/', '_')}.json"
    with open(output_path, "w") as f_out:
        json.dump(result, f_out, indent=2, default=str)
    log(f"JSON saved to {output_path}")

    # Print human-readable report
    print_report(symbol, result)


if __name__ == "__main__":
    main()
