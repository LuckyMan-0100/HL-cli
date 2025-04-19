from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime

@dataclass
class Trade:
    """Represents a single trade from the exchange."""
    symbol: str
    price: Decimal
    quantity: Decimal
    timestamp: datetime
    side: str  # "buy" or "sell"
    trade_id: str
    is_liquidation: bool = False

@dataclass
class OrderBookLevel:
    """Represents a single price level in the order book."""
    price: Decimal
    quantity: Decimal

@dataclass
class OrderBook:
    """Represents the full order book state."""
    symbol: str
    timestamp: datetime
    bids: Dict[Decimal, Decimal]  # price -> quantity
    asks: Dict[Decimal, Decimal]  # price -> quantity
    last_update_id: int

    @property
    def best_bid(self) -> Optional[OrderBookLevel]:
        """Returns the best bid price and quantity."""
        if not self.bids:
            return None
        price = max(self.bids.keys())
        return OrderBookLevel(price=price, quantity=self.bids[price])

    @property
    def best_ask(self) -> Optional[OrderBookLevel]:
        """Returns the best ask price and quantity."""
        if not self.asks:
            return None
        price = min(self.asks.keys())
        return OrderBookLevel(price=price, quantity=self.asks[price])

    @property
    def mid_price(self) -> Optional[Decimal]:
        """Calculate the mid price between best bid and best ask."""
        best_bid = self.best_bid
        best_ask = self.best_ask
        if best_bid is None or best_ask is None:
            return None
        return (best_bid.price + best_ask.price) / Decimal('2')

    def get_imbalance_1pct(self) -> Optional[Decimal]:
        """Calculate imbalance within 1% of mid price."""
        mid = self.mid_price
        if mid is None:
            return None

        lower_bound = mid * Decimal('0.99')
        upper_bound = mid * Decimal('1.01')

        bid_qty = sum(qty for price, qty in self.bids.items() if price >= lower_bound)
        ask_qty = sum(qty for price, qty in self.asks.items() if price <= upper_bound)

        return bid_qty - ask_qty

    def get_depth_ratio(self) -> Optional[Decimal]:
        """Calculate ratio of total bid depth to total ask depth."""
        total_bid_depth = sum(self.bids.values())
        total_ask_depth = sum(self.asks.values())
        
        if total_ask_depth == 0:
            return None
            
        return total_bid_depth / total_ask_depth

    def get_micro_price(self) -> Optional[Decimal]:
        """Calculate micro price: (bid*ask_qty + ask*bid_qty)/(bid_qty + ask_qty)."""
        best_bid = self.best_bid
        best_ask = self.best_ask
        if best_bid is None or best_ask is None:
            return None

        denominator = best_bid.quantity + best_ask.quantity
        if denominator == 0:
            return None

        return (best_bid.price * best_ask.quantity + best_ask.price * best_bid.quantity) / denominator

@dataclass
class Kline:
    """Represents a candlestick/kline."""
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    interval: str  # e.g., "1m" for 1-minute
    trade_count: int
    closed: bool  # True if the candle is complete 