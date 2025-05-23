"""
Risk management module implementing:
• Circuit-breaker logic
• Position-correlation checks
• Drawdown monitoring (multi-level)
• General risk-limit enforcement
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
import numpy as np
from prometheus_client import Counter, Gauge
from monitoring.metrics import (
    risk_limit_breaches,
    drawdown_gauge,
    circuit_breaker_trips,
)

from config.risk_management.guards import CircuitBreaker, CircuitBreakerConfig
from data_ingestion.memory_store import KlineMemoryStore, OrderBookMemoryStore, TradeBuffer

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
    # Core risk limits
    max_position_notional: float = 1000.0  # Max position size in quote currency
    max_daily_loss: float = 10.0  # Max daily loss in quote currency
    max_drawdown: float = 0.02  # Max drawdown from peak equity (2%)
    max_leverage: int = 3  # Maximum allowed leverage
    
    # Multi-level drawdown thresholds
    drawdown_levels: Dict[str, float] = field(default_factory=lambda: {
        "L1": 0.005,  # 0.5% - Warning
        "L2": 0.01,   # 1.0% - Reduce position
        "L3": 0.015   # 1.5% - Close positions
    })
    
    # Circuit breaker parameters
    circuit_breaker_pct: float = 0.01  # 1% price move trigger
    circuit_breaker_cooldown: int = 300  # 5 minutes cooldown
    
    # Position management
    max_position_duration: int = 3600  # 1 hour max hold time
    position_correlation_threshold: float = 0.7  # Max allowed correlation
    
    # Volatility controls
    volatility_scale_factor: float = 1.0  # Position sizing scalar
    max_volatility: float = 0.02  # Maximum allowed volatility (2%)

@dataclass
class RiskMetrics:
    daily_pnl: Decimal = Decimal('0')
    peak_equity: Decimal = Decimal('10000')  # Starting equity
    current_equity: Decimal = Decimal('10000')
    consecutive_losses: int = 0
    positions: Dict[str, Position] = field(default_factory=dict)
    breached_levels: List[str] = field(default_factory=list)
    last_circuit_break: Optional[datetime] = None
    position_entries: Dict[str, datetime] = field(default_factory=dict)

class RiskManager:
    def __init__(
        self,
        limits: Optional[RiskLimits] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        kline_store: Optional[KlineMemoryStore] = None,
        orderbook_store: Optional[OrderBookMemoryStore] = None,
        trade_buffer: Optional[TradeBuffer] = None
    ):
        self.limits = limits or RiskLimits()
        self.metrics = RiskMetrics()
        self.kline_store = kline_store or KlineMemoryStore()
        self.orderbook_store = orderbook_store or OrderBookMemoryStore()
        self.trade_buffer = trade_buffer or TradeBuffer()
        
        # Initialize circuit breaker
        self.circuit_breaker = CircuitBreaker(
            config=circuit_breaker_config
        )
        
        # Use existing metrics from monitoring.metrics
        self.current_drawdown = drawdown_gauge
        self.position_count = Gauge(
            'open_position_count',
            'Number of open positions'
        )
        self.risk_breaches = risk_limit_breaches
        
    async def initialize(self):
        """Initialize risk manager state."""
        await self.circuit_breaker.initialize()
        
    def check_limits(self, prediction: float, price: float) -> bool:
        """Check all risk limits before trade."""
        try:
            # 1. Check drawdown
            if not self._check_drawdown():
                return False
            
            # 2. Check circuit breaker
            if not self._check_circuit_breaker(price):
                return False
            
            # 3. Check position limits
            if not self._check_position_limits(prediction, price):
                return False
            
            # 4. Check volatility
            if not self._check_volatility():
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking risk limits: {e}")
            return False
    
    def _check_drawdown(self) -> bool:
        """Check multi-level drawdown thresholds."""
        if self.metrics.current_equity > self.metrics.peak_equity:
            self.metrics.peak_equity = self.metrics.current_equity
            return True
            
        drawdown = (self.metrics.peak_equity - self.metrics.current_equity) / self.metrics.peak_equity
        self.current_drawdown.set(drawdown)
        
        # Check drawdown levels
        for level, threshold in self.limits.drawdown_levels.items():
            if drawdown >= threshold and level not in self.metrics.breached_levels:
                self.metrics.breached_levels.append(level)
                logger.warning(f"Drawdown level {level} breached: {drawdown:.2%}")
                self.risk_breaches.labels(limit_type="drawdown").inc()
                
                if level == "L3":  # Highest level - stop trading
                    return False
        
        return drawdown <= self.limits.max_drawdown
    
    def _check_circuit_breaker(self, current_price: float) -> bool:
        """Check if circuit breaker should be triggered."""
        if self.metrics.last_circuit_break:
            cooldown_elapsed = (datetime.now() - self.metrics.last_circuit_break).total_seconds()
            if cooldown_elapsed < self.limits.circuit_breaker_cooldown:
                return False
        
        for symbol, position in self.metrics.positions.items():
            price_move = abs(current_price - float(position.entry_price)) / float(position.entry_price)
            if price_move >= self.limits.circuit_breaker_pct:
                logger.warning(f"Circuit breaker triggered: {price_move:.2%} move")
                self.metrics.last_circuit_break = datetime.now()
                circuit_breaker_trips.inc()
                return False
        
        return True
    
    def _check_position_limits(self, prediction: float, price: float) -> bool:
        """Check position size and duration limits."""
        # Check total exposure
        total_exposure = sum(abs(float(pos.size) * float(pos.entry_price)) for pos in self.metrics.positions.values())
        if total_exposure >= self.limits.max_position_notional:
            logger.warning(f"Max position notional exceeded: {total_exposure}")
            return False
        
        # Check position duration
        now = datetime.now()
        for symbol, entry_time in self.metrics.position_entries.items():
            duration = (now - entry_time).total_seconds()
            if duration > self.limits.max_position_duration:
                logger.warning(f"Position duration exceeded for {symbol}")
                return False
        
        return True
    
    def _check_volatility(self) -> bool:
        """Check if current volatility is within limits."""
        # This should be implemented with actual volatility calculation
        # from market data. For now, return True.
        return True
    
    def update_equity(self, new_equity: float):
        """Update current equity and check drawdown."""
        self.metrics.current_equity = Decimal(str(new_equity))
        self._check_drawdown()
    
    def record_trade(self, symbol: str, size: float, price: float):
        """Record new trade and update position tracking."""
        self.metrics.position_entries[symbol] = datetime.now()
        self.position_count.set(len(self.metrics.positions))
        
    def close_position(self, symbol: str):
        """Close a position and update metrics."""
        if symbol in self.metrics.positions:
            del self.metrics.positions[symbol]
            del self.metrics.position_entries[symbol]
            self.position_count.set(len(self.metrics.positions))
            
    def update_position(
        self,
        symbol: str,
        size: Decimal,
        entry_price: Decimal,
        stop_loss: Decimal,
        current_price: Optional[Decimal] = None
    ) -> bool:
        """Update position details and check risk limits."""
        try:
            position = Position(
                symbol=symbol,
                size=size,
                entry_price=entry_price,
                stop_loss=stop_loss
            )
            
            if current_price:
                unrealized_pnl = (current_price - entry_price) * size
                position.unrealized_pnl = unrealized_pnl
            
            self.metrics.positions[symbol] = position
            self.position_count.set(len(self.metrics.positions))
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating position: {e}")
            return False
            
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for symbol."""
        return self.metrics.positions.get(symbol)
        
    def get_total_exposure(self) -> Decimal:
        """Calculate total position exposure."""
        return sum(
            abs(pos.size * pos.entry_price)
            for pos in self.metrics.positions.values()
        )
        
    def reset_daily_metrics(self) -> None:
        """Reset daily tracking metrics."""
        self.metrics.daily_pnl = Decimal('0')
        self.metrics.consecutive_losses = 0
        self.metrics.breached_levels = []
        self.metrics.last_circuit_break = None
        self.metrics.peak_equity = self.metrics.current_equity
        self.metrics.position_entries = {}
        self.metrics.position_count.set(0)
        self.metrics.current_drawdown.set(0.0) 