-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Create trades table
CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT,
    symbol TEXT NOT NULL,
    price NUMERIC NOT NULL,
    quantity NUMERIC NOT NULL,
    side TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    is_liquidation BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_id, timestamp)
);

-- Create hypertable for trades
SELECT create_hypertable('trades', 'timestamp');

-- Create index on trades
CREATE INDEX IF NOT EXISTS idx_trades_symbol_timestamp ON trades(symbol, timestamp);

-- Create order book snapshots table
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    symbol TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    last_update_id BIGINT NOT NULL,
    bids JSONB NOT NULL,
    asks JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp, last_update_id)
);

-- Create hypertable for order book snapshots
SELECT create_hypertable('orderbook_snapshots', 'timestamp');

-- Create index on order book snapshots
CREATE INDEX IF NOT EXISTS idx_ob_symbol_timestamp ON orderbook_snapshots(symbol, timestamp);

-- Create klines table
CREATE TABLE IF NOT EXISTS klines (
    symbol TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    interval TEXT NOT NULL,
    open NUMERIC NOT NULL,
    high NUMERIC NOT NULL,
    low NUMERIC NOT NULL,
    close NUMERIC NOT NULL,
    volume NUMERIC NOT NULL,
    trade_count INTEGER NOT NULL,
    closed BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, interval, timestamp)
);

-- Create hypertable for klines
SELECT create_hypertable('klines', 'timestamp');

-- Create index on klines
CREATE INDEX IF NOT EXISTS idx_klines_symbol_interval_timestamp ON klines(symbol, interval, timestamp);

-- Create fills table
CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT,
    order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity NUMERIC NOT NULL,
    price NUMERIC NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    commission NUMERIC NOT NULL,
    commission_asset TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fill_id, timestamp)
);

-- Create hypertable for fills
SELECT create_hypertable('fills', 'timestamp');

-- Create index on fills
CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills(order_id);
CREATE INDEX IF NOT EXISTS idx_fills_symbol_timestamp ON fills(symbol, timestamp); 