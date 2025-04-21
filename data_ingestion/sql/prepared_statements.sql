-- Prepared statements for data ingestion

-- Insert trade
PREPARE insert_trade AS
    INSERT INTO trades (
        symbol, trade_id, side, price, quantity, timestamp,
        is_liquidation, created_at
    ) VALUES (
        $1, $2, $3, $4::numeric, $5::numeric, to_timestamp($6::bigint/1000),
        $7::boolean, CURRENT_TIMESTAMP
    ) ON CONFLICT (trade_id, timestamp) DO NOTHING;

-- Insert orderbook snapshot
PREPARE insert_orderbook AS
    INSERT INTO orderbook_snapshots (
        symbol, timestamp, last_update_id, bids, asks, created_at
    ) VALUES (
        $1, to_timestamp($2::bigint/1000), $3::bigint, $4::jsonb, $5::jsonb,
        CURRENT_TIMESTAMP
    ) ON CONFLICT (symbol, timestamp, last_update_id) DO NOTHING;

-- Insert kline
PREPARE insert_kline AS
    INSERT INTO klines (
        symbol, interval, timestamp, open, high, low, close,
        volume, trade_count, closed, created_at
    ) VALUES (
        $1, $2, to_timestamp($3::bigint/1000),
        $4::numeric, $5::numeric, $6::numeric, $7::numeric,
        $8::numeric, $9::integer, $10::boolean,
        CURRENT_TIMESTAMP
    ) ON CONFLICT (symbol, interval, timestamp) DO NOTHING; 