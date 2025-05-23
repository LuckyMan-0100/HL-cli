import pandas as pd
import psycopg2
import time
from typing import Iterator, Optional
from datetime import datetime, timedelta
import numpy as np

class OrderbookReader:
    def __init__(self, 
                 symbol: str,
                 batch_size: int = 1000,
                 poll_interval: float = 0.1,
                 connection_params: Optional[dict] = None):
        """
        Initialize the OrderbookReader for streaming L2 orderbook data.
        
        Args:
            symbol: Trading symbol to stream data for
            batch_size: Number of rows to fetch in each batch
            poll_interval: Time to wait between polling for new data (seconds)
            connection_params: Optional dict of Postgres connection parameters
        """
        self.symbol = symbol
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self.last_ts = None
        
        # Default connection parameters
        self.conn_params = connection_params or {
            'dbname': 'trading_data',
            'user': 'penrose',
            'password': '',
            'host': 'localhost',
            'port': 5432
        }

    def stream_updates(self) -> Iterator[pd.DataFrame]:
        """
        Stream orderbook updates from Postgres in near-real-time.
        
        Yields:
            DataFrame with columns: ts, side, price, qty, level
        """
        with psycopg2.connect(**self.conn_params) as conn:
            while True:
                query = """
                    WITH latest_snapshot AS (
                        SELECT *
                        FROM orderbook_snapshots
                        WHERE symbol = %s
                        AND timestamp > %s
                        ORDER BY timestamp
                        LIMIT %s
                    ),
                    bid_levels AS (
                        SELECT 
                            timestamp as ts,
                            'bid' as side,
                            (bid->>'price')::numeric as bid_price,
                            (bid->>'quantity')::numeric as bid_qty,
                            row_number() OVER () as level
                        FROM latest_snapshot,
                        jsonb_array_elements(bids) as bid
                    ),
                    ask_levels AS (
                        SELECT 
                            timestamp as ts,
                            'ask' as side,
                            (ask->>'price')::numeric as ask_price,
                            (ask->>'quantity')::numeric as ask_qty,
                            row_number() OVER () as level
                        FROM latest_snapshot,
                        jsonb_array_elements(asks) as ask
                    )
                    SELECT *
                    FROM bid_levels
                    UNION ALL
                    SELECT *
                    FROM ask_levels
                    ORDER BY ts, side, level
                """
                
                # Use current timestamp if no previous timestamp
                if self.last_ts is None:
                    self.last_ts = int(time.time() * 1000)
                
                # Fetch new data
                df = pd.read_sql_query(
                    query, 
                    conn,
                    params=(self.symbol, self.last_ts, self.batch_size)
                )
                
                if not df.empty:
                    self.last_ts = df['ts'].max()
                    yield df
                
                time.sleep(self.poll_interval)

    def get_snapshot(self) -> pd.DataFrame:
        """
        Get the latest orderbook snapshot.
        
        Returns:
            DataFrame with current orderbook state
        """
        with psycopg2.connect(**self.conn_params) as conn:
            query = """
                WITH latest_snapshot AS (
                    SELECT *
                    FROM orderbook_snapshots
                    WHERE symbol = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                ),
                bid_levels AS (
                    SELECT 
                        timestamp::bigint as ts,
                        'bid' as side,
                        (bid->>'price')::numeric as price,
                        (bid->>'quantity')::numeric as qty,
                        row_number() OVER (ORDER BY (bid->>'price')::numeric DESC) as level
                    FROM latest_snapshot,
                    jsonb_array_elements(bids) as bid
                ),
                ask_levels AS (
                    SELECT 
                        timestamp::bigint as ts,
                        'ask' as side,
                        (ask->>'price')::numeric as price,
                        (ask->>'quantity')::numeric as qty,
                        row_number() OVER (ORDER BY (ask->>'price')::numeric ASC) as level
                    FROM latest_snapshot,
                    jsonb_array_elements(asks) as ask
                )
                SELECT 
                    ts,
                    MAX(CASE WHEN side = 'bid' THEN price END) as bid_price,
                    MAX(CASE WHEN side = 'bid' THEN qty END) as bid_qty,
                    MAX(CASE WHEN side = 'ask' THEN price END) as ask_price,
                    MAX(CASE WHEN side = 'ask' THEN qty END) as ask_qty
                FROM (
                    SELECT * FROM bid_levels
                    UNION ALL
                    SELECT * FROM ask_levels
                ) combined
                GROUP BY ts
            """
            df = pd.read_sql_query(query, conn, params=(self.symbol,))
            print("Columns in DataFrame:", df.columns.tolist())
            print("First row:", df.iloc[0].to_dict())
            return df

if __name__ == "__main__":
    # Example usage
    reader = OrderbookReader("SOL_USDC_PERP")
    
    # Get initial snapshot
    snapshot = reader.get_snapshot()
    print("Initial Snapshot:")
    print(snapshot)
    
    # Stream updates
    print("\nStreaming updates:")
    for update in reader.stream_updates():
        print(f"\nNew update at {datetime.fromtimestamp(update['ts'].iloc[0]/1000)}:")
        print(update) 