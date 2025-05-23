"""Thread‑safe, in‑memory data stores used by the WebSocket client and
strategy loop.  These avoid hitting Postgres for every tick while still
providing a bounded, O(1) eviction structure."""

from __future__ import annotations

from collections import deque
from threading import RLock
from typing import Deque, List, Dict, Optional, Union
from dataclasses import dataclass
from decimal import Decimal
import time
import threading
from datetime import datetime
import json
import redis
import logging
import psycopg2
from psycopg2.extras import RealDictCursor

from config.settings import settings

logger = logging.getLogger(__name__)

@dataclass
class Kline:
    timestamp: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    interval: str = "1m"
    symbol: str = ""

@dataclass
class OrderBookLevel:
    """Single level in the order book."""
    price: Decimal
    quantity: Decimal

@dataclass
class OrderBook:
    """Full order book snapshot."""
    symbol: str
    timestamp: datetime
    bids: List[OrderBookLevel]  # Sorted best to worst
    asks: List[OrderBookLevel]  # Sorted best to worst
    last_update_id: int

    @property
    def mid_price(self) -> Optional[Decimal]:
        """Calculate mid price from best bid/ask."""
        if not self.bids or not self.asks:
            return None
        return (self.bids[0].price + self.asks[0].price) / Decimal('2')

    @property
    def spread(self) -> Optional[Decimal]:
        """Calculate bid-ask spread."""
        if not self.bids or not self.asks:
            return None
        return self.asks[0].price - self.bids[0].price

@dataclass
class Trade:
    """Market trade."""
    symbol: str
    timestamp: datetime
    price: Decimal
    quantity: Decimal
    is_buyer_maker: bool

class RingBuffer:
    """Fixed-size ring buffer."""
    
    def __init__(self, size: int):
        self.size = size
        self.data: Deque = deque(maxlen=size)
        
    def append(self, item: any) -> None:
        """Add item to buffer."""
        self.data.append(item)
        
    def get_all(self) -> List[any]:
        """Get all items in buffer."""
        return list(self.data)
        
    def get_last_n(self, n: int) -> List[any]:
        """Get last n items from buffer."""
        return list(self.data)[-n:]
        
    def clear(self) -> None:
        """Clear all items from buffer."""
        self.data.clear()
        
    def __len__(self) -> int:
        return len(self.data)

class KlineMemoryStore:
    """Thread-safe in-memory store for kline data."""
    
    def __init__(self):
        self.max_klines = settings.trading.kline_memory_rows
        self.klines: Dict[str, Dict[str, RingBuffer]] = {}
        self.lock = threading.Lock()
        self.dsn = settings.database.dsn
        
    def _get_db_connection(self):
        """Get a connection to the PostgreSQL database."""
        return psycopg2.connect(self.dsn)
        
    def update(self, kline: Kline) -> None:
        """Update kline data in memory store."""
        with self.lock:
            if kline.symbol not in self.klines:
                self.klines[kline.symbol] = {}
                
            if kline.interval not in self.klines[kline.symbol]:
                self.klines[kline.symbol][kline.interval] = RingBuffer(self.max_klines)
                
            self.klines[kline.symbol][kline.interval].append(kline)
            
    def get_latest(self, symbol: str, interval: str) -> Optional[Kline]:
        """Get latest kline from PostgreSQL."""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT * FROM klines 
                        WHERE symbol = %s AND interval = %s
                        ORDER BY timestamp DESC 
                        LIMIT 1
                    """, (symbol, interval))
                    
                    row = cur.fetchone()
                    if not row:
                        return None
                        
                    return Kline(
                        timestamp=row['timestamp'],
                        open=Decimal(str(row['open'])),
                        high=Decimal(str(row['high'])),
                        low=Decimal(str(row['low'])),
                        close=Decimal(str(row['close'])),
                        volume=Decimal(str(row['volume'])),
                        quote_volume=row['volume'] * row['close'],  # Calculate quote volume
                        interval=interval,
                        symbol=symbol
                    )
                    
        except Exception as e:
            logger.error(f"Error getting latest kline from PostgreSQL: {e}")
            return None
            
    def get_last_n(self, symbol: str, interval: str, n: int) -> List[Kline]:
        """Get last N klines from in-memory store."""
        with self.lock:
            if symbol in self.klines and interval in self.klines[symbol]:
                return self.klines[symbol][interval].get_last_n(n)
            return []

class OrderBookMemoryStore:
    """Thread-safe in-memory store for order book data."""
    
    def __init__(self):
        self.max_snapshots = settings.trading.orderbook_memory_rows
        self.orderbooks: Dict[str, RingBuffer] = {}
        self.lock = threading.Lock()
        
    def update(self, orderbook: OrderBook) -> None:
        """Update order book data."""
        with self.lock:
            if orderbook.symbol not in self.orderbooks:
                self.orderbooks[orderbook.symbol] = RingBuffer(self.max_snapshots)
            self.orderbooks[orderbook.symbol].append(orderbook)
            
    def get_snapshot(self, symbol: str) -> Optional[OrderBook]:
        """Get latest order book snapshot from in-memory store."""
        with self.lock:
            if symbol not in self.orderbooks:
                return None
            last_items = self.orderbooks[symbol].get_last_n(1)
            return last_items[0] if last_items else None
            
    def get_mid_price(self, symbol: str) -> Optional[Decimal]:
        """Get mid price from latest order book."""
        snapshot = self.get_snapshot(symbol)
        if not snapshot:
            return None
        return snapshot.mid_price
            
    def get_spread(self, symbol: str) -> Optional[Decimal]:
        """Get spread from latest order book."""
        snapshot = self.get_snapshot(symbol)
        if not snapshot:
            return None
        return snapshot.spread

    def get_last_n(self, symbol: str, interval: str, n: int) -> List[Kline]:
        """Get last N klines from in-memory store."""
        with self.lock:
            if symbol in self.klines and interval in self.klines[symbol]:
                return self.klines[symbol][interval].get_last_n(n)
            return []

class TradeBuffer:
    """Thread-safe buffer for recent trades."""
    
    def __init__(self):
        self.max_trades = settings.trading.trade_memory_rows
        self.trades: Dict[str, RingBuffer] = {}
        self.lock = threading.Lock()
        
    def add(self, trade: Trade) -> None:
        """Add trade to buffer."""
        with self.lock:
            if trade.symbol not in self.trades:
                self.trades[trade.symbol] = RingBuffer(self.max_trades)
            self.trades[trade.symbol].append(trade)
            
    def get_last_n(self, symbol: str, n: int) -> List[Trade]:
        """Get last N trades for symbol."""
        with self.lock:
            if symbol not in self.trades:
                return []
            return self.trades[symbol].get_window(n)
            
    def get_latest(self, symbol: str) -> Optional[Trade]:
        """Get latest trade for symbol."""
        with self.lock:
            if symbol not in self.trades:
                return None
            return self.trades[symbol].get_latest()