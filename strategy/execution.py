"""
Low-latency execution logic with smart order routing and risk management.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
import logging
from datetime import datetime, timedelta

from config.settings import settings

logger = logging.getLogger(__name__)

@dataclass
class OrderConfig:
    """Configuration for order execution."""
    symbol: str
    side: str  # 'BUY' or 'SELL'
    quantity: float
    take_profit_levels: list  # List of price levels for take profit grid
    stop_loss_level: float
    order_type: str  # 'LIMIT' or 'MARKET'
    time_in_force: str = 'GTC'
    
@dataclass
class RiskLimits:
    """Risk management parameters."""
    max_position_notional: float
    max_trade_notional: float
    max_drawdown_pct: float
    volatility_scale_factor: float
    cooldown_seconds: int
    
class ExecutionManager:
    def __init__(
        self,
        risk_limits: RiskLimits,
        symbol: str = settings.trading.symbol,
        min_spread_threshold: float = 0.0002,  # 2bps
        min_imbalance_threshold: float = 0.2,
        atr_window: int = 14,
        ema_window: int = 100
    ):
        self.risk_limits = risk_limits
        self.symbol = symbol
        self.min_spread_threshold = min_spread_threshold
        self.min_imbalance_threshold = min_imbalance_threshold
        
        # State variables
        self.current_position = 0
        self.current_notional = 0
        self.last_fill_time = None
        self.daily_pnl = []
        self.trade_history = []
        
        # Risk metrics
        self.atr_window = atr_window
        self.ema_window = ema_window
        self.atr = None
        self.volatility_ema = None
        
    def update_risk_metrics(self, price_data: pd.DataFrame):
        """Update ATR and volatility EMA."""
        if len(price_data) >= self.atr_window:
            high = price_data['high'].values
            low = price_data['low'].values
            close = price_data['close'].values
            
            tr1 = np.abs(high - low)
            tr2 = np.abs(high - np.roll(close, 1))
            tr3 = np.abs(low - np.roll(close, 1))
            tr = np.maximum(tr1, np.maximum(tr2, tr3))
            
            self.atr = np.mean(tr[-self.atr_window:])
            
            returns = np.diff(np.log(close))
            vol = np.std(returns) * np.sqrt(252)  # Annualized
            
            if self.volatility_ema is None:
                self.volatility_ema = vol
            else:
                alpha = 2 / (self.ema_window + 1)
                self.volatility_ema = (1 - alpha) * self.volatility_ema + alpha * vol
    
    def determine_order_type(self, book_data: Dict) -> str:
        """
        Determine whether to use limit or market order based on book conditions.
        
        Args:
            book_data: Order book snapshot with bid/ask prices and quantities
            
        Returns:
            str: 'LIMIT' or 'MARKET'
        """
        spread = (book_data['ask_price'] - book_data['bid_price']) / book_data['bid_price']
        
        total_quantity = book_data['bid_quantity'] + book_data['ask_quantity']
        imbalance = abs(book_data['bid_quantity'] - book_data['ask_quantity']) / total_quantity
        
        if spread <= self.min_spread_threshold and imbalance >= self.min_imbalance_threshold:
            return 'LIMIT'
        return 'MARKET'
    
    def calculate_position_size(self, signal_strength: float, price: float) -> float:
        """
        Calculate position size scaled by volatility and signal strength.
        
        Args:
            signal_strength: Model prediction probability
            price: Current price
            
        Returns:
            float: Position size in base currency
        """
        if self.atr is None or self.volatility_ema is None:
            return 0
        
        # Scale position by signal strength and inverse volatility
        vol_scale = self.risk_limits.volatility_scale_factor / self.volatility_ema
        base_size = self.risk_limits.max_trade_notional / price
        
        # Scale by signal strength (0.5-1.0)
        signal_scale = 0.5 + 0.5 * signal_strength
        
        size = base_size * vol_scale * signal_scale
        
        # Apply risk limits
        max_size = self.risk_limits.max_position_notional / price
        size = min(size, max_size - abs(self.current_position))
        
        return size
    
    def generate_take_profit_grid(self, 
                                entry_price: float,
                                side: str,
                                size: float) -> list:
        """
        Generate grid of take-profit levels based on ATR.
        
        Args:
            entry_price: Entry price
            side: 'BUY' or 'SELL'
            size: Position size
            
        Returns:
            list: List of (price, size) tuples for take-profit orders
        """
        if self.atr is None:
            return []
            
        # Generate 3 take-profit levels at 1, 2, and 3 ATR
        atr_multiples = [1.0, 2.0, 3.0]
        size_fractions = [0.5, 0.3, 0.2]  # Split position across levels
        
        grid = []
        for atr_mult, size_frac in zip(atr_multiples, size_fractions):
            if side == 'BUY':
                price = entry_price * (1 + atr_mult * self.atr)
            else:
                price = entry_price * (1 - atr_mult * self.atr)
            grid.append((price, size * size_frac))
            
        return grid
    
    def check_drawdown(self) -> bool:
        """Check if drawdown exceeds threshold."""
        if len(self.daily_pnl) < 2:
            return False
            
        peak = max(self.daily_pnl)
        current = self.daily_pnl[-1]
        drawdown = (peak - current) / peak
        
        return drawdown > self.risk_limits.max_drawdown_pct
    
    def can_trade(self) -> bool:
        """Check if we can trade based on cooldown and risk limits."""
        if self.last_fill_time is None:
            return True
            
        # Check cooldown period
        time_since_fill = datetime.now() - self.last_fill_time
        if time_since_fill.total_seconds() < self.risk_limits.cooldown_seconds:
            return False
            
        # Check drawdown
        if self.check_drawdown():
            logger.warning("Trading halted due to drawdown limit breach")
            return False
            
        return True
    
    def prepare_order(self,
                     side: str,
                     signal_strength: float,
                     price_data: pd.DataFrame,
                     book_data: Dict) -> Optional[OrderConfig]:
        """
        Prepare an order with size, type and risk parameters.
        
        Args:
            side: 'BUY' or 'SELL'
            signal_strength: Model prediction probability
            price_data: Recent OHLCV data
            book_data: Current order book snapshot
            
        Returns:
            OrderConfig or None if order should not be placed
        """
        if not self.can_trade():
            return None
            
        # Update risk metrics
        self.update_risk_metrics(price_data)
        
        # Get current mid price
        mid_price = (book_data['bid_price'] + book_data['ask_price']) / 2
        
        # Calculate position size
        size = self.calculate_position_size(signal_strength, mid_price)
        if size == 0:
            return None
            
        # Determine order type
        order_type = self.determine_order_type(book_data)
        
        # Generate take-profit grid
        tp_grid = self.generate_take_profit_grid(mid_price, side, size)
        
        # Set stop loss at 2 ATR
        stop_loss = mid_price * (1 - 2 * self.atr) if side == 'BUY' else mid_price * (1 + 2 * self.atr)
        
        return OrderConfig(
            symbol=self.symbol,
            side=side,
            quantity=size,
            take_profit_levels=[level[0] for level in tp_grid],
            stop_loss_level=stop_loss,
            order_type=order_type
        ) 