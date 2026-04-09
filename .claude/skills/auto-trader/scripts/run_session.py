#!/usr/bin/env python3
"""
run_session.py — Orchestrate a full trading session scan.

Calls existing scripts as subprocesses, aggregates results into a single JSON.

Usage:
    uv run .claude/skills/auto-trader/scripts/run_session.py
    uv run .claude/skills/auto-trader/scripts/run_session.py --phase scan
    uv run .claude/skills/auto-trader/scripts/run_session.py --phase positions
    uv run .claude/skills/auto-trader/scripts/run_session.py --quick

Phases:
    scan       — Phase 2: screener (tech50 + multi-sector), discover, market_intel
    positions  — Phase 3: fetch_data + news_macro for open positions & watchlist
    (default)  — Run all phases
    --quick    — Skip discover, only run positions + watchlist scans
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
MULTI_SECTOR_TICKERS = (
    "XOM,CVX,OXY,SLB,LMT,RTX,GD,NOC,JPM,GS,MS,BAC,WFC,UNH,JNJ,PFE,LLY,ABT,"
    "PG,KO,PEP,COST,WMT,HD,NEE,SO,DUK,AEP,ED,O,AMT,PLD,SPG,VRTX,REGN,AMGN,"
    "GILD,MRK,ABBV,TMO,DHR,F,GM,TSLA,NKE"
)

# Crypto tickers to scan (yfinance format)
CRYPTO_TICKERS = "BTC-USD,ETH-USD,SOL-USD,AVAX-USD,LINK-USD"
OUTPUT_PATH = "/tmp/session_scan.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    """Print progress to stderr with prefix."""
    print(f"[run_session] {msg}", file=sys.stderr)


def run_script(script_name: str, args: list[str], label: str,
               timeout: int = 300) -> dict:
    """Run a script as a subprocess and return parsed JSON from stdout.

    Returns parsed JSON on success, or {"error": ..., "stderr": ...} on failure.
    """
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    cmd = [sys.executable, script_path] + args

    log(f"Starting: {label}")
    t0 = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - t0

        if result.returncode != 0:
            log(f"FAILED: {label} (exit {result.returncode}, {elapsed:.1f}s)")
            return {
                "error": f"{label} exited with code {result.returncode}",
                "stderr": result.stderr[-2000:] if result.stderr else "",
            }

        log(f"Done: {label} ({elapsed:.1f}s)")

        # Parse JSON from stdout
        stdout = result.stdout.strip()
        if not stdout:
            return {"error": f"{label} produced no stdout", "stderr": result.stderr[-2000:] if result.stderr else ""}

        try:
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            return {
                "error": f"{label} stdout is not valid JSON: {e}",
                "stdout_snippet": stdout[:500],
            }

    except subprocess.TimeoutExpired:
        log(f"TIMEOUT: {label} (>{timeout}s)")
        return {"error": f"{label} timed out after {timeout}s"}
    except Exception as e:
        log(f"ERROR: {label} — {e}")
        return {"error": f"{label} exception: {e}"}


# ---------------------------------------------------------------------------
# Step A: Get portfolio state from db.py
# ---------------------------------------------------------------------------

def get_portfolio_state() -> dict:
    """Query db.py for open trades and watchlist tickers."""
    open_trades_data = run_script(
        "db.py", ["--action", "show-trades", "--status", "open"],
        "db.py show-trades --status open",
    )
    watchlist_data = run_script(
        "db.py", ["--action", "show-watchlist"],
        "db.py show-watchlist",
    )

    # Extract ticker lists
    open_trades = []
    open_tickers = []
    if isinstance(open_trades_data, list):
        open_trades = open_trades_data
        open_tickers = list({t["ticker"] for t in open_trades if "ticker" in t})
    elif isinstance(open_trades_data, dict) and "error" not in open_trades_data:
        # Might be wrapped in some structure
        open_trades = open_trades_data
        if isinstance(open_trades_data, dict):
            for v in open_trades_data.values():
                if isinstance(v, list):
                    open_tickers = list({t.get("ticker", "") for t in v if isinstance(t, dict) and "ticker" in t})
                    break

    watchlist_entries = []
    watchlist_tickers = []
    if isinstance(watchlist_data, list):
        watchlist_entries = watchlist_data
        watchlist_tickers = list({w["ticker"] for w in watchlist_data if "ticker" in w})
    elif isinstance(watchlist_data, dict) and "error" not in watchlist_data:
        watchlist_entries = watchlist_data
        if isinstance(watchlist_data, dict):
            for v in watchlist_data.values():
                if isinstance(v, list):
                    watchlist_tickers = list({w.get("ticker", "") for w in v if isinstance(w, dict) and "ticker" in w})
                    break

    return {
        "open_trades": open_trades,
        "open_tickers": open_tickers,
        "watchlist_entries": watchlist_entries,
        "watchlist_tickers": watchlist_tickers,
        "errors": [
            d for d in [open_trades_data, watchlist_data]
            if isinstance(d, dict) and "error" in d
        ],
    }


# ---------------------------------------------------------------------------
# Step B: Phase "scan" — screener + discover + market_intel
# ---------------------------------------------------------------------------

def run_phase_scan(quick: bool = False) -> dict:
    """Run screener (SP500 + tech50 + multi-sector + crypto), discover, and market_intel in parallel."""
    results = {
        "screener": {"broad": None, "crypto": None},
        "discover": None,
        "market_intel": None,
    }
    errors = []

    futures = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        # Screener: broad universe (~300 tickers — tech50 + all major sectors)
        futures[pool.submit(
            run_script,
            "screener.py",
            ["--scan", "all", "--universe", "broad", "--top", "15"],
            "screener broad",
            300,  # 5 min timeout for large universe
        )] = "screener_broad"

        # Screener: crypto
        futures[pool.submit(
            run_script,
            "screener.py",
            ["--scan", "all", "--tickers", CRYPTO_TICKERS, "--top", "5"],
            "screener crypto",
        )] = "screener_crypto"

        # Discover (skip in quick mode)
        if not quick:
            futures[pool.submit(
                run_script,
                "discover.py",
                ["--mode", "all", "--universe", "all", "--top", "10"],
                "discover all",
                600,  # 10 min timeout for discover
            )] = "discover"

        # Market intel
        futures[pool.submit(
            run_script,
            "market_intel.py",
            ["--mode", "all"],
            "market_intel all",
        )] = "market_intel"

        for future in as_completed(futures):
            key = futures[future]
            try:
                data = future.result()
            except Exception as e:
                data = {"error": f"{key} future exception: {e}"}

            if isinstance(data, dict) and "error" in data:
                errors.append(data)

            if key == "screener_broad":
                results["screener"]["broad"] = data
            elif key == "screener_crypto":
                results["screener"]["crypto"] = data
            elif key == "discover":
                results["discover"] = data
            elif key == "market_intel":
                results["market_intel"] = data

    if quick:
        results["discover"] = {"skipped": True, "reason": "quick mode"}

    results["errors"] = errors
    return results


# ---------------------------------------------------------------------------
# Step C: Phase "positions" — fetch_data + news_macro for open tickers
# ---------------------------------------------------------------------------

def run_phase_positions(tickers: list[str]) -> dict:
    """Run fetch_data per ticker and news_macro for all tickers in parallel."""
    results = {
        "fetch_data": {},
        "news_macro": None,
    }
    errors = []

    if not tickers:
        log("No tickers for positions phase — skipping")
        results["fetch_data"] = {}
        results["news_macro"] = {"skipped": True, "reason": "no tickers"}
        return results

    tickers_csv = ",".join(tickers)

    futures = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        # fetch_data: one subprocess per ticker
        for ticker in tickers:
            output_path = f"/tmp/analysis_{ticker}.json"
            futures[pool.submit(
                run_script,
                "fetch_data.py",
                ["--ticker", ticker, "--period", "6mo", "--interval", "1d",
                 "--output", output_path],
                f"fetch_data {ticker}",
            )] = ("fetch_data", ticker)

        # news_macro: single call for all tickers
        futures[pool.submit(
            run_script,
            "news_macro.py",
            ["--mode", "all", "--tickers", tickers_csv],
            f"news_macro ({len(tickers)} tickers)",
        )] = ("news_macro", None)

        for future in as_completed(futures):
            key, ticker = futures[future]
            try:
                data = future.result()
            except Exception as e:
                data = {"error": f"{key} {ticker} future exception: {e}"}

            if isinstance(data, dict) and "error" in data:
                errors.append(data)

            if key == "fetch_data" and ticker:
                # fetch_data outputs {TICKER: {...}} — extract the ticker's data
                if isinstance(data, dict) and ticker in data:
                    results["fetch_data"][ticker] = data[ticker]
                elif isinstance(data, dict) and "error" not in data:
                    # Might have the data under a different key format
                    # (e.g. BTC/USD vs BTC-USD)
                    if len(data) == 1:
                        results["fetch_data"][ticker] = list(data.values())[0]
                    else:
                        results["fetch_data"][ticker] = data
                else:
                    results["fetch_data"][ticker] = data
            elif key == "news_macro":
                results["news_macro"] = data

    results["errors"] = errors
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Orchestrate a full trading session scan."
    )
    parser.add_argument(
        "--phase",
        choices=["scan", "positions"],
        default=None,
        help="Run only a specific phase (default: run all)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Skip full universe discover, only run positions + watchlist scans",
    )
    args = parser.parse_args()

    t0 = time.time()
    run_scan = args.phase is None or args.phase == "scan"
    run_positions = args.phase is None or args.phase == "positions"
    phases_run = []
    all_errors = []

    output = {
        "generated_at": datetime.now().isoformat(),
        "duration_seconds": None,
        "phases_run": [],
        "quick_mode": args.quick,
        "positions": {"open_trades": [], "tickers": []},
        "watchlist": {"entries": [], "tickers": []},
        "screener": None,
        "discover": None,
        "market_intel": None,
        "fetch_data": {},
        "news_macro": None,
        "errors": [],
    }

    # ── Step A: Get portfolio state ────────────────────────────────────────
    log("=== Step A: Portfolio State ===")
    portfolio = get_portfolio_state()
    output["positions"] = {
        "open_trades": portfolio["open_trades"],
        "tickers": portfolio["open_tickers"],
    }
    output["watchlist"] = {
        "entries": portfolio["watchlist_entries"],
        "tickers": portfolio["watchlist_tickers"],
    }
    all_errors.extend(portfolio.get("errors", []))

    # ── Step B: Phase "scan" ──────────────────────────────────────────────
    if run_scan:
        log("=== Step B: Scan Phase (screener + discover + market_intel) ===")
        phases_run.append("scan")
        scan_results = run_phase_scan(quick=args.quick)
        output["screener"] = scan_results["screener"]
        output["discover"] = scan_results["discover"]
        output["market_intel"] = scan_results["market_intel"]
        all_errors.extend(scan_results.get("errors", []))

    # ── Step C: Phase "positions" ─────────────────────────────────────────
    if run_positions:
        log("=== Step C: Positions Phase (fetch_data + news_macro) ===")
        phases_run.append("positions")
        # Combine open position tickers + watchlist tickers (deduplicated)
        all_tickers = list(dict.fromkeys(
            portfolio["open_tickers"] + portfolio["watchlist_tickers"]
        ))
        log(f"Tickers to analyze: {all_tickers}")
        pos_results = run_phase_positions(all_tickers)
        output["fetch_data"] = pos_results["fetch_data"]
        output["news_macro"] = pos_results["news_macro"]
        all_errors.extend(pos_results.get("errors", []))

    # ── Step D: Consolidate & output ──────────────────────────────────────
    duration = time.time() - t0
    output["phases_run"] = phases_run
    output["duration_seconds"] = round(duration, 1)
    output["errors"] = all_errors

    # Write to file
    try:
        with open(OUTPUT_PATH, "w") as f:
            json.dump(output, f, indent=2, default=str)
        log(f"Results saved to {OUTPUT_PATH}")
    except Exception as e:
        log(f"Error saving results: {e}")

    # Print JSON to stdout
    print(json.dumps(output, indent=2, default=str))

    # ── Summary to stderr ─────────────────────────────────────────────────
    log("=" * 60)
    log(f"Session complete in {duration:.1f}s")
    log(f"Phases: {', '.join(phases_run) if phases_run else 'none'}")
    log(f"Quick mode: {args.quick}")
    log(f"Open positions: {len(portfolio['open_tickers'])} tickers")
    log(f"Watchlist: {len(portfolio['watchlist_tickers'])} tickers")
    if output.get("fetch_data"):
        log(f"Fetch data: {len(output['fetch_data'])} tickers analyzed")
    if all_errors:
        log(f"Errors: {len(all_errors)}")
        for err in all_errors:
            err_msg = err.get("error", str(err)) if isinstance(err, dict) else str(err)
            log(f"  - {err_msg[:200]}")
    else:
        log("Errors: none")
    log("=" * 60)


if __name__ == "__main__":
    main()
