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
- Fetches analyst price targets, recommendation summaries, and recent news
- Outputs a structured JSON summary for Claude to analyze

### 1b. News & Macro Layer (`scripts/news_macro.py`)
- **News**: Aggregates headlines from Alpaca News API (primary) or yfinance (fallback)
- **Analyst**: Consensus ratings, price targets, recent upgrades/downgrades
- **Macro**: ETF-proxy regime signals (VIX, yields, dollar, credit, breadth, commodities) + optional FRED deep macro data (Fed rate, CPI, unemployment, yield curve)
- **Calendar**: Hard-coded 2026 FOMC/CPI/jobs dates + yfinance earnings calendar
- **Sentiment**: Keyword-based headline sentiment scoring per ticker and overall

### 2. Analysis & Decision Layer (Claude)

Claude's job is to synthesize ALL data into a trade decision. This is a
structured multi-step reasoning process, not a glance at numbers.

#### Signal Trust Hierarchy (信号信任层级)

**Numbers don't lie. News can be 烟雾弹 (smoke screens).**

Trust level (highest to lowest):
1. **Price action & volume** — what the market is ACTUALLY doing (最可靠)
2. **Technical indicators** — mathematical derivatives of price (RSI, MACD, etc.)
3. **Macro regime** — VIX, yields, credit spreads (hard numbers)
4. **Analyst targets & ratings** — useful for direction, but lagging
5. **News headlines** — informative but NEVER decisive alone (可能是烟雾弹)

**Core rule**: Numbers decide. News informs and forecasts. Never override
a clear technical signal because of a headline. But use news to understand
WHY the numbers are moving and WHERE they might go next.

#### Step-by-step analysis workflow

**Step 1: Read the numbers first (先看数据)**
- Price vs SMAs (trend), RSI/Stochastic (momentum), MACD (direction change)
- Volume (conviction), ATR (volatility), support/resistance (key levels)
- Form a preliminary bias: bullish / bearish / neutral

**Step 2: Read the news with context (带着问题读新闻)**
Don't just count keywords. Actually read each headline and ask:
- What is the **theme**? (product launch, earnings, partnership, macro event)
- Is this **new information** or recycled/expected? (priced in vs surprise)
- **Who benefits and who loses?** (NVDA partnership = bullish NVDA, maybe bearish competitor)
- Is this a **one-time event** or a **trend change**? (CEO quote vs industry shift)
- Could this be a **烟雾弹**? (clickbait, opinion piece, short-seller report)

**Step 3: Cross-reference news with numbers (交叉验证)**
- Bullish news + price going UP + volume HIGH = news is real, confirmed by money
- Bullish news + price FLAT or DOWN = market doesn't believe it, be skeptical
- Bearish news + price holding UP = strong hands, potential contrarian buy
- Bearish news + price crashing + volume spike = news is real, stay away

**Step 4: Check macro & calendar (宏观环境检查)**
- Is the macro regime supportive or hostile?
- Any events in next 2-3 days that could override everything?
- Macro is a **filter**, not a signal — it tells you when NOT to trade

**Step 5: Form final decision (最终决策)**
- The decision must be justified by NUMBERS first
- News adds color and conviction — upgrade from HOLD to BUY, or add caution
- If numbers and news conflict, TRUST THE NUMBERS
- If numbers are neutral and news is strong, WAIT for numbers to confirm

#### News reasoning examples

Good reasoning:
> "NVDA headlines are all about GTC partnerships (Uber, Lyft, Hyundai, Adobe).
> This is a THEME — autonomous driving + AI infrastructure expanding to new
> verticals. The numbers confirm: volume 1.11x avg, MACD crossing bullish.
> But price is still below SMA50 and FOMC is in 2 days. The news tells me
> WHERE the next move goes (up), the numbers tell me WHEN to enter (not yet)."

Bad reasoning:
> "Headlines say surge so I should buy." ← 烟雾弹 trap

#### Quick reference: News & Macro signals

| Signal | How to use |
|--------|-----------|
| Analyst >70% buy + >15% upside | Directional bias (not entry trigger) |
| Bullish news + bullish technicals | High-conviction entry |
| Bullish news + bearish technicals | Wait for numbers to confirm |
| Bearish news + oversold technicals | Potential contrarian buy |
| Bearish news + bearish technicals | Stay away |
| VIX > 30 | Reduce position sizes |
| FOMC within 2 days | Avoid new entries |
| Earnings within 5 days | Don't enter (binary event risk) |
| Credit stress (HYG << LQD) | Favor quality over speculation |
| Narrow breadth (SPY >> RSP) | Market is fragile, be cautious |

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
   uv sync  # run from project root
   ```

2. **Fetch and analyze data**:
   ```bash
   uv run .claude/skills/auto-trader/scripts/fetch_data.py --ticker AAPL --period 6mo --interval 1d
   ```
   This outputs a JSON file at `/tmp/analysis_AAPL.json` containing:
   - Recent price action (last 30 days OHLCV)
   - All computed technical indicators with current values
   - Key support/resistance levels
   - Recent volume trends
   - Basic fundamental snapshot
   - Analyst price targets, recommendation summary, recent headlines

2b. **Fetch news, macro & sentiment context**:
   ```bash
   uv run .claude/skills/auto-trader/scripts/news_macro.py --mode all --tickers "AAPL,NVDA"
   ```
   This outputs `/tmp/news_macro.json` containing:
   - News headlines with source and timestamps
   - Analyst consensus (targets, ratings, recent changes)
   - Macro regime (VIX, yields, credit, breadth, dollar, commodities)
   - Economic calendar (FOMC, CPI, jobs, earnings)
   - Headline sentiment per ticker

3. **Claude analyzes the data** (follow the 5-step workflow above):

   **A. Numbers first (技术面)**:
   - **Trend**: Overall direction from SMAs, price action
   - **Momentum**: RSI, MACD, Stochastic — accelerating or fading?
   - **Key levels**: Support, resistance, Bollinger Bands
   - **Volume**: Confirming the move or diverging?
   - → Form preliminary bias

   **B. Read the news (基本面 + 新闻)**:
   - Actually read the top 10 headlines — identify themes, not just keywords
   - Flag: catalysts, partnerships, earnings surprises, analyst changes
   - Ask: is this new info or priced in? Real signal or 烟雾弹?
   - → Adjust conviction (but don't flip the bias unless overwhelming)

   **C. Cross-reference (交叉验证)**:
   - Does the news EXPLAIN why the numbers look the way they do?
   - If news is bullish but price is down — market disagrees, be cautious
   - If news is bearish but price holds — strong hands, potential opportunity

   **D. Macro & calendar filter (宏观过滤)**:
   - Check VIX, yields, credit, breadth
   - Any FOMC/CPI/earnings in next 3 days? → filter out new entries

   **E. Final decision (最终判断)**:
   - **Signal**: BUY / SELL / HOLD — must be justified by numbers
   - **Confidence**: High / Medium / Low
   - **News impact**: How news changes conviction (e.g. "news adds +1 conviction")
   - **Plan**: Entry, stop-loss, take-profit (if BUY or SELL)
   - **Position size**: % of portfolio (conservative: 2-5%)

4. **Execute the trade** (if user confirms):
   ```bash
   uv run .claude/skills/auto-trader/scripts/trade.py --action buy --ticker AAPL --qty 10 --order-type market
   ```
   Or for a bracket order with stop-loss and take-profit:
   ```bash
   uv run .claude/skills/auto-trader/scripts/trade.py --action buy --ticker AAPL --qty 10 \
     --order-type bracket --stop-loss 170.00 --take-profit 195.00
   ```

5. **Check portfolio**:
   ```bash
   uv run .claude/skills/auto-trader/scripts/trade.py --action portfolio
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
- `scripts/fetch_data.py` — Data fetching, technical analysis, and analyst/news data
- `scripts/news_macro.py` — News, macro, analyst, calendar & sentiment intelligence
- `scripts/trade.py` — Alpaca paper trading execution
- `scripts/market_intel.py` — Market intelligence scanner (sectors, earnings, movers)
- `scripts/screener.py` — Trading opportunity screener
- `scripts/discover.py` — Stock discovery engine
- `references/indicators.md` — Reference guide for interpreting technical indicators
