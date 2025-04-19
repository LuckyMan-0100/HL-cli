"""
Custom Gymnasium environment for order book trading.
"""

import gymnasium as gym
import numpy as np
from gymnasium import spaces
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any

from data_ingestion.memory_store import MemoryStore, OrderBook
from risk_management.risk_manager import RiskManager, Position

class TradingEnvironment(gym.Env):
    """
    Trading environment that follows gym interface.
    Provides order book state and inventory management.
    """
    
    def __init__(
        self,
        symbol: str,
        memory_store: MemoryStore,
        risk_manager: RiskManager,
        lookback_periods: int = 20,
        max_position_size: float = 1.0,
        transaction_fee: float = 0.001,  # 10 bps
        reward_scaling: float = 1e-4,
        episode_steps: int = 1000
    ):
        super().__init__()
        
        self.symbol = symbol
        self.memory_store = memory_store
        self.risk_manager = risk_manager
        self.lookback_periods = lookback_periods
        self.max_position_size = max_position_size
        self.transaction_fee = transaction_fee
        self.reward_scaling = reward_scaling
        self.episode_steps = episode_steps
        
        # Define action space: [-1, 1] for position sizing
        self.action_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(1,),
            dtype=np.float32
        )
        
        # Define observation space
        self.observation_space = spaces.Dict({
            # Order book features
            'book_features': spaces.Box(
                low=-np.inf,
                high=np.inf,
                shape=(lookback_periods, 6),  # price, volume, imbalance for bid/ask
                dtype=np.float32
            ),
            # Technical indicators
            'technical_features': spaces.Box(
                low=-np.inf,
                high=np.inf,
                shape=(lookback_periods, 4),  # RSI, MACD, BB%, ATR
                dtype=np.float32
            ),
            # Position state
            'position': spaces.Box(
                low=-max_position_size,
                high=max_position_size,
                shape=(1,),
                dtype=np.float32
            ),
            # Entry price (0 if no position)
            'entry_price': spaces.Box(
                low=0,
                high=np.inf,
                shape=(1,),
                dtype=np.float32
            )
        })
        
        self._current_step = 0
        self._current_position: Optional[Position] = None
        self._episode_pnl = 0.0
        self._total_volume = 0.0
        
    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[Dict] = None
    ) -> Tuple[Dict, Dict]:
        """Reset environment to initial state."""
        super().reset(seed=seed)
        
        self._current_step = 0
        self._current_position = None
        self._episode_pnl = 0.0
        self._total_volume = 0.0
        
        observation = self._get_observation()
        info = {}
        
        return observation, info
        
    def step(self, action: np.ndarray) -> Tuple[Dict, float, bool, bool, Dict]:
        """Execute one environment step."""
        self._current_step += 1
        
        # Get current market state
        ob = self.memory_store.get_orderbook_snapshot(self.symbol)
        if not ob:
            return self._get_observation(), 0.0, True, False, {'error': 'No order book data'}
            
        mid_price = self.memory_store.get_mid_price(self.symbol)
        if not mid_price:
            return self._get_observation(), 0.0, True, False, {'error': 'No price data'}
            
        # Calculate target position
        target_position = float(action[0]) * self.max_position_size
        
        # Calculate trade size
        current_position = float(self._current_position.size) if self._current_position else 0.0
        trade_size = target_position - current_position
        
        reward = 0.0
        info = {}
        
        if abs(trade_size) > 0:
            # Execute trade
            price = float(ob.asks[0].price if trade_size > 0 else ob.bids[0].price)
            notional = abs(trade_size * price)
            
            # Apply transaction fee
            fee = notional * self.transaction_fee
            reward -= fee
            
            # Update position
            if self._current_position:
                # Close existing position
                pnl = (price - float(self._current_position.entry_price)) * current_position
                self._episode_pnl += pnl
                reward += pnl
                self._current_position = None
                
            if abs(target_position) > 0:
                # Open new position
                self._current_position = Position(
                    symbol=self.symbol,
                    size=Decimal(str(target_position)),
                    entry_price=Decimal(str(price)),
                    stop_loss=Decimal('0')  # Not using stop loss in RL
                )
                
            self._total_volume += notional
            
        elif self._current_position:
            # Mark-to-market existing position
            unrealized_pnl = (float(mid_price) - float(self._current_position.entry_price)) * current_position
            reward += unrealized_pnl - self._episode_pnl  # Only count change in PnL
            self._episode_pnl = unrealized_pnl
            
        # Scale reward
        reward *= self.reward_scaling
        
        # Add volume-based reward component
        volume_reward = self._total_volume * self.reward_scaling * 0.1  # 10% weight to volume
        reward += volume_reward
        
        # Check if episode is done
        done = self._current_step >= self.episode_steps
        
        # Get next observation
        observation = self._get_observation()
        
        info.update({
            'step': self._current_step,
            'position': current_position,
            'pnl': self._episode_pnl,
            'volume': self._total_volume
        })
        
        return observation, reward, done, False, info
        
    def _get_observation(self) -> Dict[str, np.ndarray]:
        """Construct observation from current state."""
        # Get order book features
        ob_features = np.zeros((self.lookback_periods, 6), dtype=np.float32)
        ob_history = self.memory_store.get_orderbook_history(
            self.symbol,
            self.lookback_periods
        )
        
        for i, ob in enumerate(ob_history):
            if i >= self.lookback_periods:
                break
                
            mid_price = (float(ob.bids[0].price) + float(ob.asks[0].price)) / 2
            bid_volume = float(ob.bids[0].quantity)
            ask_volume = float(ob.asks[0].quantity)
            total_volume = bid_volume + ask_volume
            
            ob_features[i] = [
                float(ob.bids[0].price) / mid_price - 1,  # Normalized bid price
                float(ob.asks[0].price) / mid_price - 1,  # Normalized ask price
                bid_volume / total_volume if total_volume > 0 else 0,  # Bid volume ratio
                ask_volume / total_volume if total_volume > 0 else 0,  # Ask volume ratio
                sum(float(level.quantity) for level in ob.bids[:5]),  # Bid depth
                sum(float(level.quantity) for level in ob.asks[:5])   # Ask depth
            ]
            
        # Get technical features (placeholder - should be calculated properly)
        tech_features = np.zeros((self.lookback_periods, 4), dtype=np.float32)
        
        # Get position state
        position = np.array(
            [float(self._current_position.size)] if self._current_position else [0.0],
            dtype=np.float32
        )
        
        entry_price = np.array(
            [float(self._current_position.entry_price)] if self._current_position else [0.0],
            dtype=np.float32
        )
        
        return {
            'book_features': ob_features,
            'technical_features': tech_features,
            'position': position,
            'entry_price': entry_price
        }
        
    def render(self):
        """Render environment state."""
        pass  # Not implemented
        
    def close(self):
        """Clean up environment resources."""
        pass 