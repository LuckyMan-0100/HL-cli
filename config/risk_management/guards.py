"""
Risk management guards and circuit breakers.
"""
from dataclasses import dataclass
from typing import Optional
import numpy as np
from datetime import datetime, timedelta

@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    price_move_threshold: float = 0.01  # 1% price move
    volume_threshold: float = 100000.0  # $100k notional
    cooldown_seconds: int = 300  # 5 minutes
    
class CircuitBreaker:
    """Circuit breaker implementation."""
    
    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
        memory_store = None
    ):
        self.config = config or CircuitBreakerConfig()
        self.memory_store = memory_store
        self.last_trigger = None
        self.cumulative_volume = 0.0
        
    async def initialize(self):
        """Initialize circuit breaker state."""
        pass
        
    def record_trade(self, notional_value: float):
        """Record trade for volume tracking."""
        self.cumulative_volume += notional_value
        
    def should_trigger(self, price_move: float) -> bool:
        """Check if circuit breaker should trigger."""
        # Check cooldown
        if self.last_trigger:
            cooldown_elapsed = (datetime.now() - self.last_trigger).total_seconds()
            if cooldown_elapsed < self.config.cooldown_seconds:
                return False
                
        # Check conditions
        if (abs(price_move) > self.config.price_move_threshold and
            self.cumulative_volume > self.config.volume_threshold):
            self.last_trigger = datetime.now()
            return True
            
        return False
        
    def reset(self):
        """Reset circuit breaker state."""
        self.last_trigger = None
        self.cumulative_volume = 0.0 