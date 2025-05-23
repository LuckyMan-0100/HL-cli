"""Test utilities and mock objects for testing."""

from typing import Dict, List
from decimal import Decimal

class MockOrderBook:
    """Mock orderbook for testing purposes."""
    
    def __init__(self, bids: List[Dict], asks: List[Dict]):
        """Initialize mock orderbook with test data."""
        self.bids = [
            {"price": Decimal(str(price)), "size": Decimal(str(size))}
            for price, size in bids
        ]
        self.asks = [
            {"price": Decimal(str(price)), "size": Decimal(str(size))}
            for price, size in asks
        ]
    
    def get_bids(self) -> List[Dict]:
        """Get bid side of the orderbook."""
        return self.bids
    
    def get_asks(self) -> List[Dict]:
        """Get ask side of the orderbook."""
        return self.asks
    
    def get_mid_price(self) -> Decimal:
        """Calculate mid price from best bid/ask."""
        if not self.bids or not self.asks:
            return Decimal('0')
        return (self.bids[0]["price"] + self.asks[0]["price"]) / Decimal('2') 