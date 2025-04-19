"""
Risk management guards and circuit breakers.
"""

import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional

import backpack
from data_ingestion.memory_store import MemoryStore

logger = logging.getLogger(__name__)

@dataclass
class CircuitBreakerConfig:
    # Drawdown limits
    max_drawdown_pct: float = 0.05  # 5% max drawdown
    max_daily_loss_pct: float = 0.02  # 2% max daily loss
    
    # Volume limits
    max_hourly_volume: Decimal = Decimal('100000')  # Max notional volume per hour
    max_daily_volume: Decimal = Decimal('1000000')  # Max notional volume per day
    
    # Position limits
    max_position_notional: Decimal = Decimal('50000')  # Max position size
    max_leverage: int = 20  # Max leverage
    
    # Trade frequency limits
    min_trade_interval_seconds: int = 30  # Minimum time between trades
    max_trades_per_hour: int = 120  # Maximum number of trades per hour
    
    # Market impact limits
    max_spread_bps: int = 20  # Maximum spread in basis points
    min_book_depth_notional: Decimal = Decimal('100000')  # Minimum order book depth

class CircuitBreaker:
    """Circuit breaker implementation with multiple triggers."""
    
    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
        memory_store: Optional[MemoryStore] = None
    ):
        self.config = config or CircuitBreakerConfig()
        self.memory_store = memory_store
        self.exchange_client = backpack.create_client()
        
        # State tracking
        self._is_triggered = False
        self._trigger_reason = None
        self._last_trade_time = 0
        self._hourly_volume = Decimal('0')
        self._daily_volume = Decimal('0')
        self._hourly_trades = 0
        self._last_hour_reset = time.time()
        self._last_day_reset = time.time()
        
        # Account tracking
        self._initial_equity = None
        self._peak_equity = None
        self._current_equity = None
        self._daily_starting_equity = None
        
    async def initialize(self):
        """Initialize circuit breaker state."""
        # Fetch initial account state
        account = await self.exchange_client.get_account()
        self._initial_equity = Decimal(str(account['totalEquityValue']))
        self._peak_equity = self._initial_equity
        self._current_equity = self._initial_equity
        self._daily_starting_equity = self._initial_equity
        
    def is_triggered(self) -> bool:
        """Check if circuit breaker is triggered."""
        return self._is_triggered
        
    def get_trigger_reason(self) -> Optional[str]:
        """Get reason for circuit breaker trigger."""
        return self._trigger_reason
        
    async def check_limits(self, symbol: str, size: Decimal, price: Decimal) -> bool:
        """
        Check if proposed trade violates any limits.
        Returns True if trade is allowed, False if it should be blocked.
        """
        # Update account state
        await self._update_account_state()
        
        # Check if already triggered
        if self.is_triggered():
            return False
            
        # Calculate trade notional
        notional = size * price
        
        # Check drawdown limits
        drawdown_pct = (self._peak_equity - self._current_equity) / self._peak_equity
        if drawdown_pct > self.config.max_drawdown_pct:
            self._trigger_circuit_breaker(
                f"Max drawdown exceeded: {drawdown_pct:.2%} > {self.config.max_drawdown_pct:.2%}"
            )
            return False
            
        daily_pnl_pct = (self._current_equity - self._daily_starting_equity) / self._daily_starting_equity
        if daily_pnl_pct < -self.config.max_daily_loss_pct:
            self._trigger_circuit_breaker(
                f"Max daily loss exceeded: {daily_pnl_pct:.2%} > -{self.config.max_daily_loss_pct:.2%}"
            )
            return False
            
        # Check volume limits
        if self._hourly_volume + notional > self.config.max_hourly_volume:
            self._trigger_circuit_breaker(
                f"Hourly volume limit exceeded: {self._hourly_volume + notional} > {self.config.max_hourly_volume}"
            )
            return False
            
        if self._daily_volume + notional > self.config.max_daily_volume:
            self._trigger_circuit_breaker(
                f"Daily volume limit exceeded: {self._daily_volume + notional} > {self.config.max_daily_volume}"
            )
            return False
            
        # Check trade frequency
        current_time = time.time()
        if current_time - self._last_trade_time < self.config.min_trade_interval_seconds:
            return False
            
        if self._hourly_trades >= self.config.max_trades_per_hour:
            return False
            
        # Check market impact
        if not await self._check_market_impact(symbol, size, price):
            return False
            
        return True
        
    def record_trade(self, notional: Decimal):
        """Record trade for volume tracking."""
        current_time = time.time()
        
        # Update hourly metrics
        if current_time - self._last_hour_reset >= 3600:
            self._hourly_volume = Decimal('0')
            self._hourly_trades = 0
            self._last_hour_reset = current_time
            
        # Update daily metrics
        if current_time - self._last_day_reset >= 86400:
            self._daily_volume = Decimal('0')
            self._last_day_reset = current_time
            self._daily_starting_equity = self._current_equity
            
        self._hourly_volume += notional
        self._daily_volume += notional
        self._hourly_trades += 1
        self._last_trade_time = current_time
        
    async def _update_account_state(self):
        """Update account equity metrics."""
        account = await self.exchange_client.get_account()
        self._current_equity = Decimal(str(account['totalEquityValue']))
        self._peak_equity = max(self._peak_equity, self._current_equity)
        
    async def _check_market_impact(self, symbol: str, size: Decimal, price: Decimal) -> bool:
        """Check if trade would have too much market impact."""
        if not self.memory_store:
            return True
            
        # Check spread
        ob = self.memory_store.get_orderbook_snapshot(symbol)
        if not ob or not ob.bids or not ob.asks:
            return False
            
        spread = (ob.asks[0].price - ob.bids[0].price) / ob.bids[0].price
        if spread > self.config.max_spread_bps / 10000:
            return False
            
        # Check book depth
        side_depth = Decimal('0')
        if size > 0:  # Buy
            for level in ob.asks:
                side_depth += level.price * level.quantity
                if side_depth >= self.config.min_book_depth_notional:
                    break
        else:  # Sell
            for level in ob.bids:
                side_depth += level.price * level.quantity
                if side_depth >= self.config.min_book_depth_notional:
                    break
                    
        return side_depth >= self.config.min_book_depth_notional
        
    def _trigger_circuit_breaker(self, reason: str):
        """Trigger circuit breaker with reason."""
        self._is_triggered = True
        self._trigger_reason = reason
        logger.warning(f"Circuit breaker triggered: {reason}")
        
    def reset(self):
        """Reset circuit breaker state."""
        self._is_triggered = False
        self._trigger_reason = None 