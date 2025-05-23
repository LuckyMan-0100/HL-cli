"""
Execution interface for live trading on Backpack Exchange.
Handles order execution, monitoring, and management.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, List, Tuple
import uuid
import random
from config.settings import settings
from data_ingestion.redis_client import RedisQuoteClient  # imported for type

logger = logging.getLogger(__name__)

class Side(str, Enum):
    """Order side."""
    BUY = "buy"
    SELL = "sell"

class OrderStatus(str, Enum):
    """Order status."""
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"

@dataclass
class Order:
    """Trading order details."""
    id: str
    symbol: str
    side: str  # "buy" or "sell"
    qty: float
    price: Optional[float] = None  # None for market orders
    leverage: float = 1.0
    timestamp: datetime = datetime.now()
    client_order_id: Optional[str] = None

@dataclass
class Fill:
    """Order fill details."""
    id: str
    price: float
    qty: float
    side: str
    timestamp: datetime
    fees: float = 0.0

class ExecutionInterface:
    """Base class for execution interfaces."""
    
    async def send_order(self, order: Order) -> Optional[Fill]:
        """Send order to exchange."""
        raise NotImplementedError
        
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        raise NotImplementedError

    def get_open_positions(self) -> List[dict]:
        """Get currently open positions."""
        return []

class LiveExecution(ExecutionInterface):
    """Live trading execution interface."""
    
    def __init__(self, cpp_exec_path: str):
        self.cpp_exec_path = cpp_exec_path
        logger.info("Live execution not implemented, using paper trading")
        
    async def send_order(self, order: Order) -> Optional[Fill]:
        """Not implemented for paper trading."""
        return None
        
    async def cancel_order(self, order_id: str) -> bool:
        """Not implemented for paper trading."""
        return False

class PaperExecution(ExecutionInterface):
    """Paper trading execution interface using real market data."""
    
    def __init__(self, quote_client: RedisQuoteClient):
        # Use the shared RedisQuoteClient from the strategy loop
        self.quote_client = quote_client
        self.position = 0.0
        self.cash = settings.trading.initial_capital
        
    async def send_order(self, order: Order) -> Optional[Fill]:
        """Execute order using real market data."""
        try:
            # Get real-time quote from Redis
            quote = await self.quote_client.get_quote()
            if not quote or quote['bidPrice'] == 0 or quote['askPrice'] == 0:
                logger.warning("No valid quote data available for paper trade")
                return None
                
            # Use actual market prices
            fill_price = quote['askPrice'] if order.side == "buy" else quote['bidPrice']
            
            # Apply exchange fees (using real Hyperliquid fee structure)
            fee_rate = settings.trading.taker_fee_rate
            fees = order.qty * fill_price * fee_rate
            
            # Update position and cash
            if order.side == "buy":
                self.position += order.qty
                self.cash -= (order.qty * fill_price + fees)
            else:
                self.position -= order.qty
                self.cash += (order.qty * fill_price - fees)
                
            fill = Fill(
                id=str(uuid.uuid4()),
                price=fill_price,
                qty=order.qty,
                side=order.side,
                timestamp=datetime.now(),
                fees=fees
            )
            
            logger.info(f"Paper trade executed: {order.side} {order.qty} @ {fill_price:.2f}")
            logger.info(f"Position: {self.position:.3f}, Cash: ${self.cash:.2f}")
            
            return fill
            
        except Exception as e:
            logger.error(f"Error in paper execution: {e}")
            return None
            
    async def cancel_order(self, order_id: str) -> bool:
        """Simulate order cancellation."""
        return True  # Always succeed in paper trading

    def get_position(self, symbol: str) -> float:
        """Return current paper trading position for the given symbol."""
        return self.position

    def get_open_positions(self) -> List[dict]:
        """Get paper trading positions."""
        if self.position != 0:
            # Get latest quote for mark price
            quote = asyncio.run(self.quote_client.get_quote())
            mark_price = (quote['bidPrice'] + quote['askPrice']) / 2 if quote else 0
            
            return [{
                'symbol': settings.trading.symbol,
                'size': self.position,
                'mark_price': mark_price,
                'unrealized_pnl': self.position * (mark_price - self.last_fill_price) if hasattr(self, 'last_fill_price') else 0.0
            }]
        return []

    def _on_order_update(self, update: dict) -> None:
        """Handle order update from WebSocket."""
        order_id = update["orderId"]
        status = update["status"]
        
        if status == OrderStatus.FILLED:
            # Create fill object
            fill = Fill(
                id=order_id,
                price=float(update["avgPrice"]),
                qty=float(update["executedQty"]),
                side=Side.BUY.value if update["side"] == "BUY" else Side.SELL.value,
                timestamp=datetime.fromtimestamp(update["updateTime"] / 1000),
                fees=float(update["commission"])
            )
            # Note: The fees are already included in the fill price
            
        elif status in (OrderStatus.CANCELED, OrderStatus.REJECTED):
            # Handle order cancellation or rejection
            pass

    def get_open_positions(self) -> List[dict]:
        """Get paper trading positions."""
        return []  # Paper trading does not have open positions

    def _on_order_update(self, update: dict) -> None:
        """Handle order update from WebSocket."""
        order_id = update["orderId"]
        status = update["status"]
        
        if status == OrderStatus.FILLED:
            # Create fill object
            fill = Fill(
                id=order_id,
                price=float(update["avgPrice"]),
                qty=float(update["executedQty"]),
                side=Side.BUY.value if update["side"] == "BUY" else Side.SELL.value,
                timestamp=datetime.fromtimestamp(update["updateTime"] / 1000),
                fees=float(update["commission"])
            )
            # Note: The fees are already included in the fill price
            
        elif status in (OrderStatus.CANCELED, OrderStatus.REJECTED):
            # Handle order cancellation or rejection
            pass 