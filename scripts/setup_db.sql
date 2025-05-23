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
SELECT create_hypertable('trades', 'timestamp', if_not_exists => TRUE);

-- Create index on trades
CREATE INDEX IF NOT EXISTS idx_trades_symbol_timestamp ON trades(symbol, timestamp DESC);

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
SELECT create_hypertable('orderbook_snapshots', 'timestamp', if_not_exists => TRUE);

-- Create index on order book snapshots
CREATE INDEX IF NOT EXISTS idx_ob_symbol_timestamp ON orderbook_snapshots(symbol, timestamp DESC);

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
SELECT create_hypertable('klines', 'timestamp', if_not_exists => TRUE);

-- Create index on klines
CREATE INDEX IF NOT EXISTS idx_klines_symbol_interval_timestamp ON klines(symbol, interval, timestamp DESC);

-- Create L2 features table for ML training
CREATE TABLE IF NOT EXISTS l2_features (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    queue_imbalance DOUBLE PRECISION NOT NULL,
    order_flow_imbalance DOUBLE PRECISION NOT NULL,
    depth_slope_bids DOUBLE PRECISION NOT NULL,
    depth_slope_asks DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT l2_features_queue_imbalance_check 
        CHECK (queue_imbalance BETWEEN -1 AND 1),
    CONSTRAINT l2_features_order_flow_imbalance_check 
        CHECK (order_flow_imbalance BETWEEN -1 AND 1),
        
    -- Unique constraint
    CONSTRAINT l2_features_unique_key UNIQUE (symbol, timestamp)
);

-- Create hypertable for L2 features
SELECT create_hypertable('l2_features', 'timestamp', if_not_exists => TRUE);

-- Create index for L2 features
CREATE INDEX IF NOT EXISTS l2_features_symbol_timestamp_idx 
    ON l2_features (symbol, timestamp DESC);

-- Create ML model metrics table
CREATE TABLE IF NOT EXISTS model_metrics (
    id SERIAL PRIMARY KEY,
    model_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (model_id, timestamp, metric_name)
);

-- Create hypertable for model metrics
SELECT create_hypertable('model_metrics', 'timestamp', if_not_exists => TRUE);

-- Create index for model metrics
CREATE INDEX IF NOT EXISTS model_metrics_model_timestamp_idx 
    ON model_metrics (model_id, timestamp DESC);

-- Create model artifacts table
CREATE TABLE IF NOT EXISTS model_artifacts (
    id SERIAL PRIMARY KEY,
    model_id TEXT NOT NULL,
    version TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    metadata JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (model_id, version)
);

-- Grant permissions
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO PUBLIC;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO PUBLIC; 