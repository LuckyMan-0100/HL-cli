import pytest
import numpy as np
from decimal import Decimal
from rl.environment import TradingEnvironment
from data_ingestion.memory_store import MemoryStore, OrderBook
from risk_management.risk_manager import RiskManager, Position

class MockOrderBook:
    def __init__(self, bids, asks):
        self.bids = bids
        self.asks = asks

@pytest.fixture
def memory_store():
    store = MemoryStore()
    # Add mock data
    ob = MockOrderBook(
        bids=[{"price": Decimal("100"), "quantity": Decimal("1.0")}],
        asks=[{"price": Decimal("101"), "quantity": Decimal("1.0")}]
    )
    store.update_orderbook("SOL/USD", ob)
    return store

@pytest.fixture
def risk_manager():
    return RiskManager()

@pytest.fixture
def env(memory_store, risk_manager):
    return TradingEnvironment(
        symbol="SOL/USD",
        memory_store=memory_store,
        risk_manager=risk_manager,
        lookback_periods=20,
        max_position_size=1.0,
        transaction_fee=0.001,
        reward_scaling=1.0,
        episode_steps=1000
    )

def test_env_initialization(env):
    """Test environment initialization"""
    assert env.symbol == "SOL/USD"
    assert env.max_position_size == 1.0
    assert env.transaction_fee == 0.001
    assert env.reward_scaling == 1.0
    assert env.episode_steps == 1000

def test_env_reset(env):
    """Test environment reset"""
    obs, info = env.reset()
    assert isinstance(obs, dict)
    assert "book_features" in obs
    assert "technical_features" in obs
    assert "position" in obs
    assert "entry_price" in obs
    assert obs["position"][0] == 0.0
    assert obs["entry_price"][0] == 0.0

def test_env_step_long_position(env):
    """Test taking a long position"""
    env.reset()
    action = np.array([0.5])  # 50% long position
    obs, reward, done, truncated, info = env.step(action)
    
    assert isinstance(obs, dict)
    assert isinstance(reward, float)
    assert isinstance(done, bool)
    assert isinstance(info, dict)
    assert obs["position"][0] > 0.0

def test_env_step_short_position(env):
    """Test taking a short position"""
    env.reset()
    action = np.array([-0.5])  # 50% short position
    obs, reward, done, truncated, info = env.step(action)
    
    assert isinstance(obs, dict)
    assert isinstance(reward, float)
    assert isinstance(done, bool)
    assert isinstance(info, dict)
    assert obs["position"][0] < 0.0

def test_position_limits(env):
    """Test position size limits"""
    env.reset()
    action = np.array([2.0])  # Try to exceed max position
    obs, _, _, _, _ = env.step(action)
    assert abs(obs["position"][0]) <= env.max_position_size

def test_episode_termination(env):
    """Test episode termination"""
    env.reset()
    done = False
    steps = 0
    while not done and steps < env.episode_steps + 10:
        _, _, done, truncated, _ = env.step(np.array([0.1]))
        done = done or truncated
        steps += 1
    assert steps == env.episode_steps

def test_reward_calculation(env):
    """Test reward calculation with fees"""
    env.reset()
    
    # Take position
    action = np.array([0.5])
    _, reward1, _, _, _ = env.step(action)
    
    # Close position
    action = np.array([0.0])
    _, reward2, _, _, _ = env.step(action)
    
    # Verify transaction fees are applied
    assert abs(reward1) >= env.transaction_fee
    assert abs(reward2) >= env.transaction_fee

def test_observation_space(env):
    """Test observation space consistency"""
    obs, _ = env.reset()
    
    assert obs["book_features"].shape == (env.lookback_periods, 6)
    assert obs["technical_features"].shape == (env.lookback_periods, 4)
    assert obs["position"].shape == (1,)
    assert obs["entry_price"].shape == (1,)

def test_edge_cases(env):
    """Test edge cases and error handling"""
    env.reset()
    
    # Test invalid actions
    obs, _, _, _, _ = env.step(np.array([np.nan]))
    assert not np.isnan(obs["position"][0])
    
    obs, _, _, _, _ = env.step(np.array([np.inf]))
    assert not np.isinf(obs["position"][0])
    
    # Test with empty order book
    env.memory_store.clear()
    obs, reward, done, truncated, info = env.step(np.array([0.1]))
    assert "error" in info

if __name__ == "__main__":
    pytest.main([__file__]) 