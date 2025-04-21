CREATE TABLE IF NOT EXISTS l2_features (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timestamp BIGINT NOT NULL,
    queue_imbalance DOUBLE PRECISION NOT NULL,
    order_flow_imbalance DOUBLE PRECISION NOT NULL,
    depth_slope_bids DOUBLE PRECISION NOT NULL,
    depth_slope_asks DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT l2_features_queue_imbalance_check 
        CHECK (queue_imbalance BETWEEN -1 AND 1),
    CONSTRAINT l2_features_order_flow_imbalance_check 
        CHECK (order_flow_imbalance BETWEEN -1 AND 1),
        
    -- Indexes
    UNIQUE (symbol, timestamp)
);

-- Index for time-series queries
CREATE INDEX IF NOT EXISTS l2_features_symbol_timestamp_idx 
    ON l2_features (symbol, timestamp DESC);

-- Index for cleanup queries
CREATE INDEX IF NOT EXISTS l2_features_created_at_idx 
    ON l2_features (created_at DESC); 