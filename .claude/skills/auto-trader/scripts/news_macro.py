#!/usr/bin/env python3
"""
news_macro.py — News, macro, analyst & sentiment intelligence.

Usage:
    python news_macro.py --mode news --tickers "AAPL,NVDA"
    python news_macro.py --mode analyst --tickers "AAPL,NVDA"
    python news_macro.py --mode macro
    python news_macro.py --mode calendar --tickers "AAPL"
    python news_macro.py --mode sentiment --tickers "AAPL,NVDA"
    python news_macro.py --mode all --tickers "AAPL,NVDA"

Modes:
    news        — Aggregate news headlines (Alpaca primary, yfinance fallback).
    analyst     — Analyst consensus: price targets, ratings, recent changes.
    macro       — Macro context via ETF proxies + FRED data.
    calendar    — Upcoming earnings + hard-coded 2026 economic events.
    sentiment   — Keyword-based headline sentiment scoring.
    all         — Run all modes, merge results.

Outputs JSON to stdout and saves to /tmp/news_macro.json.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSLA"]
OUTPUT_PATH = "/tmp/news_macro.json"

BULLISH_WORDS = [
    "upgrade", "upgrades", "upgraded", "beat", "beats", "surge", "surges",
    "surging", "rally", "rallies", "rallying", "buy", "record", "growth",
    "outperform", "outperforms", "bullish", "soar", "soars", "soaring",
    "breakout", "boost", "boosts", "boosted", "gain", "gains", "strong",
    "positive", "upbeat", "optimistic", "revenue beat", "earnings beat",
    "all-time high", "raises guidance", "raised guidance", "accelerate",
    "momentum", "overweight", "top pick", "best", "exceeds", "exceeded",
]

BEARISH_WORDS = [
    "downgrade", "downgrades", "downgraded", "miss", "misses", "missed",
    "cut", "cuts", "crash", "crashes", "recession", "layoff", "layoffs",
    "sell", "plunge", "plunges", "plunging", "bearish", "decline", "declines",
    "declining", "drop", "drops", "slump", "slumps", "weak", "weakness",
    "negative", "warning", "warns", "risk", "loss", "losses", "underperform",
    "underperforms", "underweight", "lowers guidance", "lowered guidance",
    "decelerate", "disappointing", "worst", "falls", "falling", "tumble",
]

# 2026 FOMC meeting dates (2-day meetings, end date listed)
# TODO: Update for 2027 — Fed publishes next year's schedule each December
FOMC_2026 = [
    "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]

# 2026 CPI release dates (Bureau of Labor Statistics, typically mid-month)
# TODO: Update for 2027
CPI_2026 = [
    "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-14",
    "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12",
    "2026-09-15", "2026-10-13", "2026-11-12", "2026-12-09",
]

# 2026 Jobs reports (typically first Friday of each month)
# TODO: Update for 2027
JOBS_2026 = [
    "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
    "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07",
    "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    """Print progress to stderr."""
    print(f"[news_macro] {msg}", file=sys.stderr)


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


def load_credentials():
    """Load credentials from env vars or config file."""
    creds = {}
    # Alpaca
    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not (api_key and secret_key):
        config_path = os.path.expanduser("~/.config/traderz/credentials.json")
        if os.path.exists(config_path):
            with open(config_path) as f:
                stored = json.load(f)
            api_key = api_key or stored.get("ALPACA_API_KEY")
            secret_key = secret_key or stored.get("ALPACA_SECRET_KEY")
    creds["ALPACA_API_KEY"] = api_key
    creds["ALPACA_SECRET_KEY"] = secret_key

    # FRED
    fred_key = os.environ.get("FRED_API_KEY")
    if not fred_key:
        config_path = os.path.expanduser("~/.config/traderz/credentials.json")
        if os.path.exists(config_path):
            with open(config_path) as f:
                stored = json.load(f)
            fred_key = stored.get("FRED_API_KEY")
    creds["FRED_API_KEY"] = fred_key

    return creds


# ---------------------------------------------------------------------------
# Mode: news
# ---------------------------------------------------------------------------

def mode_news(tickers: list[str]) -> dict:
    """Aggregate news headlines. Alpaca primary, yfinance fallback."""
    log("Fetching news headlines...")
    all_headlines = []
    source = "unknown"

    # Try Alpaca News API first
    creds = load_credentials()
    if creds.get("ALPACA_API_KEY") and creds.get("ALPACA_SECRET_KEY"):
        try:
            from alpaca.data import NewsClient
            from alpaca.data.requests import NewsRequest

            client = NewsClient(
                api_key=creds["ALPACA_API_KEY"],
                secret_key=creds["ALPACA_SECRET_KEY"],
            )
            request = NewsRequest(symbols=",".join(tickers), limit=50)
            news_set = client.get_news(request)
            news_items = news_set.data.get("news", []) if news_set.data else []

            seen = set()
            for item in news_items:
                title = item.headline
                if title in seen:
                    continue
                seen.add(title)
                all_headlines.append({
                    "title": title,
                    "summary": item.summary[:300] if item.summary else None,
                    "source": item.source if hasattr(item, "source") else None,
                    "published": str(item.created_at) if item.created_at else None,
                    "symbols": [s for s in (item.symbols or [])],
                    "url": item.url if hasattr(item, "url") else None,
                })

            source = "alpaca"
            log(f"  Alpaca News API: {len(all_headlines)} headlines")
        except Exception as e:
            log(f"  Alpaca News API failed: {e}. Falling back to yfinance.")
            all_headlines = []

    # Fallback: yfinance
    if not all_headlines:
        seen = set()
        for sym in tickers:
            try:
                tk = yf.Ticker(sym)
                news_items = tk.news or []
                for item in news_items[:10]:
                    title = item.get("title", "")
                    if title in seen:
                        continue
                    seen.add(title)
                    published = item.get("providerPublishTime")
                    if published and isinstance(published, (int, float)):
                        published = datetime.fromtimestamp(published).isoformat()
                    all_headlines.append({
                        "title": title,
                        "summary": None,
                        "source": item.get("publisher"),
                        "published": str(published) if published else None,
                        "symbols": [sym],
                        "url": item.get("link"),
                    })
            except Exception as e:
                log(f"  {sym}: yfinance news error — {e}")

        source = "yfinance"
        log(f"  yfinance: {len(all_headlines)} headlines")

    # Sort by recency, take top 30
    all_headlines.sort(
        key=lambda h: h.get("published") or "0000",
        reverse=True,
    )
    all_headlines = all_headlines[:30]

    return {
        "news": {
            "source": source,
            "count": len(all_headlines),
            "headlines": all_headlines,
        }
    }


# ---------------------------------------------------------------------------
# Mode: analyst
# ---------------------------------------------------------------------------

def mode_analyst(tickers: list[str]) -> dict:
    """Analyst consensus: price targets, ratings, recent changes."""
    log("Fetching analyst data...")
    results = []

    for sym in tickers:
        try:
            tk = yf.Ticker(sym)
            info = tk.info
            current_price = info.get("currentPrice") or info.get("regularMarketPrice")

            # Price targets
            targets = {}
            try:
                apt = tk.analyst_price_targets
                if apt is not None and isinstance(apt, dict):
                    targets = {
                        "current": apt.get("current"),
                        "mean": apt.get("mean"),
                        "high": apt.get("high"),
                        "low": apt.get("low"),
                        "number_of_analysts": apt.get("numberOfAnalysts"),
                    }
            except Exception:
                pass

            # Recommendations summary
            rec_summary = {}
            try:
                rs = tk.recommendations_summary
                if rs is not None and isinstance(rs, pd.DataFrame) and not rs.empty:
                    latest = rs.iloc[0].to_dict()
                    rec_summary = {
                        "strongBuy": int(latest.get("strongBuy", 0)),
                        "buy": int(latest.get("buy", 0)),
                        "hold": int(latest.get("hold", 0)),
                        "sell": int(latest.get("sell", 0)),
                        "strongSell": int(latest.get("strongSell", 0)),
                    }
            except Exception:
                pass

            # Recent rating changes
            recent_changes = []
            try:
                recs = tk.recommendations
                if recs is not None and isinstance(recs, pd.DataFrame) and not recs.empty:
                    for _, row in recs.tail(5).iterrows():
                        recent_changes.append({
                            "firm": row.get("Firm", ""),
                            "grade": row.get("To Grade", ""),
                            "from_grade": row.get("From Grade", ""),
                            "action": row.get("Action", ""),
                        })
                    recent_changes.reverse()  # most recent first
            except Exception:
                pass

            # Compute derived metrics
            upside_pct = None
            if targets.get("mean") and current_price and current_price > 0:
                upside_pct = safe_round(
                    (targets["mean"] - current_price) / current_price * 100, 1
                )

            consensus_score = None
            if rec_summary:
                total = sum(rec_summary.values())
                if total > 0:
                    weighted = (
                        rec_summary.get("strongBuy", 0) * 5
                        + rec_summary.get("buy", 0) * 4
                        + rec_summary.get("hold", 0) * 3
                        + rec_summary.get("sell", 0) * 2
                        + rec_summary.get("strongSell", 0) * 1
                    )
                    consensus_score = safe_round(weighted / total, 2)

            results.append({
                "ticker": sym,
                "current_price": safe_round(current_price, 2),
                "price_targets": targets,
                "recommendations_summary": rec_summary,
                "recent_changes": recent_changes,
                "upside_pct": upside_pct,
                "consensus_score": consensus_score,
            })
            log(f"  {sym}: upside={upside_pct}%, consensus={consensus_score}")

        except Exception as e:
            log(f"  {sym}: error — {e}")
            results.append({
                "ticker": sym,
                "error": str(e),
            })

    # Rank by upside descending
    results.sort(key=lambda r: r.get("upside_pct") or -9999, reverse=True)

    return {"analyst": results}


# ---------------------------------------------------------------------------
# Mode: macro
# ---------------------------------------------------------------------------

def mode_macro() -> dict:
    """Macro context via ETF proxies + optional FRED data."""
    log("Fetching macro ETF data...")

    etfs = ["^VIX", "TLT", "SHY", "UUP", "HYG", "LQD", "RSP", "SPY", "GLD", "USO"]
    try:
        data = yf.download(etfs, period="1mo", interval="1d",
                           group_by="ticker", progress=False)
    except Exception as e:
        log(f"  Error downloading macro ETF data: {e}")
        return {"macro": {"error": str(e)}}

    def get_close(sym):
        try:
            if len(etfs) == 1:
                return data["Close"].dropna()
            return data[sym]["Close"].dropna()
        except Exception:
            return pd.Series(dtype=float)

    signals = {}

    # --- VIX ---
    vix = get_close("^VIX")
    if len(vix) >= 2:
        vix_current = safe_round(vix.iloc[-1], 2)
        vix_5d_change = safe_round(pct_change_over(vix, 5), 2) if len(vix) >= 6 else None
        if vix_current is not None:
            if vix_current < 15:
                vix_regime = "low (complacent)"
            elif vix_current < 20:
                vix_regime = "normal"
            elif vix_current < 30:
                vix_regime = "elevated"
            else:
                vix_regime = "extreme (fear)"
        else:
            vix_regime = "unknown"
        signals["vix"] = {
            "level": vix_current,
            "5d_change_pct": vix_5d_change,
            "regime": vix_regime,
        }

    # --- Yields (TLT vs SHY) ---
    tlt = get_close("TLT")
    shy = get_close("SHY")
    if len(tlt) >= 6 and len(shy) >= 6:
        tlt_5d = safe_round(pct_change_over(tlt, 5), 2)
        shy_5d = safe_round(pct_change_over(shy, 5), 2)
        if tlt_5d is not None:
            yield_signal = "falling (risk-on)" if tlt_5d > 0 else "rising (risk-off)"
        else:
            yield_signal = "unknown"
        signals["yields"] = {
            "TLT_5d_pct": tlt_5d,
            "SHY_5d_pct": shy_5d,
            "long_rate_direction": yield_signal,
        }

    # --- Dollar (UUP) ---
    uup = get_close("UUP")
    if len(uup) >= 6:
        uup_5d = safe_round(pct_change_over(uup, 5), 2)
        if uup_5d is not None:
            dollar_signal = "strengthening (headwind)" if uup_5d > 0.3 else (
                "weakening (tailwind)" if uup_5d < -0.3 else "stable"
            )
        else:
            dollar_signal = "unknown"
        signals["dollar"] = {
            "UUP_5d_pct": uup_5d,
            "signal": dollar_signal,
        }

    # --- Credit (HYG vs LQD) ---
    hyg = get_close("HYG")
    lqd = get_close("LQD")
    if len(hyg) >= 6 and len(lqd) >= 6:
        hyg_5d = safe_round(pct_change_over(hyg, 5), 2)
        lqd_5d = safe_round(pct_change_over(lqd, 5), 2)
        spread_change = None
        credit_signal = "unknown"
        if hyg_5d is not None and lqd_5d is not None:
            spread_change = safe_round(hyg_5d - lqd_5d, 2)
            if spread_change < -0.5:
                credit_signal = "stress (HYG underperforming — risk-off)"
            elif spread_change > 0.5:
                credit_signal = "healthy (HYG outperforming — risk-on)"
            else:
                credit_signal = "neutral"
        signals["credit"] = {
            "HYG_5d_pct": hyg_5d,
            "LQD_5d_pct": lqd_5d,
            "spread_change": spread_change,
            "signal": credit_signal,
        }

    # --- Breadth (RSP vs SPY) ---
    rsp = get_close("RSP")
    spy = get_close("SPY")
    if len(rsp) >= 6 and len(spy) >= 6:
        rsp_5d = safe_round(pct_change_over(rsp, 5), 2)
        spy_5d = safe_round(pct_change_over(spy, 5), 2)
        breadth_diff = None
        breadth_signal = "unknown"
        if rsp_5d is not None and spy_5d is not None:
            breadth_diff = safe_round(rsp_5d - spy_5d, 2)
            if breadth_diff > 0.5:
                breadth_signal = "broad participation (healthy)"
            elif breadth_diff < -0.5:
                breadth_signal = "narrow leadership (fragile)"
            else:
                breadth_signal = "balanced"
        signals["breadth"] = {
            "RSP_5d_pct": rsp_5d,
            "SPY_5d_pct": spy_5d,
            "diff": breadth_diff,
            "signal": breadth_signal,
        }

    # --- Commodities (GLD, USO) ---
    gld = get_close("GLD")
    uso = get_close("USO")
    if len(gld) >= 6:
        gld_5d = safe_round(pct_change_over(gld, 5), 2)
        uso_5d = safe_round(pct_change_over(uso, 5), 2) if len(uso) >= 6 else None
        commodity_signal = "neutral"
        if gld_5d is not None and gld_5d > 1.0:
            commodity_signal = "gold rallying (risk-off / inflation hedge)"
        elif uso_5d is not None and uso_5d > 3.0:
            commodity_signal = "oil surging (inflation risk)"
        signals["commodities"] = {
            "GLD_5d_pct": gld_5d,
            "USO_5d_pct": uso_5d,
            "signal": commodity_signal,
        }

    # --- FRED deep macro data (optional) ---
    fred_data = {}
    creds = load_credentials()
    if creds.get("FRED_API_KEY"):
        try:
            from fredapi import Fred
            fred = Fred(api_key=creds["FRED_API_KEY"])

            series_map = {
                "fed_funds_rate": "FEDFUNDS",
                "cpi_yoy": "CPIAUCSL",
                "unemployment": "UNRATE",
                "treasury_10y": "DGS10",
                "treasury_2y": "DGS2",
            }

            for name, series_id in series_map.items():
                try:
                    s = fred.get_series(series_id, observation_start="2025-01-01")
                    s = s.dropna()
                    if len(s) > 0:
                        fred_data[name] = {
                            "latest": safe_round(s.iloc[-1], 3),
                            "date": str(s.index[-1].date()),
                        }
                except Exception as e:
                    log(f"  FRED {series_id}: {e}")

            # Yield curve: 10Y - 2Y spread
            if "treasury_10y" in fred_data and "treasury_2y" in fred_data:
                t10 = fred_data["treasury_10y"]["latest"]
                t2 = fred_data["treasury_2y"]["latest"]
                if t10 is not None and t2 is not None:
                    spread = safe_round(t10 - t2, 3)
                    fred_data["yield_curve_spread"] = {
                        "value": spread,
                        "signal": "inverted (recession warning)" if spread < 0 else "normal",
                    }

            log(f"  FRED data: {len(fred_data)} series loaded")
        except ImportError:
            log("  fredapi not installed — skipping FRED data")
        except Exception as e:
            log(f"  FRED error: {e}")
    else:
        log("  No FRED_API_KEY — skipping deep macro data")

    # --- Regime summary ---
    summary_parts = []
    if "vix" in signals:
        summary_parts.append(f"VIX {signals['vix']['level']} ({signals['vix']['regime']})")
    if "yields" in signals:
        summary_parts.append(f"Long rates {signals['yields']['long_rate_direction']}")
    if "dollar" in signals:
        summary_parts.append(f"Dollar {signals['dollar']['signal']}")
    if "credit" in signals:
        summary_parts.append(f"Credit {signals['credit']['signal']}")
    if "breadth" in signals:
        summary_parts.append(f"Breadth {signals['breadth']['signal']}")
    if "commodities" in signals:
        summary_parts.append(f"Commodities {signals['commodities']['signal']}")
    if fred_data.get("yield_curve_spread"):
        summary_parts.append(f"Yield curve {fred_data['yield_curve_spread']['signal']}")

    return {
        "macro": {
            "signals": signals,
            "fred": fred_data if fred_data else None,
            "regime_summary": " | ".join(summary_parts),
        }
    }


# ---------------------------------------------------------------------------
# Mode: calendar
# ---------------------------------------------------------------------------

def mode_calendar(tickers: list[str]) -> dict:
    """Upcoming earnings + hard-coded 2026 economic events."""
    log("Building economic calendar...")
    today = datetime.now().date()
    horizon = today + timedelta(days=14)  # 2-week lookahead

    events = []

    # --- Earnings (reuse yfinance calendar logic) ---
    for sym in tickers:
        try:
            tk = yf.Ticker(sym)
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
                    if raw is not None:
                        if isinstance(raw, list) and len(raw) > 0:
                            raw = raw[0]
                        if hasattr(raw, "date"):
                            earnings_date = raw.date()
                        elif isinstance(raw, str):
                            earnings_date = datetime.strptime(raw, "%Y-%m-%d").date()

            if earnings_date and today <= earnings_date <= horizon:
                days_until = (earnings_date - today).days
                events.append({
                    "type": "earnings",
                    "ticker": sym,
                    "date": str(earnings_date),
                    "days_until": days_until,
                    "warning": f"{sym} earnings in {days_until} days — binary event risk (财报博弈风险大)",
                })
        except Exception as e:
            log(f"  {sym} earnings calendar: {e}")

    # --- FOMC meetings ---
    for date_str in FOMC_2026:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        if today <= d <= horizon:
            days_until = (d - today).days
            events.append({
                "type": "fomc",
                "date": date_str,
                "days_until": days_until,
                "warning": f"FOMC decision in {days_until} days — expect elevated volatility",
            })

    # --- CPI releases ---
    for date_str in CPI_2026:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        if today <= d <= horizon:
            days_until = (d - today).days
            events.append({
                "type": "cpi",
                "date": date_str,
                "days_until": days_until,
                "warning": f"CPI release in {days_until} days — inflation data may move markets",
            })

    # --- Jobs reports ---
    for date_str in JOBS_2026:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        if today <= d <= horizon:
            days_until = (d - today).days
            events.append({
                "type": "jobs",
                "date": date_str,
                "days_until": days_until,
                "warning": f"Jobs report in {days_until} days — labor data impacts Fed expectations",
            })

    # Sort by date
    events.sort(key=lambda e: e["days_until"])

    # Generate high-level warnings
    warnings = [e["warning"] for e in events if e["days_until"] <= 3]

    log(f"  {len(events)} upcoming events in next 14 days")
    if warnings:
        for w in warnings:
            log(f"  ⚠ {w}")

    return {
        "calendar": {
            "lookahead_days": 14,
            "events": events,
            "imminent_warnings": warnings,
        }
    }


# ---------------------------------------------------------------------------
# Mode: sentiment
# ---------------------------------------------------------------------------

def _score_headline(title: str) -> tuple[int, int]:
    """Count bullish and bearish word hits in a headline."""
    title_lower = title.lower()
    bullish = sum(1 for w in BULLISH_WORDS if w in title_lower)
    bearish = sum(1 for w in BEARISH_WORDS if w in title_lower)
    return bullish, bearish


def mode_sentiment(tickers: list[str], headlines: list[dict] | None = None) -> dict:
    """Keyword-based headline sentiment scoring."""
    log("Computing headline sentiment...")

    # If no headlines passed, fetch them
    if headlines is None:
        news_result = mode_news(tickers)
        headlines = news_result.get("news", {}).get("headlines", [])

    # Per-ticker sentiment
    ticker_headlines = {sym: [] for sym in tickers}
    for h in headlines:
        title = h.get("title", "")
        syms = h.get("symbols") or []
        # Match headlines to tickers
        for sym in tickers:
            if sym in syms or sym.lower() in title.lower():
                ticker_headlines[sym].append(title)

    ticker_sentiment = []
    total_bullish = 0
    total_bearish = 0

    for sym in tickers:
        sym_bullish = 0
        sym_bearish = 0
        for title in ticker_headlines[sym]:
            b, br = _score_headline(title)
            sym_bullish += b
            sym_bearish += br

        total_bullish += sym_bullish
        total_bearish += sym_bearish

        total = sym_bullish + sym_bearish
        if total > 0:
            ratio = safe_round(sym_bullish / total, 2)
        else:
            ratio = 0.5  # neutral when no signal

        if ratio > 0.6:
            classification = "bullish"
        elif ratio < 0.4:
            classification = "bearish"
        else:
            classification = "neutral"

        ticker_sentiment.append({
            "ticker": sym,
            "headline_count": len(ticker_headlines[sym]),
            "bullish_hits": sym_bullish,
            "bearish_hits": sym_bearish,
            "bullish_ratio": ratio,
            "classification": classification,
        })

    # Overall market sentiment
    overall_total = total_bullish + total_bearish
    if overall_total > 0:
        overall_ratio = safe_round(total_bullish / overall_total, 2)
    else:
        overall_ratio = 0.5

    if overall_ratio > 0.6:
        overall_class = "bullish"
    elif overall_ratio < 0.4:
        overall_class = "bearish"
    else:
        overall_class = "neutral"

    log(f"  Overall sentiment: {overall_class} (ratio={overall_ratio})")

    return {
        "sentiment": {
            "per_ticker": ticker_sentiment,
            "overall": {
                "bullish_hits": total_bullish,
                "bearish_hits": total_bearish,
                "bullish_ratio": overall_ratio,
                "classification": overall_class,
            },
        }
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="News, macro, analyst & sentiment intelligence."
    )
    parser.add_argument(
        "--mode",
        required=True,
        help="Comma-separated modes: news, analyst, macro, calendar, sentiment, all",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated ticker list (default: tech7).",
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

    modes = [m.strip().lower() for m in args.mode.split(",")]
    run_all = "all" in modes

    log(f"Modes: {', '.join(modes)} | Tickers: {', '.join(tickers)}")
    log(f"Run time: {datetime.now().isoformat()}")

    results = {
        "generated_at": datetime.now().isoformat(),
        "modes": modes,
        "tickers": tickers,
    }

    # For sentiment, we can reuse news headlines
    cached_headlines = None

    if run_all or "news" in modes:
        news_result = mode_news(tickers)
        results.update(news_result)
        cached_headlines = news_result.get("news", {}).get("headlines")

    if run_all or "analyst" in modes:
        results.update(mode_analyst(tickers))

    if run_all or "macro" in modes:
        results.update(mode_macro())

    if run_all or "calendar" in modes:
        results.update(mode_calendar(tickers))

    if run_all or "sentiment" in modes:
        results.update(mode_sentiment(tickers, headlines=cached_headlines))

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
