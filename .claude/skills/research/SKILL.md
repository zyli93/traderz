---
name: research
description: >
  Stock and crypto research digest. Use this skill when the user asks to
  research, look up, or get a summary/digest/highlights for any stock ticker
  or cryptocurrency. Trigger on phrases like "research NVDA", "tell me about
  AAPL", "what's going on with BTC", "digest for TSLA", "highlights for ETH",
  "look into AMD", or any request for a comprehensive overview of a single
  asset. This is a read-only research skill — it does NOT place trades.
---

# Research Digest Skill

Generate a comprehensive one-page research digest for any stock or crypto.
Combines technical analysis, fundamentals, news, analyst consensus, macro
context, sentiment, and upcoming events into a single readable report.

## How to use

Run the research script for any ticker:

```bash
uv run .claude/skills/research/scripts/research_digest.py --ticker NVDA
uv run .claude/skills/research/scripts/research_digest.py --ticker BTC-USD
uv run .claude/skills/research/scripts/research_digest.py --ticker AAPL --period 1y
```

This outputs a structured JSON to `/tmp/research_TICKER.json` and prints
a human-readable digest to stdout.

## What's included in the digest

1. **Price & Trend** — Current price, daily change, 5d/20d/3mo performance
2. **Technical Setup** — RSI, MACD, Stochastic, Bollinger Bands, ADX, key MAs
3. **Support & Resistance** — Recent range, 52-week range
4. **Fundamentals** — P/E, market cap, sector, beta, dividend yield
5. **Analyst Consensus** — Price targets (mean/high/low), buy/hold/sell ratings, consensus score
6. **News Headlines** — Top 10 recent headlines from Alpaca or yfinance
7. **Headline Sentiment** — Bullish/bearish/neutral keyword scoring
8. **Macro Context** — VIX, yields, dollar, credit, breadth regime
9. **Upcoming Events** — FOMC, CPI, jobs, earnings within 14 days
10. **Overall Verdict** — Bullish/bearish/neutral summary with key takeaways

## How Claude should present the digest

After running the script, Claude should NOT just dump the output. Instead:

1. **Start with the numbers** — price, trend, key technical signals
2. **Read through the headlines** — identify the narrative/theme, not just keywords.
   Ask: is this new info or priced in? Signal or 烟雾弹 (smoke screen)?
3. **Cross-reference** — does the news explain the price action? If bullish news
   but price is flat/down, the market doesn't believe it. Say so.
4. **Present a "News Story"** section that summarizes what's actually happening
   in 2-3 sentences (e.g. "NVDA is in the middle of GTC 2026, announcing
   autonomous driving partnerships across Uber, Lyft, Hyundai. The theme is
   AI infrastructure expanding beyond data centers into physical world.")
5. **Give the verdict** — numbers decide, news adds color
6. Add Chinese explanations for technical terms where helpful

## Files

- `SKILL.md` — This file
- `scripts/research_digest.py` — Main research script
