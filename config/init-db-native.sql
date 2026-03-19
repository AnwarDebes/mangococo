-- Goblin Database Schema v2.0 (Native PostgreSQL - no TimescaleDB)

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

-- Portfolio snapshots
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    time TIMESTAMPTZ NOT NULL PRIMARY KEY,
    total_value DECIMAL(20, 8) NOT NULL,
    cash_balance DECIMAL(20, 8) NOT NULL,
    positions_value DECIMAL(20, 8) NOT NULL,
    daily_pnl DECIMAL(20, 8) NOT NULL
);

-- Initial portfolio
INSERT INTO portfolio_snapshots (time, total_value, cash_balance, positions_value, daily_pnl)
VALUES (NOW(), 1000.00, 1000.00, 0, 0) ON CONFLICT DO NOTHING;

-- =============================================
-- NEW TABLES (v2.0)
-- =============================================

-- OHLCV candles (aggregated from ticks or backfilled from exchange)
CREATE TABLE IF NOT EXISTS candles (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    PRIMARY KEY (time, symbol, timeframe)
);

-- Sentiment scores from various sources
CREATE TABLE IF NOT EXISTS sentiment_scores (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    source VARCHAR(50) NOT NULL,
    score DECIMAL(5, 4) NOT NULL,
    mentions INTEGER DEFAULT 1,
    label VARCHAR(20),
    text_hash VARCHAR(32),
    raw_data JSONB,
    PRIMARY KEY (time, symbol, source)
);

-- ML model predictions
CREATE TABLE IF NOT EXISTS ml_predictions (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    model_name VARCHAR(50) NOT NULL,
    model_version VARCHAR(50) NOT NULL,
    direction VARCHAR(15) NOT NULL,
    confidence DECIMAL(5, 4) NOT NULL,
    features JSONB,
    actual_return_5m DECIMAL(10, 6),
    actual_return_15m DECIMAL(10, 6),
    actual_return_30m DECIMAL(10, 6),
    PRIMARY KEY (time, symbol, model_name)
);

-- On-chain and exchange metrics
CREATE TABLE IF NOT EXISTS onchain_metrics (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    metric_name VARCHAR(50) NOT NULL,
    value DECIMAL(20, 8) NOT NULL,
    metadata JSONB,
    PRIMARY KEY (time, symbol, metric_name)
);

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
    results JSONB
);

-- Trade history
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
    exit_reason VARCHAR(50),
    strategy VARCHAR(50),
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
-- Permissions
-- =============================================
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO goblin;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO goblin;
