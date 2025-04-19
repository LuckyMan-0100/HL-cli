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

import backpack
from exec_bridge import ExecutionClient, Side, OrderType

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
    """Order request."""
    id: str
    symbol: str
    side: Side
    qty: Decimal
    price: Optional[Decimal]  # None for market orders
    leverage: int
    timestamp: datetime
    client_order_id: Optional[str] = None

@dataclass
class Fill:
    """Order fill details."""
    order_id: str
    symbol: str
    side: Side
    qty: Decimal
    price: Decimal
    timestamp: datetime
    commission: Decimal
    commission_asset: str

class LiveExecution:
    """Live trading execution interface using C++ bridge."""
    
    def __init__(self, cpp_module_path: str):
        """Initialize with path to C++ execution module."""
        from exec_bridge import ExecutionClient
        
        self.client = ExecutionClient()
        self.client.load_module(cpp_module_path)
        self._active_orders: Dict[str, Order] = {}
        self._fills: Dict[str, Fill] = {}
        self._lock = asyncio.Lock()

    async def send_order(self, order: Order) -> Fill:
        """Submit an order and wait for fill."""
        async with self._lock:
            try:
                # Register order
                self._active_orders[order.id] = order
                
                # Submit via C++ bridge
                if order.price is None:
                    # Market order
                    self.client.send_market_order(
                        symbol=order.symbol,
                        side=order.side == Side.BUY,
                        quantity=float(order.qty),
                        leverage=order.leverage
                    )
                else:
                    # Limit order
                    self.client.send_limit_order(
                        symbol=order.symbol,
                        side=order.side == Side.BUY,
                        quantity=float(order.qty),
                        price=float(order.price),
                        leverage=order.leverage
                    )
                
                # Wait for fill
                fill = await self._wait_for_fill(order.id)
                return fill
                
            except Exception as e:
                logger.error(f"Order execution failed: {e}")
                self._active_orders.pop(order.id, None)
                raise

    async def _wait_for_fill(self, order_id: str, timeout: float = 30.0) -> Fill:
        """Wait for an order to be filled."""
        start = asyncio.get_event_loop().time()
        
        while True:
            if asyncio.get_event_loop().time() - start > timeout:
                # Cancel order on timeout
                await self.cancel_order(order_id)
                raise TimeoutError(f"Order {order_id} not filled within {timeout}s")
                
            # Check if we have a fill
            fill = self._fills.get(order_id)
            if fill is not None:
                return fill
                
            await asyncio.sleep(0.1)  # Avoid tight loop

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an active order."""
        async with self._lock:
            order = self._active_orders.get(order_id)
            if order is None:
                return False
                
            try:
                self.client.cancel_order(order_id)
                self._active_orders.pop(order_id, None)
                return True
            except Exception as e:
                logger.error(f"Failed to cancel order {order_id}: {e}")
                return False

    def get_open_positions(self) -> List[dict]:
        """Get currently open positions."""
        try:
            return self.client.get_positions()
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    def _on_order_update(self, update: dict) -> None:
        """Handle order update from WebSocket."""
        order_id = update["orderId"]
        status = update["status"]
        
        if status == OrderStatus.FILLED:
            # Create fill object
            fill = Fill(
                order_id=order_id,
                symbol=update["symbol"],
                side=Side.BUY if update["side"] == "BUY" else Side.SELL,
                qty=Decimal(str(update["executedQty"])),
                price=Decimal(str(update["avgPrice"])),
                timestamp=datetime.fromtimestamp(update["updateTime"] / 1000),
                commission=Decimal(str(update["commission"])),
                commission_asset=update["commissionAsset"]
            )
            self._fills[order_id] = fill
            self._active_orders.pop(order_id, None)
            
        elif status in (OrderStatus.CANCELED, OrderStatus.REJECTED):
            self._active_orders.pop(order_id, None)

class PaperExecution:
    """Paper trading execution interface."""
    
    def __init__(self):
        self._positions: Dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def send_order(self, order: Order) -> Fill:
        """Simulate order execution."""
        async with self._lock:
            # Simulate fill at current price
            fill = Fill(
                order_id=order.id,
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                price=order.price or Decimal("0"),  # Would need price feed
                timestamp=datetime.utcnow(),
                commission=Decimal("0"),
                commission_asset=order.symbol.split("/")[1]
            )
            
            # Update paper positions
            pos = self._positions.get(order.symbol, {
                "symbol": order.symbol,
                "size": Decimal("0"),
                "entry_price": Decimal("0")
            })
            
            if order.side == Side.BUY:
                pos["size"] += order.qty
            else:
                pos["size"] -= order.qty
                
            pos["entry_price"] = fill.price
            self._positions[order.symbol] = pos
            
            return fill

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel simulated order."""
        return True  # Nothing to cancel in paper trading

    def get_open_positions(self) -> List[dict]:
        """Get paper trading positions."""
        return list(self._positions.values()) 