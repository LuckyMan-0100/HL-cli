import logging
from typing import List, Optional, Dict
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime
from decimal import Decimal
import json
import pandas as pd

from .settings import settings
from .models import Trade, OrderBook, Kline

logger = logging.getLogger(__name__)

class PostgresWriter:
    """Handles writing market data to PostgreSQL database."""

    def __init__(self):
        print("PostgresWriter init starting...")  # Debug print
        self.dsn = settings.database.dsn
        print(f"DSN: {self.dsn}")  # Debug print
        self._conn = None
        logger.info(f"Initializing PostgresWriter with DSN: {self.dsn}")
        try:
            print("Ensuring tables...")  # Debug print
            self._ensure_tables()
            print("Tables ensured successfully")  # Debug print
        except Exception as e:
            print(f"Error ensuring tables: {str(e)}")  # Debug print
            raise

    def _get_conn(self):
        """Get a database connection, creating it if necessary."""
        try:
            if self._conn is None or self._conn.closed:
                print("Creating new database connection...")  # Debug print
                self._conn = psycopg2.connect(self.dsn)
                print("Database connection established")  # Debug print
            return self._conn
        except psycopg2.Error as e:
            print(f"Database connection error: {str(e)}")  # Debug print
            logger.error(f"Failed to connect to database: {str(e)}")
            raise

    def _ensure_tables(self):
        """Create necessary tables if they don't exist."""
        logger.info("Ensuring required database tables exist...")
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                # Enable TimescaleDB extension
                logger.info("Enabling TimescaleDB extension...")
                cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
                
                # Trades table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        trade_id TEXT PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        price NUMERIC NOT NULL,
                        quantity NUMERIC NOT NULL,
                        side TEXT NOT NULL,
                        timestamp BIGINT NOT NULL,
                        is_liquidation BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_trades_symbol_timestamp ON trades(symbol, timestamp);
                """)

                # Order book snapshots table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                        symbol TEXT NOT NULL,
                        timestamp BIGINT NOT NULL,
                        last_update_id BIGINT NOT NULL,
                        bids JSONB NOT NULL,
                        asks JSONB NOT NULL,
                        PRIMARY KEY (symbol, timestamp)
                    );
                    CREATE INDEX IF NOT EXISTS idx_ob_symbol_timestamp 
                    ON orderbook_snapshots(symbol, timestamp);
                """)
                
                # Convert orderbook_snapshots to TimescaleDB hypertable
                cur.execute("""
                    SELECT create_hypertable('orderbook_snapshots', 'timestamp', 
                                           if_not_exists => TRUE,
                                           migrate_data => TRUE);
                """)

                # Klines table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS klines (
                        symbol TEXT NOT NULL,
                        timestamp BIGINT NOT NULL,
                        interval TEXT NOT NULL,
                        open NUMERIC NOT NULL,
                        high NUMERIC NOT NULL,
                        low NUMERIC NOT NULL,
                        close NUMERIC NOT NULL,
                        volume NUMERIC NOT NULL,
                        trade_count INTEGER NOT NULL,
                        closed BOOLEAN NOT NULL,
                        PRIMARY KEY (symbol, interval, timestamp)
                    );
                    CREATE INDEX IF NOT EXISTS idx_klines_lookup 
                    ON klines(symbol, interval, timestamp DESC);
                """)

                conn.commit()
        except Exception as e:
            logger.error(f"Failed to ensure tables: {str(e)}")
            raise

    def write_trade(self, trade: Trade):
        """Write a single trade to the database."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            # Convert datetime to millisecond timestamp
            timestamp_ms = int(trade.timestamp.timestamp() * 1000)
            
            cur.execute("""
                INSERT INTO trades (
                    trade_id, symbol, price, quantity, side, 
                    timestamp, is_liquidation
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (trade_id) DO NOTHING
            """, (
                trade.trade_id, trade.symbol, str(trade.price), 
                str(trade.quantity), trade.side, timestamp_ms,
                trade.is_liquidation
            ))
            conn.commit()

    def write_trades(self, trades: List[Trade]):
        """Write multiple trades to the database efficiently."""
        if not trades:
            return

        conn = self._get_conn()
        with conn.cursor() as cur:
            values = [
                (t.trade_id, t.symbol, str(t.price), str(t.quantity),
                 t.side, int(t.timestamp.timestamp() * 1000), t.is_liquidation)
                for t in trades
            ]
            execute_values(cur, """
                INSERT INTO trades (
                    trade_id, symbol, price, quantity, side, 
                    timestamp, is_liquidation
                ) VALUES %s
                ON CONFLICT (trade_id) DO NOTHING
            """, values)
            conn.commit()

    def write_orderbook(self, orderbook: OrderBook):
        """Write an order book snapshot to the database."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            # Convert Decimal objects to strings for JSON serialization
            bids = [[str(price), str(qty)] for price, qty in orderbook.bids.items()]
            asks = [[str(price), str(qty)] for price, qty in orderbook.asks.items()]
            
            # Convert datetime to millisecond timestamp
            timestamp_ms = int(orderbook.timestamp.timestamp() * 1000)
            
            cur.execute("""
                INSERT INTO orderbook_snapshots (
                    symbol, timestamp, last_update_id, bids, asks
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (symbol, timestamp) DO UPDATE
                SET last_update_id = EXCLUDED.last_update_id,
                    bids = EXCLUDED.bids,
                    asks = EXCLUDED.asks
            """, (
                orderbook.symbol,
                timestamp_ms,
                orderbook.last_update_id,
                json.dumps(bids),
                json.dumps(asks)
            ))
            conn.commit()

    def write_kline(self, kline: Kline):
        """Write a single kline/candlestick to the database."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            # Convert datetime to millisecond timestamp
            timestamp_ms = int(kline.timestamp.timestamp() * 1000)
            
            cur.execute("""
                INSERT INTO klines (
                    symbol, timestamp, interval, open, high, low,
                    close, volume, trade_count, closed
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, interval, timestamp) 
                DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    trade_count = EXCLUDED.trade_count,
                    closed = EXCLUDED.closed
            """, (
                kline.symbol, timestamp_ms, kline.interval,
                str(kline.open), str(kline.high), str(kline.low),
                str(kline.close), str(kline.volume),
                kline.trade_count, kline.closed
            ))
            conn.commit()

    def get_latest_klines(
        self, symbol: str, interval: str, limit: int = 5000
    ) -> List[Kline]:
        """Retrieve the latest klines for a symbol and interval."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT symbol, timestamp, interval, open, high, low,
                       close, volume, trade_count, closed
                FROM klines
                WHERE symbol = %s AND interval = %s
                ORDER BY timestamp DESC
                LIMIT %s
            """, (symbol, interval, limit))
            
            rows = cur.fetchall()
            
            return [
                Kline(
                    symbol=row[0],
                    timestamp=datetime.fromtimestamp(row[1] / 1000),
                    interval=row[2],
                    open=Decimal(str(row[3])),
                    high=Decimal(str(row[4])),
                    low=Decimal(str(row[5])),
                    close=Decimal(str(row[6])),
                    volume=Decimal(str(row[7])),
                    trade_count=row[8],
                    closed=row[9]
                )
                for row in reversed(rows)  # Reverse to get chronological order
            ]

    def get_klines_in_range(
        self,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict]:
        """
        Retrieve klines within a specified time range.
        
        Args:
            symbol: Trading symbol
            interval: Kline interval (e.g., "1m", "5m")
            start_time: Start of time range
            end_time: End of time range
            
        Returns:
            List of kline dictionaries
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            # Convert datetime to millisecond timestamps for comparison
            start_ms = int(start_time.timestamp() * 1000)
            end_ms = int(end_time.timestamp() * 1000)
            
            cur.execute("""
                SELECT 
                    symbol,
                    timestamp,
                    interval,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    trade_count,
                    closed
                FROM klines
                WHERE symbol = %s 
                AND interval = %s
                AND timestamp BETWEEN %s AND %s
                ORDER BY timestamp ASC
            """, (symbol, interval, start_ms, end_ms))
            
            rows = cur.fetchall()
            
            return [
                {
                    'symbol': row[0],
                    'timestamp': datetime.fromtimestamp(row[1] / 1000),
                    'interval': row[2],
                    'open': str(row[3]),
                    'high': str(row[4]),
                    'low': str(row[5]),
                    'close': str(row[6]),
                    'volume': str(row[7]),
                    'trade_count': row[8],
                    'closed': row[9]
                }
                for row in rows
            ]

    def get_orderbook_in_range(self, symbol: str, start_time: datetime, 
                              end_time: datetime, sample_interval: str = '1 minute') -> pd.DataFrame:
        """
        Get sampled orderbook data within a time range.
        
        Args:
            symbol: Trading pair symbol
            start_time: Start of time range (datetime)
            end_time: End of time range (datetime)
            sample_interval: Sampling interval (e.g. '1 minute', '5 minutes')
            
        Returns:
            DataFrame with columns: timestamp, bid_price, bid_quantity, ask_price, ask_quantity
        """
        print(f"Fetching orderbook data from {start_time} to {end_time}")
        conn = self._get_conn()
        with conn.cursor() as cur:
            # Convert datetime to millisecond timestamps for comparison
            start_ms = int(start_time.timestamp() * 1000)
            end_ms = int(end_time.timestamp() * 1000)
            
            # First count total records for progress tracking
            cur.execute("""
                SELECT COUNT(*) 
                FROM orderbook_snapshots 
                WHERE symbol = %s 
                AND timestamp BETWEEN %s AND %s
            """, (symbol, start_ms, end_ms))
            total_records = cur.fetchone()[0]
            print(f"Found {total_records} orderbook records to process")
            
            # Updated query to handle the correct JSON structure
            cur.execute("""
                SELECT 
                    timestamp,
                    COALESCE((bids->0->>'price')::NUMERIC, NULL) as bid_price,
                    COALESCE((bids->0->>'quantity')::NUMERIC, NULL) as bid_quantity,
                    COALESCE((asks->0->>'price')::NUMERIC, NULL) as ask_price,
                    COALESCE((asks->0->>'quantity')::NUMERIC, NULL) as ask_quantity
                FROM orderbook_snapshots
                WHERE symbol = %s 
                AND timestamp BETWEEN %s AND %s
                AND (bids->0->>'price') IS NOT NULL 
                AND (asks->0->>'price') IS NOT NULL
                ORDER BY timestamp;
            """, (symbol, start_ms, end_ms))
            
            print("Fetching records from database...")
            columns = ['timestamp', 'bid_price', 'bid_quantity', 'ask_price', 'ask_quantity']
            data = cur.fetchall()
            print(f"Retrieved {len(data)} records")
            
        print("Converting to DataFrame...")
        df = pd.DataFrame(data, columns=columns)
        if not df.empty:
            # Convert millisecond timestamps to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Convert interval string to pandas frequency string
            freq = sample_interval.lower().replace(' minutes', 'T').replace(' minute', 'T')
            freq = freq.replace('hour', 'H').replace('day', 'D')
            
            # Resample to desired interval
            print(f"Resampling data to {freq} intervals...")
            df = df.resample(freq).agg({
                'bid_price': 'last',
                'bid_quantity': 'last',
                'ask_price': 'last',
                'ask_quantity': 'last'
            }).dropna()
            print(f"Final DataFrame shape: {df.shape}")
            
        return df

    def close(self):
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None 