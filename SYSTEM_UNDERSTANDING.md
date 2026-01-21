# MangoCoco Trading Bot - System Understanding

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Service Breakdown](#service-breakdown)
4. [Trading Strategy](#trading-strategy)
5. [Data Flow](#data-flow)
6. [Current Configuration](#current-configuration)
7. [Profitability Analysis](#profitability-analysis)
8. [Improvement Suggestions](#improvement-suggestions)

---

## System Overview

MangoCoco is an automated cryptocurrency trading bot that trades on the MEXC exchange. It uses a microservices architecture with Docker containers communicating via Redis pub/sub messaging.

**Core Concept:** The bot analyzes price movements using momentum and RSI indicators, generates buy/sell signals, executes trades automatically, and manages positions with predefined take-profit and stop-loss targets.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MEXC EXCHANGE                            │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ API Calls
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DOCKER NETWORK                              │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ MARKET-DATA  │───▶│  PREDICTION  │───▶│   SIGNAL     │      │
│  │   Service    │    │   Service    │    │   Service    │      │
│  │              │    │              │    │              │      │
│  │ Fetches live │    │ Analyzes     │    │ Converts to  │      │
│  │ price ticks  │    │ momentum/RSI │    │ buy/sell     │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                   │                   │               │
│         ▼                   ▼                   ▼               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                      REDIS                               │   │
│  │  • latest_ticks (price data)                            │   │
│  │  • predictions:* (analysis results)                     │   │
│  │  • raw_signals (trading signals)                        │   │
│  │  • filled_orders (executed trades)                      │   │
│  │  • positions (open positions)                           │   │
│  │  • portfolio_state (balance tracking)                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│         │                   │                   │               │
│         ▼                   ▼                   ▼               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  EXECUTOR    │    │  POSITION    │    │    RISK      │      │
│  │   Service    │    │   Service    │    │   Service    │      │
│  │              │    │              │    │              │      │
│  │ Executes     │    │ Tracks open  │    │ Manages risk │      │
│  │ orders on    │    │ positions,   │    │ parameters   │      │
│  │ MEXC         │    │ triggers     │    │              │      │
│  │              │    │ TP/SL        │    │              │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Service Breakdown

### 1. Market Data Service (`services/market-data/`)
**Purpose:** Fetches real-time price data from MEXC

**How it works:**
- Connects to MEXC WebSocket for live price feeds
- Subscribes to 79 trading pairs
- Publishes tick data to Redis `latest_ticks` hash
- Updates every ~100ms

**Key Data:**
```json
{
  "symbol": "BTC/USDT",
  "price": 42000.50,
  "bid": 42000.00,
  "ask": 42001.00,
  "volume": 1234567.89,
  "change_pct": 2.5
}
```

---

### 2. Prediction Service (`services/prediction/`)
**Purpose:** Analyzes price data and generates trading predictions

**Strategy: Momentum + RSI**

**How it works:**
1. Receives price ticks from Redis
2. Calculates momentum (price change rate)
3. Calculates RSI (Relative Strength Index)
4. Generates prediction: `buy`, `sell`, or `hold`

**RSI Logic:**
- RSI < 35 (oversold) → BUY signal
- RSI > 65 (overbought) → SELL signal
- RSI 35-65 → HOLD

**Momentum Logic:**
- Price trending UP + volume spike → BUY
- Price trending DOWN → SELL

**Output:**
```json
{
  "symbol": "SOL/USDT",
  "direction": "buy",
  "confidence": 0.85,
  "current_price": 95.50
}
```

---

### 3. Signal Service (`services/signal/`)
**Purpose:** Converts predictions into actionable trading signals

**How it works:**
1. Receives predictions from Redis `predictions:*` channels
2. Checks confidence threshold (must be > 5%)
3. Checks available USDT balance (must be >= $1.50)
4. Checks if position already exists for symbol
5. Generates signal with exact $1.50 trade amount

**Rules:**
- Only BUY if no existing position
- Only SELL if has existing position
- Always trade exactly $1.50 USDT

**Output:**
```json
{
  "signal_id": "abc123",
  "symbol": "SOL/USDT",
  "action": "buy",
  "amount": 1.5,
  "price": 95.50,
  "confidence": 0.85
}
```

---

### 4. Executor Service (`services/executor/`)
**Purpose:** Executes trades on MEXC exchange

**How it works:**
1. Receives signals from Redis `raw_signals` channel
2. Fetches real-time price from MEXC
3. For BUY: Converts $1.50 USDT to coin quantity
4. Places market order on MEXC
5. Publishes result to `filled_orders` channel

**Key Logic:**
```python
# BUY: Convert USDT to coins
coin_quantity = usdt_amount / current_price  # $1.50 / $95.50 = 0.0157 SOL

# SELL: Use coin quantity from position
amount = position.amount
```

**MEXC Response Handling:**
- Handles null values from MEXC API
- Falls back to current price if order price is null
- Minimum order: $1.05 USDT (with buffer)

---

### 5. Position Service (`services/position/`)
**Purpose:** Tracks open positions and triggers automatic exits

**How it works:**
1. Listens for `filled_orders` from executor
2. Creates position record with entry price
3. Calculates stop-loss and take-profit prices
4. Monitors price every 100ms
5. Triggers sell signal when targets hit

**Position Record:**
```json
{
  "symbol": "SOL/USDT",
  "side": "long",
  "entry_price": 95.50,
  "current_price": 96.00,
  "amount": 0.0157,
  "stop_loss_price": 95.31,    // -0.2%
  "take_profit_price": 96.07,  // +0.6%
  "status": "open"
}
```

**Exit Triggers:**
1. **Take Profit:** Price >= take_profit_price → SELL
2. **Stop Loss:** Price <= stop_loss_price → SELL
3. ~~**Max Hold Time:** Disabled (was 60 min)~~

---

### 6. Risk Service (`services/risk/`)
**Purpose:** Manages risk parameters and portfolio limits

**Parameters:**
- Max position size: 15% of portfolio
- Max daily loss: 50%
- Max open positions: 20

---

## Trading Strategy

### Current Strategy: Momentum + RSI Scalping

**Entry Conditions (BUY):**
1. RSI < 35 (oversold) OR
2. Positive momentum + volume spike
3. Confidence > 5%
4. Have >= $1.50 USDT available

**Exit Conditions (SELL):**
1. Take Profit: +0.6% from entry
2. Stop Loss: -0.2% from entry

**Risk/Reward Ratio:** 3:1
- Risk $0.003 (0.2% of $1.50) to make $0.009 (0.6% of $1.50)
- Break-even win rate: ~25%

---

## Data Flow

```
1. MARKET-DATA fetches BTC price: $42,000
         │
         ▼
2. PREDICTION analyzes: RSI=32 (oversold) → direction=buy, confidence=0.85
         │
         ▼
3. SIGNAL checks balance ($6.27) → generates buy signal for $1.50
         │
         ▼
4. EXECUTOR places order: buy 0.0000357 BTC @ $42,000
         │
         ▼
5. POSITION tracks: entry=$42,000, TP=$42,252 (+0.6%), SL=$41,916 (-0.2%)
         │
         ▼
6. Price rises to $42,300 → POSITION triggers take-profit
         │
         ▼
7. EXECUTOR sells → Profit: $0.007 (0.4% after fees)
```

---

## Current Configuration

| Parameter | Value | Description |
|-----------|-------|-------------|
| PROFIT_TARGET_PCT | 0.6% | Take profit target |
| MAX_TRADE_LOSS_PCT | 0.2% | Stop loss target |
| MAX_HOLD_TIME_MINUTES | 0 | Unlimited (hold until targets) |
| Trade Size | $1.50 | Fixed per trade |
| Trading Pairs | 79 | Coins monitored |
| RSI_OVERSOLD | 35 | Buy when RSI below |
| RSI_OVERBOUGHT | 65 | Sell when RSI above |
| CONFIDENCE_THRESHOLD | 5% | Minimum signal confidence |

---

## Profitability Analysis

### Current Math (per trade):

**Winning Trade:**
- Gross profit: +0.6% × $1.50 = +$0.009
- Trading fees: -0.2% × $1.50 = -$0.003 (buy + sell)
- **Net profit: +$0.006 (+0.4%)**

**Losing Trade:**
- Gross loss: -0.2% × $1.50 = -$0.003
- Trading fees: -0.2% × $1.50 = -$0.003
- **Net loss: -$0.006 (-0.4%)**

**Break-even win rate:** 50%

### Issues with Current Strategy:

1. **Momentum in Crypto is Noisy**
   - Crypto prices are highly volatile
   - Short-term momentum often reverses quickly
   - Many false signals in sideways markets

2. **0.2% Stop Loss is Very Tight**
   - Normal price fluctuation can trigger stop loss
   - May get stopped out before price moves in your favor

3. **Single Indicator Strategy**
   - RSI alone is not a strong predictor
   - Works better with additional confirmation

---

## Improvement Suggestions

### 1. Widen Stop Loss (Recommended: 0.5-1%)

**Why:** 0.2% is within normal noise. Prices often dip briefly before continuing up.

**Change:**
```
MAX_TRADE_LOSS_PCT=0.005  # 0.5% stop loss
PROFIT_TARGET_PCT=0.015   # 1.5% take profit (maintain 3:1 ratio)
```

**Impact:** Fewer stop-outs from noise, bigger wins when right.

---

### 2. Add Trend Filter

**Why:** Don't buy in a downtrend, don't sell in an uptrend.

**Implementation idea:**
- Calculate 1-hour moving average
- Only BUY if price > 1h MA (uptrend)
- Only SELL if price < 1h MA (downtrend)

---

### 3. Add Volume Confirmation

**Why:** Price moves with high volume are more reliable.

**Current:** Volume spike threshold is only 5%
**Suggested:** Require 20-50% volume increase for signals

```
VOLUME_SPIKE_THRESHOLD=1.20  # 20% above average
```

---

### 4. Time-Based Filters

**Why:** Crypto behaves differently at different times.

**Ideas:**
- Avoid trading during low-volume hours (e.g., 2-6 AM UTC)
- Trade more during high-volatility periods (US/EU market overlap)

---

### 5. Trailing Stop Loss

**Why:** Lock in profits as price moves in your favor.

**How it would work:**
- Initial stop loss: -0.5%
- If price goes +0.3%, move stop loss to -0.2%
- If price goes +0.5%, move stop loss to break-even
- If price goes +0.8%, move stop loss to +0.3%

**Impact:** Capture more profit on big moves, protect gains.

---

### 6. Multiple Timeframe Analysis

**Why:** Align short-term and long-term trends.

**Implementation:**
- Check 15-min, 1-hour, and 4-hour RSI
- Only trade when all timeframes agree

---

### 7. Coin Selection

**Why:** Not all coins are equally profitable for scalping.

**Better coins for scalping:**
- High liquidity (tight spreads)
- Moderate volatility
- Active trading volume

**Suggested focus:** Top 20 by volume instead of 79 coins.

---

### 8. Backtesting

**Why:** Test strategies on historical data before risking real money.

**Tools to consider:**
- Backtrader (Python)
- QuantConnect
- TradingView Pine Script

---

### 9. Paper Trading Mode

**Why:** Test changes without risking capital.

**Current:** `MOCK_MODE=false`
**For testing:** Set `MOCK_MODE=true`

---

### 10. Position Sizing Based on Confidence

**Why:** Bet more when signals are stronger.

**Example:**
- Confidence 70-80%: Trade $1.50
- Confidence 80-90%: Trade $2.00
- Confidence 90%+: Trade $2.50

---

## Quick Wins (Easy to Implement)

| Change | Effort | Expected Impact |
|--------|--------|-----------------|
| Widen stop loss to 0.5% | Low | Fewer noise stop-outs |
| Increase take profit to 1.5% | Low | Bigger wins |
| Increase volume threshold to 20% | Low | Fewer false signals |
| Reduce to top 20 coins | Low | Better liquidity |
| Add moving average filter | Medium | Better trend alignment |
| Trailing stop loss | Medium | Lock in profits |

---

## Monitoring Commands

**Watch live trades:**
```bash
python monitor.py
```

**Check balance:**
```bash
curl http://localhost:8005/balance
```

**Check positions:**
```bash
docker exec mc-redis redis-cli -a $REDIS_PASSWORD HGETALL positions
```

**View logs:**
```bash
docker logs mc-executor --tail 50
docker logs mc-signal --tail 50
docker logs mc-position --tail 50
```

---

## Files Reference

| File | Purpose |
|------|---------|
| `config/trading.env` | Main configuration |
| `services/executor/main.py` | Order execution |
| `services/position/main.py` | Position tracking |
| `services/signal/main.py` | Signal generation |
| `services/prediction/main.py` | Price analysis |
| `monitor.py` | Live trade monitor |

---

## Summary

The system is well-architected with proper separation of concerns. The main areas for improvement are:

1. **Strategy refinement** - Current momentum/RSI strategy needs additional filters
2. **Risk management** - Stop loss may be too tight for crypto volatility
3. **Signal quality** - Add more confirmation before trading

Start with the "Quick Wins" above before making larger changes. Always test in mock mode first!
