-- MangoCoco Database Schema v2.0
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- =============================================
-- EXISTING TABLES (v1.0)
-- =============================================

-- Market Data (raw ticks)
CREATE TABLE IF NOT EXISTS ticks (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    bid DECIMAL(20, 8),
    ask DECIMAL(20, 8),
    volume DECIMAL(20, 8),
    PRIMARY KEY (time, symbol)
);
SELECT create_hypertable('ticks', 'time', if_not_exists => TRUE);

-- Orders
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    order_id VARCHAR(100) UNIQUE NOT NULL,
    exchange_order_id VARCHAR(100),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(4) NOT NULL,
    order_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    price DECIMAL(20, 8),
    amount DECIMAL(20, 8) NOT NULL,
    filled DECIMAL(20, 8) DEFAULT 0,
    cost DECIMAL(20, 8) DEFAULT 0,
    fee DECIMAL(20, 8) DEFAULT 0
);

-- Positions
CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(5) NOT NULL,
    entry_price DECIMAL(20, 8) NOT NULL,
    current_price DECIMAL(20, 8),
    amount DECIMAL(20, 8) NOT NULL,
    unrealized_pnl DECIMAL(20, 8) DEFAULT 0,
    realized_pnl DECIMAL(20, 8) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'open'
);

-- Signals
CREATE TABLE IF NOT EXISTS signals (
    time TIMESTAMPTZ NOT NULL,
    signal_id VARCHAR(100) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    action VARCHAR(10) NOT NULL,
    confidence DECIMAL(5, 4) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    executed BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (time, signal_id)
);
SELECT create_hypertable('signals', 'time', if_not_exists => TRUE);

-- Portfolio snapshots
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    time TIMESTAMPTZ NOT NULL PRIMARY KEY,
    total_value DECIMAL(20, 8) NOT NULL,
    cash_balance DECIMAL(20, 8) NOT NULL,
    positions_value DECIMAL(20, 8) NOT NULL,
    daily_pnl DECIMAL(20, 8) NOT NULL
);
SELECT create_hypertable('portfolio_snapshots', 'time', if_not_exists => TRUE);

-- Initial portfolio
INSERT INTO portfolio_snapshots (time, total_value, cash_balance, positions_value, daily_pnl)
VALUES (NOW(), 11.00, 11.00, 0, 0) ON CONFLICT DO NOTHING;

-- =============================================
-- NEW TABLES (v2.0)
-- =============================================

-- OHLCV candles (aggregated from ticks or backfilled from exchange)
CREATE TABLE IF NOT EXISTS candles (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,  -- '1m', '5m', '15m', '1h', '4h', '1d'
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    PRIMARY KEY (time, symbol, timeframe)
);
SELECT create_hypertable('candles', 'time', if_not_exists => TRUE);

-- Sentiment scores from various sources
CREATE TABLE IF NOT EXISTS sentiment_scores (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    source VARCHAR(50) NOT NULL,  -- 'cryptopanic', 'reddit', 'fear_greed'
    score DECIMAL(5, 4) NOT NULL, -- -1.0 to 1.0
    volume INTEGER DEFAULT 0,     -- number of mentions
    raw_data JSONB,               -- optional raw source data
    PRIMARY KEY (time, symbol, source)
);
SELECT create_hypertable('sentiment_scores', 'time', if_not_exists => TRUE);

-- ML model predictions (for evaluation and backtesting audit)
CREATE TABLE IF NOT EXISTS ml_predictions (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    model_name VARCHAR(50) NOT NULL,      -- 'tcn', 'xgboost', 'ensemble'
    model_version VARCHAR(50) NOT NULL,
    direction VARCHAR(15) NOT NULL,       -- 'strong_buy', 'buy', 'hold', 'sell', 'strong_sell'
    confidence DECIMAL(5, 4) NOT NULL,
    features JSONB,                       -- input features snapshot
    actual_return_5m DECIMAL(10, 6),      -- filled in later for evaluation
    actual_return_15m DECIMAL(10, 6),
    actual_return_30m DECIMAL(10, 6),
    PRIMARY KEY (time, symbol, model_name)
);
SELECT create_hypertable('ml_predictions', 'time', if_not_exists => TRUE);

-- On-chain and exchange metrics
CREATE TABLE IF NOT EXISTS onchain_metrics (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    metric_name VARCHAR(50) NOT NULL,  -- 'whale_flow', 'exchange_netflow', 'funding_rate', etc.
    value DECIMAL(20, 8) NOT NULL,
    metadata JSONB,
    PRIMARY KEY (time, symbol, metric_name)
);
SELECT create_hypertable('onchain_metrics', 'time', if_not_exists => TRUE);

-- Backtesting results
CREATE TABLE IF NOT EXISTS backtest_runs (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    strategy_name VARCHAR(100) NOT NULL,
    parameters JSONB NOT NULL,
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,
    total_trades INTEGER,
    win_rate DECIMAL(5, 4),
    sharpe_ratio DECIMAL(10, 4),
    sortino_ratio DECIMAL(10, 4),
    max_drawdown DECIMAL(10, 4),
    total_return DECIMAL(10, 4),
    profit_factor DECIMAL(10, 4),
    results JSONB                    -- detailed trade-by-trade results
);

-- Trade history (persisted from Redis for long-term analysis)
CREATE TABLE IF NOT EXISTS trade_history (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(5) NOT NULL,
    entry_price DECIMAL(20, 8) NOT NULL,
    exit_price DECIMAL(20, 8),
    amount DECIMAL(20, 8) NOT NULL,
    realized_pnl DECIMAL(20, 8),
    pnl_pct DECIMAL(10, 6),
    exit_reason VARCHAR(50),         -- 'stop_loss', 'take_profit', 'trailing_stop', 'max_hold_time', 'manual'
    strategy VARCHAR(50),            -- which strategy generated this trade
    hold_time_seconds INTEGER,
    fees DECIMAL(20, 8) DEFAULT 0
);

-- =============================================
-- INDEXES
-- =============================================
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time ON ticks(symbol, time DESC);
CREATE INDEX IF NOT EXISTS idx_candles_symbol_tf ON candles(symbol, timeframe, time DESC);
CREATE INDEX IF NOT EXISTS idx_sentiment_symbol_time ON sentiment_scores(symbol, time DESC);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_symbol ON ml_predictions(symbol, time DESC);
CREATE INDEX IF NOT EXISTS idx_onchain_symbol ON onchain_metrics(symbol, metric_name, time DESC);
CREATE INDEX IF NOT EXISTS idx_trade_history_symbol ON trade_history(symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_history_strategy ON trade_history(strategy, created_at DESC);

-- =============================================
-- CONTINUOUS AGGREGATES (materialized views for dashboard)
-- =============================================

-- 1-minute candles from ticks (auto-refreshed)
CREATE MATERIALIZED VIEW IF NOT EXISTS candles_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time) AS bucket,
    symbol,
    first(price, time) AS open,
    max(price) AS high,
    min(price) AS low,
    last(price, time) AS close,
    sum(volume) AS volume
FROM ticks
GROUP BY bucket, symbol
WITH NO DATA;

-- Hourly portfolio performance
CREATE MATERIALIZED VIEW IF NOT EXISTS portfolio_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    last(total_value, time) AS total_value,
    last(cash_balance, time) AS cash_balance,
    last(positions_value, time) AS positions_value,
    last(daily_pnl, time) AS daily_pnl
FROM portfolio_snapshots
GROUP BY bucket
WITH NO DATA;

-- Permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO mangococo;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mangococo;
