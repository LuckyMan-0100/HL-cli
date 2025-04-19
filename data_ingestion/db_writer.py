import logging
from typing import List, Optional
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime
from decimal import Decimal
import json

from config.settings import settings
from .models import Trade, OrderBook, Kline

logger = logging.getLogger(__name__)

class PostgresWriter:
    """Handles writing market data to PostgreSQL database."""

    def __init__(self):
        self.dsn = settings.database.dsn
        self._conn = None
        self._ensure_tables()

    def _get_conn(self):
        """Get a database connection, creating it if necessary."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.dsn)
        return self._conn

    def _ensure_tables(self):
        """Create necessary tables if they don't exist."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            # Trades table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    price NUMERIC NOT NULL,
                    quantity NUMERIC NOT NULL,
                    side TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    is_liquidation BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_trades_symbol_timestamp ON trades(symbol, timestamp);
            """)

            # Order book snapshots table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                    id SERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    last_update_id BIGINT NOT NULL,
                    bids JSONB NOT NULL,
                    asks JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, last_update_id)
                );
                CREATE INDEX IF NOT EXISTS idx_ob_symbol_timestamp 
                ON orderbook_snapshots(symbol, timestamp);
            """)

            # Klines table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS klines (
                    symbol TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    interval TEXT NOT NULL,
                    open NUMERIC NOT NULL,
                    high NUMERIC NOT NULL,
                    low NUMERIC NOT NULL,
                    close NUMERIC NOT NULL,
                    volume NUMERIC NOT NULL,
                    trade_count INTEGER NOT NULL,
                    closed BOOLEAN NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (symbol, interval, timestamp)
                );
                CREATE INDEX IF NOT EXISTS idx_klines_lookup 
                ON klines(symbol, interval, timestamp DESC);
            """)

            conn.commit()

    def write_trade(self, trade: Trade):
        """Write a single trade to the database."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO trades (
                    trade_id, symbol, price, quantity, side, 
                    timestamp, is_liquidation
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (trade_id) DO NOTHING
            """, (
                trade.trade_id, trade.symbol, str(trade.price), 
                str(trade.quantity), trade.side, trade.timestamp,
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
                 t.side, t.timestamp, t.is_liquidation)
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
            bids = {str(k): str(v) for k, v in orderbook.bids.items()}
            asks = {str(k): str(v) for k, v in orderbook.asks.items()}
            
            cur.execute("""
                INSERT INTO orderbook_snapshots (
                    symbol, timestamp, last_update_id, bids, asks
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (symbol, last_update_id) DO UPDATE
                SET timestamp = EXCLUDED.timestamp,
                    bids = EXCLUDED.bids,
                    asks = EXCLUDED.asks
            """, (
                orderbook.symbol,
                orderbook.timestamp,
                orderbook.last_update_id,
                json.dumps(bids),
                json.dumps(asks)
            ))
            conn.commit()

    def write_kline(self, kline: Kline):
        """Write a single kline/candlestick to the database."""
        conn = self._get_conn()
        with conn.cursor() as cur:
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
                kline.symbol, kline.timestamp, kline.interval,
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
                    timestamp=row[1],
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

    def close(self):
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None 