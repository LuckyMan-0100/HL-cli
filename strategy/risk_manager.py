"""
Risk management module for controlling position sizes and exposure.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional

logger = logging.getLogger(__name__)

@dataclass
class Position:
    symbol: str
    size: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    unrealized_pnl: Decimal = Decimal('0')
    realized_pnl: Decimal = Decimal('0')

@dataclass
class RiskLimits:
    max_position_value: Decimal = Decimal('10000')  # Max position size in quote currency
    max_daily_loss: Decimal = Decimal('1000')  # Max daily loss in quote currency
    max_drawdown: Decimal = Decimal('2000')  # Max drawdown from peak equity
    max_leverage: int = 20
    consecutive_loss_limit: int = 3

@dataclass
class RiskMetrics:
    daily_pnl: Decimal = Decimal('0')
    peak_equity: Decimal = Decimal('10000')  # Starting equity
    current_equity: Decimal = Decimal('10000')
    consecutive_losses: int = 0
    positions: Dict[str, Position] = field(default_factory=dict)

class RiskManager:
    def __init__(self, limits: Optional[RiskLimits] = None):
        self.limits = limits or RiskLimits()
        self.metrics = RiskMetrics()
        
    def can_trade(self) -> bool:
        """Check if trading is allowed based on risk limits."""
        # Check consecutive losses
        if self.metrics.consecutive_losses >= self.limits.consecutive_loss_limit:
            logger.warning(f"Hit consecutive loss limit: {self.metrics.consecutive_losses}")
            return False
            
        # Check daily loss limit
        if self.metrics.daily_pnl <= -self.limits.max_daily_loss:
            logger.warning(f"Hit daily loss limit: {self.metrics.daily_pnl}")
            return False
            
        # Check drawdown
        drawdown = self.metrics.peak_equity - self.metrics.current_equity
        if drawdown >= self.limits.max_drawdown:
            logger.warning(f"Hit max drawdown limit: {drawdown}")
            return False
            
        return True
        
    def update_position(
        self,
        symbol: str,
        size: Decimal,
        entry_price: Decimal,
        stop_loss: Decimal,
        current_price: Optional[Decimal] = None
    ) -> bool:
        """Update or create a position."""
        # Calculate position value
        position_value = size * entry_price
        
        # Check position size limit
        if position_value > self.limits.max_position_value:
            logger.warning(f"Position value {position_value} exceeds limit {self.limits.max_position_value}")
            return False
            
        # Create or update position
        position = Position(
            symbol=symbol,
            size=size,
            entry_price=entry_price,
            stop_loss=stop_loss
        )
        
        # Update unrealized PnL if we have current price
        if current_price:
            position.unrealized_pnl = (current_price - entry_price) * size
            
        self.metrics.positions[symbol] = position
        return True
        
    def close_position(
        self,
        symbol: str,
        exit_price: Decimal,
        size: Optional[Decimal] = None
    ) -> None:
        """Close a position and update metrics."""
        position = self.metrics.positions.get(symbol)
        if not position:
            logger.warning(f"No position found for {symbol}")
            return
            
        # Handle partial closes
        close_size = size or position.size
        if close_size > position.size:
            logger.warning(f"Close size {close_size} > position size {position.size}")
            close_size = position.size
            
        # Calculate PnL
        pnl = (exit_price - position.entry_price) * close_size
        
        # Update metrics
        self.metrics.daily_pnl += pnl
        self.metrics.current_equity += pnl
        self.metrics.peak_equity = max(self.metrics.peak_equity, self.metrics.current_equity)
        
        # Update consecutive losses
        if pnl < 0:
            self.metrics.consecutive_losses += 1
        else:
            self.metrics.consecutive_losses = 0
            
        # Update or remove position
        if close_size == position.size:
            del self.metrics.positions[symbol]
        else:
            position.size -= close_size
            
        logger.info(
            f"Closed position {symbol}: "
            f"Size={close_size}, "
            f"PnL={pnl}, "
            f"Daily PnL={self.metrics.daily_pnl}"
        )
        
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for a symbol."""
        return self.metrics.positions.get(symbol)
        
    def get_total_exposure(self) -> Decimal:
        """Calculate total exposure across all positions."""
        return sum(
            abs(pos.size * pos.entry_price)
            for pos in self.metrics.positions.values()
        )
        
    def reset_daily_metrics(self) -> None:
        """Reset daily tracking metrics."""
        self.metrics.daily_pnl = Decimal('0')
        self.metrics.consecutive_losses = 0 