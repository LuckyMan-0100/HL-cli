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

from config.settings import settings
from .models import Kline, OrderBook, Trade


@dataclass
class Kline:
    timestamp: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal

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

class RingBuffer:
    """Thread-safe ring buffer with efficient window queries."""
    
    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self.buffer = deque(maxlen=max_size)
        self.lock = threading.Lock()
        
    def append(self, item: any) -> None:
        """Add item to buffer in thread-safe manner."""
        with self.lock:
            self.buffer.append(item)
            
    def get_window(self, window_size: int) -> List[any]:
        """Get last N items from buffer."""
        with self.lock:
            return list(self.buffer)[-window_size:]
            
    def get_latest(self) -> Optional[any]:
        """Get most recent item."""
        with self.lock:
            return self.buffer[-1] if self.buffer else None

class MemoryStore:
    """Thread-safe in-memory store for market data."""
    
    def __init__(
        self,
        kline_buffer_size: int = 10000,
        orderbook_buffer_size: int = 1000,
        trade_buffer_size: int = 10000
    ):
        # Kline buffers per symbol and timeframe
        self._klines: Dict[str, Dict[str, RingBuffer]] = {}
        self._kline_buffer_size = kline_buffer_size
        
        # Order book buffers per symbol
        self._orderbooks: Dict[str, RingBuffer] = {}
        self._orderbook_buffer_size = orderbook_buffer_size
        
        # Trade buffers per symbol
        self._trades: Dict[str, RingBuffer] = {}
        self._trade_buffer_size = trade_buffer_size
        
        # Latest prices per symbol
        self._latest_prices: Dict[str, Decimal] = {}
        self._price_lock = threading.Lock()
        
        # Latest order book state per symbol
        self._latest_orderbooks: Dict[str, OrderBook] = {}
        self._orderbook_lock = threading.Lock()
        
    def update_kline(self, symbol: str, timeframe: str, kline: Kline) -> None:
        """Update kline data."""
        if symbol not in self._klines:
            self._klines[symbol] = {}
            
        if timeframe not in self._klines[symbol]:
            self._klines[symbol][timeframe] = RingBuffer(self._kline_buffer_size)
            
        self._klines[symbol][timeframe].append(kline)
        
        # Update latest price
        with self._price_lock:
            self._latest_prices[symbol] = kline.close
            
    def get_klines(
        self,
        symbol: str,
        timeframe: str,
        window_size: int
    ) -> List[Kline]:
        """Get last N klines for symbol and timeframe."""
        if symbol not in self._klines or timeframe not in self._klines[symbol]:
            return []
            
        return self._klines[symbol][timeframe].get_window(window_size)
        
    def update_orderbook(self, symbol: str, orderbook: OrderBook) -> None:
        """Update order book state."""
        if symbol not in self._orderbooks:
            self._orderbooks[symbol] = RingBuffer(self._orderbook_buffer_size)
            
        self._orderbooks[symbol].append(orderbook)
        
        # Update latest snapshot
        with self._orderbook_lock:
            self._latest_orderbooks[symbol] = orderbook
            
    def get_orderbook_snapshot(self, symbol: str) -> Optional[OrderBook]:
        """Get latest order book snapshot."""
        with self._orderbook_lock:
            return self._latest_orderbooks.get(symbol)
            
    def get_orderbook_history(
        self,
        symbol: str,
        window_size: int
    ) -> List[OrderBook]:
        """Get historical order book snapshots."""
        if symbol not in self._orderbooks:
            return []
            
        return self._orderbooks[symbol].get_window(window_size)
        
    def get_latest_price(self, symbol: str) -> Optional[Decimal]:
        """Get latest price for symbol."""
        with self._price_lock:
            return self._latest_prices.get(symbol)
            
    def get_mid_price(self, symbol: str) -> Optional[Decimal]:
        """Calculate mid price from latest order book."""
        ob = self.get_orderbook_snapshot(symbol)
        if not ob or not ob.bids or not ob.asks:
            return None
            
        return (ob.bids[0].price + ob.asks[0].price) / Decimal('2')
        
    def get_weighted_mid_price(
        self,
        symbol: str,
        depth: int = 10
    ) -> Optional[Decimal]:
        """Calculate volume-weighted mid price."""
        ob = self.get_orderbook_snapshot(symbol)
        if not ob:
            return None
            
        bid_volume = Decimal('0')
        bid_value = Decimal('0')
        for level in ob.bids[:depth]:
            bid_volume += level.quantity
            bid_value += level.price * level.quantity
            
        ask_volume = Decimal('0')
        ask_value = Decimal('0')
        for level in ob.asks[:depth]:
            ask_volume += level.quantity
            ask_value += level.price * level.quantity
            
        if bid_volume == 0 or ask_volume == 0:
            return None
            
        weighted_bid = bid_value / bid_volume
        weighted_ask = ask_value / ask_volume
        return (weighted_bid + weighted_ask) / Decimal('2')
        
    def get_order_book_imbalance(
        self,
        symbol: str,
        depth: int = 10
    ) -> Optional[Decimal]:
        """Calculate order book imbalance."""
        ob = self.get_orderbook_snapshot(symbol)
        if not ob:
            return None
            
        bid_volume = sum(level.quantity for level in ob.bids[:depth])
        ask_volume = sum(level.quantity for level in ob.asks[:depth])
        
        total_volume = bid_volume + ask_volume
        if total_volume == 0:
            return Decimal('0')
            
        return (bid_volume - ask_volume) / total_volume
        
    def clear_old_data(self, max_age_seconds: float = 3600) -> None:
        """Clear data older than specified age."""
        current_time = time.time()
        
        def _is_recent(item: Union[Kline, OrderBook], max_age: float) -> bool:
            return (current_time - item.timestamp / 1000) <= max_age
        
        for symbol in list(self._klines.keys()):
            for timeframe in list(self._klines[symbol].keys()):
                buffer = self._klines[symbol][timeframe]
                with buffer.lock:
                    buffer.buffer = deque(
                        [k for k in buffer.buffer if _is_recent(k, max_age_seconds)],
                        maxlen=buffer.max_size
                    )
                    
        for symbol in list(self._orderbooks.keys()):
            buffer = self._orderbooks[symbol]
            with buffer.lock:
                buffer.buffer = deque(
                    [ob for ob in buffer.buffer if _is_recent(ob, max_age_seconds)],
                    maxlen=buffer.max_size
                )


class KlineMemoryStore:
    """Thread-safe store for kline data per symbol and interval."""
    
    def __init__(self):
        self._klines: Dict[str, Dict[str, Deque[Kline]]] = {}  # symbol -> interval -> klines
        self._lock = threading.RLock()
        self.max_klines = settings.trading.kline_memory_rows

    def update(self, kline: Kline) -> None:
        """Update kline data for a symbol and interval."""
        with self._lock:
            if kline.symbol not in self._klines:
                self._klines[kline.symbol] = {}
            
            if kline.interval not in self._klines[kline.symbol]:
                self._klines[kline.symbol][kline.interval] = deque(maxlen=self.max_klines)
            
            self._klines[kline.symbol][kline.interval].append(kline)

    def get_latest(self, symbol: str, interval: str) -> Optional[Kline]:
        """Get the most recent kline for a symbol and interval."""
        with self._lock:
            try:
                return self._klines[symbol][interval][-1]
            except (KeyError, IndexError):
                return None

    def get_last_n(self, symbol: str, interval: str, n: int) -> List[Kline]:
        """Get the last N klines for a symbol and interval."""
        with self._lock:
            try:
                klines = self._klines[symbol][interval]
                return list(klines)[-n:]
            except (KeyError, IndexError):
                return []


class OrderBookMemoryStore:
    """Thread-safe store for latest order book state."""
    
    def __init__(self):
        self._snapshots: Dict[str, OrderBook] = {}  # symbol -> latest snapshot
        self._lock = threading.RLock()

    def update(self, orderbook: OrderBook) -> None:
        """Update the order book snapshot for a symbol."""
        with self._lock:
            self._snapshots[orderbook.symbol] = orderbook

    def get_snapshot(self, symbol: str) -> Optional[OrderBook]:
        """Get the latest order book snapshot for a symbol."""
        with self._lock:
            return self._snapshots.get(symbol)

    def get_mid_price(self, symbol: str) -> Optional[Decimal]:
        """Get the current mid price for a symbol."""
        snapshot = self.get_snapshot(symbol)
        if snapshot:
            return snapshot.mid_price
        return None

    def get_spread(self, symbol: str) -> Optional[Decimal]:
        """Get the current bid-ask spread for a symbol."""
        snapshot = self.get_snapshot(symbol)
        if snapshot:
            best_bid = snapshot.best_bid
            best_ask = snapshot.best_ask
            if best_bid and best_ask:
                return best_ask.price - best_bid.price
        return None


class TradeBuffer:
    """Thread-safe circular buffer for recent trades."""
    
    def __init__(self, max_size: int = settings.trading.trade_memory_rows):
        self._trades: Dict[str, Deque[Trade]] = {}  # symbol -> trades
        self._lock = threading.RLock()
        self.max_size = max_size

    def add(self, trade: Trade) -> None:
        """Add a trade to the buffer."""
        with self._lock:
            if trade.symbol not in self._trades:
                self._trades[trade.symbol] = deque(maxlen=self.max_size)
            self._trades[trade.symbol].append(trade)

    def get_last_n(self, symbol: str, n: int) -> List[Trade]:
        """Get the last N trades for a symbol."""
        with self._lock:
            try:
                trades = self._trades[symbol]
                return list(trades)[-n:]
            except (KeyError, IndexError):
                return []

    def get_latest(self, symbol: str) -> Optional[Trade]:
        """Get the most recent trade for a symbol."""
        with self._lock:
            try:
                return self._trades[symbol][-1]
            except (KeyError, IndexError):
                return None