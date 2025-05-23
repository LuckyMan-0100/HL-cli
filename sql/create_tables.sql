CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    ts TIMESTAMP WITH TIME ZONE NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('bid', 'ask')),
    price DECIMAL(20, 8) NOT NULL,
    qty DECIMAL(20, 8) NOT NULL,
    level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 10),
    PRIMARY KEY (ts, side, level)
);

CREATE INDEX IF NOT EXISTS orderbook_snapshots_ts_idx ON orderbook_snapshots (ts);

-- Initial test data
INSERT INTO orderbook_snapshots (ts, side, price, qty, level) VALUES
    (NOW(), 'bid', 50000.00, 1.5, 1),
    (NOW(), 'bid', 49990.00, 2.0, 2),
    (NOW(), 'ask', 50010.00, 1.0, 1),
    (NOW(), 'ask', 50020.00, 2.5, 2); 