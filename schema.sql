-- Market data schema

-- Order book snapshots
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    last_update_id BIGINT NOT NULL,
    bids JSONB NOT NULL,
    asks JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, last_update_id)
);

-- Create index on timestamp for time-based queries
CREATE INDEX IF NOT EXISTS orderbook_snapshots_timestamp_idx ON orderbook_snapshots (symbol, timestamp DESC);

-- Trades
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    price NUMERIC NOT NULL,
    quantity NUMERIC NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('buy', 'sell')),
    trade_id VARCHAR(50) NOT NULL,
    is_liquidation BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, trade_id)
);

-- Create index on timestamp for time-based queries
CREATE INDEX IF NOT EXISTS trades_timestamp_idx ON trades (symbol, timestamp DESC);

-- Klines (candlesticks)
CREATE TABLE IF NOT EXISTS klines (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    interval VARCHAR(3) NOT NULL,
    open NUMERIC NOT NULL,
    high NUMERIC NOT NULL,
    low NUMERIC NOT NULL,
    close NUMERIC NOT NULL,
    volume NUMERIC NOT NULL,
    trade_count INTEGER NOT NULL,
    closed BOOLEAN NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, interval, timestamp)
);

-- Create index on timestamp for time-based queries
CREATE INDEX IF NOT EXISTS klines_timestamp_idx ON klines (symbol, interval, timestamp DESC);

-- Add comments
COMMENT ON TABLE orderbook_snapshots IS 'Stores order book snapshots with full depth';
COMMENT ON TABLE trades IS 'Stores individual trades with price, size and side';
COMMENT ON TABLE klines IS 'Stores OHLCV candlestick data for different intervals'; 