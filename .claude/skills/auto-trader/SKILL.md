---
name: auto-trader
description: >
  Automated US stock analysis and paper trading skill. Use this skill whenever
  the user wants to: analyze stocks or ETFs with technical indicators, get
  AI-driven buy/sell/hold recommendations, execute paper trades via Alpaca,
  check portfolio status, backtest a trading strategy, or build an end-to-end
  automated trading workflow. Trigger on mentions of stock tickers (AAPL, TSLA,
  SPY, etc.), trading signals, paper trading, portfolio analysis, technical
  analysis (RSI, MACD, moving averages), or any request involving stock market
  decisions. Also trigger when the user says things like "should I buy X",
  "what's happening with my portfolio", "run my strategy", or "analyze the
  market today".
---

# Auto Trader Skill

An end-to-end US stock paper trading system that combines market data retrieval,
technical analysis, AI-powered decision making, and simulated order execution
via Alpaca's Paper Trading API.

## Prerequisites

The user needs an Alpaca Paper Trading account (free). They must provide:
- `ALPACA_API_KEY` — their paper trading API key
- `ALPACA_SECRET_KEY` — their paper trading secret key

If the user hasn't set these up yet, guide them to https://alpaca.markets to
create a free account and generate paper trading API keys.

Store credentials as environment variables. NEVER hardcode them in scripts.

## Architecture Overview

The skill operates in three layers:

### 1. Data Layer (`scripts/fetch_data.py`)
- Uses `yfinance` to pull historical OHLCV data (no API key needed)
- Computes technical indicators: SMA(20/50/200), EMA(12/26), RSI(14), MACD,
  Bollinger Bands, ATR, Volume profile
- Fetches basic fundamentals (P/E, market cap, earnings dates)
- Outputs a structured JSON summary for Claude to analyze

### 2. Analysis & Decision Layer (Claude)
- Claude receives the structured data summary
- Evaluates the technical setup, trend direction, support/resistance levels
- Considers risk/reward ratio and position sizing
- Produces a clear recommendation: BUY / SELL / HOLD with confidence level
- Explains the reasoning in plain language
- Suggests entry price, stop-loss, and take-profit levels

### 3. Execution Layer (`scripts/trade.py`)
- Connects to Alpaca Paper Trading API
- Executes orders based on Claude's recommendations
- Supports: market, limit, stop, and bracket orders
- Checks account status, buying power, and existing positions
- Reports back order confirmation or rejection details

## Workflow

When the user asks to analyze or trade a stock:

1. **Install dependencies** (first run only):
   ```bash
   uv sync
   ```

2. **Fetch and analyze data**:
   ```bash
   uv run scripts/fetch_data.py --ticker AAPL --period 6mo --interval 1d
   ```
   This outputs a JSON file at `/tmp/analysis_AAPL.json` containing:
   - Recent price action (last 30 days OHLCV)
   - All computed technical indicators with current values
   - Key support/resistance levels
   - Recent volume trends
   - Basic fundamental snapshot

3. **Claude analyzes the data**:
   Read the JSON output and make a trading decision. Structure your analysis as:
   - **Trend**: What is the overall trend? (bullish / bearish / sideways)
   - **Momentum**: What do RSI, MACD say about momentum?
   - **Key levels**: Where are support and resistance?
   - **Signal**: BUY / SELL / HOLD
   - **Confidence**: High / Medium / Low
   - **Plan**: Entry, stop-loss, take-profit (if BUY or SELL)
   - **Position size**: Suggest allocation as % of portfolio (conservative: 2-5%)

4. **Execute the trade** (if user confirms):
   ```bash
   uv run scripts/trade.py --action buy --ticker AAPL --qty 10 --order-type market
   ```
   Or for a bracket order with stop-loss and take-profit:
   ```bash
   uv run scripts/trade.py --action buy --ticker AAPL --qty 10 \
     --order-type bracket --stop-loss 170.00 --take-profit 195.00
   ```

5. **Check portfolio**:
   ```bash
   uv run scripts/trade.py --action portfolio
   ```

## Important Guidelines

- **Always confirm with the user before executing any trade.** Show your
  analysis and recommendation first, then ask if they want to proceed.
- **Risk management is paramount.** Never suggest putting more than 5% of
  portfolio in a single position unless the user explicitly asks for it.
- **Paper trading only.** This skill is designed for Alpaca paper trading.
  Never attempt to connect to live trading endpoints.
- **Not financial advice.** Always remind the user that this is a simulation
  tool for learning and strategy testing, not financial advice.

## Available Commands

| User Intent | Action |
|---|---|
| "Analyze AAPL" | Fetch data + run analysis + give recommendation |
| "Buy 10 shares of TSLA" | Execute paper trade (after confirmation) |
| "Show my portfolio" | Display current positions and P&L |
| "What should I trade today?" | Scan a watchlist and find best setups |
| "Backtest SMA crossover on SPY" | Run historical backtest |
| "Set a stop loss on my AAPL position" | Modify existing order |

## Error Handling

- If Alpaca credentials are missing, prompt the user to set them up
- If yfinance returns no data, suggest checking the ticker symbol
- If an order is rejected, explain the reason (insufficient buying power,
  market closed, PDT rule, etc.)
- Always wrap API calls in try/except and give clear error messages

## Files in this skill

- `SKILL.md` — This file (instructions and workflow)
- `scripts/fetch_data.py` — Data fetching and technical analysis
- `scripts/trade.py` — Alpaca paper trading execution
- `references/indicators.md` — Reference guide for interpreting technical indicators
