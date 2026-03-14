# Technical Indicators Reference

Quick-reference guide for interpreting the indicators computed by `fetch_data.py`.

## Trend Indicators

### SMA (Simple Moving Average)
- **SMA 20**: Short-term trend. Price above = short-term bullish.
- **SMA 50**: Medium-term trend. Widely watched institutional level.
- **SMA 200**: Long-term trend. The most important MA for institutional investors.
- **Golden Cross**: SMA 50 crosses above SMA 200 → bullish signal
- **Death Cross**: SMA 50 crosses below SMA 200 → bearish signal

### EMA (Exponential Moving Average)
- Gives more weight to recent prices than SMA
- EMA 12 & EMA 26 are used to calculate MACD

### MACD (Moving Average Convergence Divergence)
- **MACD line** = EMA 12 - EMA 26
- **Signal line** = 9-day EMA of MACD line
- **Histogram** = MACD - Signal
- Bullish: MACD crosses above signal line, histogram turns positive
- Bearish: MACD crosses below signal line, histogram turns negative
- Divergence: Price makes new high but MACD doesn't → potential reversal

### ADX (Average Directional Index)
- Measures trend strength (not direction)
- 0-20: Weak/no trend
- 20-40: Strong trend
- 40-60: Very strong trend
- 60+: Extremely strong trend

## Momentum Indicators

### RSI (Relative Strength Index)
- Range: 0-100
- \>70: Overbought → potential pullback
- <30: Oversold → potential bounce
- 40-60: Neutral zone
- Divergence with price = potential reversal signal

### Stochastic Oscillator
- %K: Fast line, %D: Slow/signal line
- \>80: Overbought
- <20: Oversold
- %K crossing above %D in oversold = bullish
- %K crossing below %D in overbought = bearish

## Volatility Indicators

### Bollinger Bands
- Middle band = SMA 20
- Upper band = SMA 20 + 2σ
- Lower band = SMA 20 - 2σ
- Price touching upper band: overbought/strong uptrend
- Price touching lower band: oversold/strong downtrend
- Band squeeze (narrow bands): Low volatility, breakout incoming

### ATR (Average True Range)
- Measures volatility in dollar terms
- Use for stop-loss placement: Stop = Entry ± (1.5-2x ATR)
- Higher ATR = more volatile, wider stops needed

## Volume Indicators

### OBV (On Balance Volume)
- Running total of volume (add on up days, subtract on down days)
- Rising OBV + rising price = trend confirmed
- Rising OBV + falling price = accumulation (bullish divergence)
- Falling OBV + rising price = distribution (bearish divergence)

### Volume vs Average
- \>1.5x average: High volume, significant move
- <0.5x average: Low volume, weak conviction
- Breakouts on high volume are more reliable

## Combining Signals

Strong buy setup (multiple confirmations):
1. Price above SMA 50 and SMA 200
2. RSI between 40-60 (not overbought) or rising from <30
3. MACD bullish crossover
4. Volume above average
5. Price bouncing off support level

Strong sell/short setup:
1. Price below SMA 50 and SMA 200
2. RSI above 70 or falling from overbought
3. MACD bearish crossover
4. Volume above average on down days
5. Price rejected at resistance level

Risk management rules of thumb:
- Position size: Risk no more than 1-2% of portfolio per trade
- Stop loss: 1.5-2x ATR below entry (for longs)
- Take profit: Aim for 2:1 or 3:1 reward/risk ratio
- Never ignore a stop loss signal
