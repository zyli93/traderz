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

## MANDATORY: Always Start With Portfolio Snapshot

**Every time this skill is invoked**, before doing ANY analysis or trading,
immediately run:

```bash
uv run .claude/skills/auto-trader/scripts/trade.py --action portfolio
```

Present a brief, compact snapshot to the user at the top of your response:

```
📊 Portfolio: $100,375 | Cash: $81,340 (81%)
AMD 36 @ $200.58 → $204.37 (+$136, +1.9%)
AMZN 17 @ $209.48 → $209.00 (-$8, -0.2%)
MU 8 @ $430.10 → $447.37 (+$138, +4.0%)
QCOM 20 @ $129.74 → $131.41 (+$33, +1.3%)
BTC 0.027 @ $71,316 → $69,893 (-$39, -2.0%)
```

This gives the user immediate context before any analysis begins.

## MANDATORY: Bookkeeping After Every Session

After every trading session (analysis, trades, or portfolio check), record
everything in the SQLite database. This is NOT optional — it ensures continuity
across conversations.

**After placing trades:**
```bash
uv run .claude/skills/auto-trader/scripts/db.py --action record-trade \
  --ticker TICKER --side buy/sell --qty N --price P \
  --stop-loss SL --take-profit TP --order-type TYPE \
  --strategy "reason for trade"
```

**After closing/exiting trades:**
```bash
uv run .claude/skills/auto-trader/scripts/db.py --action close-trade \
  --ticker TICKER --exit-price P
```

**Always at the end of every session:**
```bash
# Snapshot portfolio
uv run .claude/skills/auto-trader/scripts/db.py --action snapshot

# Log the session
uv run .claude/skills/auto-trader/scripts/db.py --action record-session \
  --regime "macro summary" --summary "what was done"

# Log any lessons learned (if applicable)
uv run .claude/skills/auto-trader/scripts/db.py --action add-lesson \
  --text "lesson text"
```

**After reading news with clear directional calls:**
```bash
# Record a media/analyst call for later verification
uv run .claude/skills/auto-trader/scripts/db.py --action record-media-call \
  --source "benzinga" --ticker MU --call bear \
  --headline "Is This A Bull Trap For Micron?" \
  --price-at-call 422.0 [--author "Author Name"] [--date 2026-03-20]

# Later, verify if the call was correct
uv run .claude/skills/auto-trader/scripts/db.py --action verify-media-call \
  --call-id 1 --price-at-verify 393.43 --correct yes

# Check accuracy stats per source
uv run .claude/skills/auto-trader/scripts/db.py --action show-media-stats
uv run .claude/skills/auto-trader/scripts/db.py --action show-media-calls [--source benzinga] [--ticker MU]
```

**After scanning for opportunities, save watchlist items:**
```bash
# Add a ticker to the watchlist with full context
uv run .claude/skills/auto-trader/scripts/db.py --action add-watchlist \
  --ticker MRVL --setup-type "Minervini trend" \
  --entry-trigger "Pullback to $93-95" \
  --entry-price-target 94.0 --stop-loss 85.0 --take-profit 120.0 \
  --position-size-pct 3.0 --analyst-upside-pct 22.0 \
  --thesis "Why we like it" --last-price 98.45

# Update a watchlist entry (e.g. new trigger, price update)
uv run .claude/skills/auto-trader/scripts/db.py --action update-watchlist \
  --ticker MRVL --last-price 94.0 --notes "Pulled back to target zone"

# Mark as ready (trigger conditions met)
uv run .claude/skills/auto-trader/scripts/db.py --action update-watchlist \
  --ticker MRVL --status ready

# Remove from watchlist (thesis invalidated)
uv run .claude/skills/auto-trader/scripts/db.py --action remove-watchlist --ticker MRVL

# View active watchlist
uv run .claude/skills/auto-trader/scripts/db.py --action show-watchlist
uv run .claude/skills/auto-trader/scripts/db.py --action show-watchlist --status ready
```

**To review history at session start:**
```bash
uv run .claude/skills/auto-trader/scripts/db.py --action show-trades --status open
uv run .claude/skills/auto-trader/scripts/db.py --action show-pnl
uv run .claude/skills/auto-trader/scripts/db.py --action show-sessions --limit 3
uv run .claude/skills/auto-trader/scripts/db.py --action show-watchlist
```

## MANDATORY: Read Strategy Before Every Session

**Before doing ANYTHING**, read the master strategy file:
```bash
# This file contains ALL trading rules: entry/exit, position sizing, risk management, session flow
cat ~/.claude/projects/-Users-zeyuli-projects-traderz/memory/strategy_master.md
```
Follow the session flow defined there (Phases 1-6). The workflow below is a quick reference.

## Workflow: Full Trading Session

When the user says "run trading session", "今天如何", or similar:

### Phase 1: Snapshot
```bash
uv run .claude/skills/auto-trader/scripts/trade.py --action portfolio
uv run .claude/skills/auto-trader/scripts/db.py --action show-sessions --limit 3
```

### Phase 2+3: Full Market Scan + Position Data — ONE COMMAND
```bash
uv run .claude/skills/auto-trader/scripts/run_session.py
```
This automatically:
- Reads open positions + watchlist from db.py
- Runs screener (tech50 + 44 multi-sector stocks) in parallel
- Runs discover (700+ universe) in parallel
- Runs market_intel (sectors, movers, correlations) in parallel
- Fetches technical data for all position + watchlist tickers in parallel
- Fetches news/macro for all relevant tickers
- Outputs everything to `/tmp/session_scan.json`

**Quick mode** (skip discover, faster): `run_session.py --quick`
**Scan only** (no position data): `run_session.py --phase scan`
**Positions only** (no full scan): `run_session.py --phase positions`

After it completes, read `/tmp/session_scan.json` and analyze. The JSON has these sections:
- `positions` / `watchlist` — what we hold and watch
- `screener.tech50` / `screener.multi_sector` — oversold bounce, breakout, squeeze, RS, gap up
- `discover` — gainers, trending up, new highs, momentum leaders
- `market_intel` — sector rankings, movers, correlations
- `fetch_data` — per-ticker technical indicators for all positions + watchlist
- `news_macro` — headlines, macro regime, calendar, sentiment
- `errors` — any scripts that failed (session continues despite errors)

### Phase 4: Analyze
Using the consolidated data from session_scan.json:
1. Check existing positions (stops, exit conditions, trailing stops)
2. Review screener/discover hits for new opportunities
3. Apply 5-step analysis workflow (numbers → news → cross-ref → macro filter → decision)
4. Cross-check diversification across sectors

### Phase 5: Execute
- **Confirmation rule**: Single trade > $3,000 OR daily total new buys > $5,000 → ask user first. Otherwise execute directly.
- Place stop-loss orders immediately after entry
- Record everything in db.py

### Phase 6: Stop Hunting Scan (brief)
Quick check on held positions + watchlist for stop hunting signals (long wicks, volume spikes at support, V-reversals). Report only if found.

### Phase 7: Bookkeeping
```bash
uv run .claude/skills/auto-trader/scripts/db.py --action snapshot
uv run .claude/skills/auto-trader/scripts/db.py --action record-session --regime "..." --summary "..."
```

### Phase 8: Telegram 报告（必做）
Session 结束后，发送完整中文报告到 Telegram。分 4 封信：
1. **总览 + 今日操作**: 账户、P&L、每笔交易的原因
2. **持仓详情**: 每个持仓的技术状态、thesis 是否成立
3. **宏观 + 市场**: 板块排名、关键新闻、macro regime
4. **Watchlist + 反思**: watchlist 更新、错过的机会、教训

使用 `notify_telegram.py --action pages` 发送（stdin 传 JSON 数组）：
```bash
echo '["第1封内容", "第2封内容", "第3封内容", "第4封内容"]' | \
  uv run .claude/skills/auto-trader/scripts/notify_telegram.py --action pages
```
每封信标注日期和编号（如"4/8 早盘 第1封"）。中文为主，英文术语保留原文。

## Workflow: Single Stock Analysis

When the user asks to analyze a specific stock (e.g. "analyze AAPL"):

1. **Fetch data**:
   ```bash
   uv run .claude/skills/auto-trader/scripts/fetch_data.py --ticker AAPL --period 6mo --interval 1d
   uv run .claude/skills/auto-trader/scripts/news_macro.py --mode all --tickers "AAPL"
   ```

2. **Analyze** using the 5-step workflow above

3. **Execute** if recommended (follow confirmation rule in Phase 5)

## Important Guidelines

- **Confirmation rule**: Single trade > $3,000 OR daily total > $5,000 → ask user.
  Below threshold → execute directly. User learns by observing, not by approving every trade.
- **Risk management is paramount.** Never put more than 5% of portfolio in a single position.
- **Paper trading only.** Never attempt to connect to live trading endpoints.
- **Full market scan is MANDATORY** every session. Never limit analysis to existing watchlist only.

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
- `scripts/run_session.py` — **Session orchestrator**: one command to run all scans + fetch all data. Use this instead of calling individual scripts.
- `scripts/fetch_data.py` — Data fetching, technical analysis, and analyst/news data (called by run_session.py, or standalone for single ticker)
- `scripts/news_macro.py` — News, macro, analyst, calendar & sentiment intelligence (called by run_session.py, or standalone)
- `scripts/trade.py` — Alpaca paper trading execution
- `scripts/db.py` — SQLite trading database (trades, snapshots, sessions, lessons)
- `scripts/market_intel.py` — Market intelligence scanner (called by run_session.py, or standalone)
- `scripts/screener.py` — Trading opportunity screener (called by run_session.py, or standalone)
- `scripts/discover.py` — Stock discovery engine (called by run_session.py, or standalone)
- `scripts/notify_telegram.py` — Telegram notification sender (session reports, alerts)
- `references/indicators.md` — Reference guide for interpreting technical indicators
