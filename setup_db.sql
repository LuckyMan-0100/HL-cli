-- Create tables for trading system

-- Order book snapshots (L2 data)
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    timestamp BIGINT NOT NULL, -- Epoch milliseconds
    last_update_id BIGINT,
    bids JSONB,
    asks JSONB,
    received_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index on timestamp for efficient tailing
CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_timestamp 
ON orderbook_snapshots(timestamp);

-- Create index on symbol for filtering
CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_symbol 
ON orderbook_snapshots(symbol);

-- Trades table
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    timestamp BIGINT NOT NULL,
    price DECIMAL(20,8) NOT NULL,
    quantity DECIMAL(20,8) NOT NULL,
    is_buyer_maker BOOLEAN NOT NULL,
    received_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_timestamp 
ON trades(timestamp);

CREATE INDEX IF NOT EXISTS idx_trades_symbol 
ON trades(symbol);

-- Features table
CREATE TABLE IF NOT EXISTS features (
    id SERIAL PRIMARY KEY,
    timestamp BIGINT NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    rsi_14 DECIMAL(10,4),
    macd DECIMAL(10,4),
    macd_signal DECIMAL(10,4),
    macd_hist DECIMAL(10,4),
    bb_upper DECIMAL(20,8),
    bb_middle DECIMAL(20,8),
    bb_lower DECIMAL(20,8),
    atr_14 DECIMAL(10,4),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_features_timestamp 
ON features(timestamp);

CREATE INDEX IF NOT EXISTS idx_features_symbol 
ON features(symbol);

-- Positions tracking
CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    entry_price DECIMAL(20,8) NOT NULL,
    quantity DECIMAL(20,8) NOT NULL,
    timestamp BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL,
    pnl DECIMAL(20,8),
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_positions_timestamp 
ON positions(timestamp);

CREATE INDEX IF NOT EXISTS idx_positions_symbol 
ON positions(symbol);

-- Risk metrics
CREATE TABLE IF NOT EXISTS risk_metrics (
    id SERIAL PRIMARY KEY,
    timestamp BIGINT NOT NULL,
    equity DECIMAL(20,8) NOT NULL,
    total_pnl DECIMAL(20,8) NOT NULL,
    drawdown DECIMAL(10,4) NOT NULL,
    total_notional DECIMAL(20,8) NOT NULL,
    position_count INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_metrics_timestamp 
ON risk_metrics(timestamp); 