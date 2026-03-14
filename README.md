# Traderz — AI-Powered Paper Trading

An automated stock analysis and paper trading system that combines real-time market data, technical analysis, and AI-driven decision making with simulated execution via Alpaca's Paper Trading API.

## Features

- **Data Fetching** — Pull historical OHLCV data for any US stock or ETF via yfinance
- **Technical Analysis** — Compute SMA, EMA, RSI, MACD, Bollinger Bands, ATR, OBV, ADX, Stochastic, and more
- **AI Decision Making** — Claude analyzes indicators and produces BUY/SELL/HOLD recommendations with confidence levels
- **Paper Trading** — Execute simulated trades through Alpaca (market, limit, stop, bracket orders)
- **Portfolio Management** — Track positions, P&L, and account status

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- [Alpaca](https://alpaca.markets) paper trading account (free)
- [Claude Code](https://claude.com/claude-code) CLI

## Quick Start

```bash
# Clone the repo
git clone https://github.com/zyli93/traderz.git
cd traderz

# Install dependencies
uv sync

# Set up Alpaca credentials (stored outside the repo)
mkdir -p ~/.config/traderz
cat > ~/.config/traderz/credentials.json << 'EOF'
{
  "ALPACA_API_KEY": "your_paper_trading_api_key",
  "ALPACA_SECRET_KEY": "your_paper_trading_secret_key"
}
EOF
chmod 600 ~/.config/traderz/credentials.json
```

## Usage with Claude Code

```
# Analyze a stock
> Analyze AAPL

# Execute a paper trade
> Buy 10 shares of TSLA

# Check your portfolio
> Show my portfolio

# Scan for opportunities
> What should I trade today?
```

## Disclaimer

This is a **simulation tool** for learning and strategy testing. It is **not financial advice**. All trades are executed on Alpaca's paper trading platform with virtual money. Past performance of any strategy does not guarantee future results.
