import pytest
import numpy as np
import torch
import os
import tempfile
from rl.train import compute_gae, RolloutBuffer, train
from rl.agent import PPOAgent
from rl.environment import TradingEnvironment
from data_ingestion.memory_store import MemoryStore
from risk_management.risk_manager import RiskManager

def test_compute_gae():
    """Test GAE computation"""
    rewards = np.array([1.0, 2.0, 3.0])
    values = np.array([1.1, 2.1, 3.1])
    dones = np.array([0, 0, 1])
    next_values = np.array([2.1, 3.1, 0.0])
    gamma = 0.99
    gae_lambda = 0.95
    
    advantages, returns = compute_gae(rewards, values, dones, next_values, gamma, gae_lambda)
    
    assert advantages.shape == (3,)
    assert returns.shape == (3,)
    assert not np.any(np.isnan(advantages))
    assert not np.any(np.isnan(returns))
    assert returns[-1] == rewards[-1]  # Last return should equal last reward when done

def test_rollout_buffer():
    """Test RolloutBuffer functionality"""
    buffer = RolloutBuffer()
    
    # Test adding transitions
    state = np.zeros(4)
    action = np.array([0.5])
    reward = 1.0
    done = False
    value = 1.1
    log_prob = -0.5
    
    buffer.add(state, action, reward, done, value, log_prob)
    
    assert len(buffer.states) == 1
    assert len(buffer.actions) == 1
    assert len(buffer.rewards) == 1
    assert len(buffer.dones) == 1
    assert len(buffer.values) == 1
    assert len(buffer.log_probs) == 1
    
    # Test computing returns and advantages
    buffer.compute_returns_and_advantages(0.0, 0.99, 0.95)
    
    assert len(buffer.advantages) == 1
    assert len(buffer.returns) == 1
    
    # Test getting data as tensors
    states, actions, old_log_probs, advantages, returns = buffer.get()
    
    assert isinstance(states, torch.Tensor)
    assert isinstance(actions, torch.Tensor)
    assert isinstance(old_log_probs, torch.Tensor)
    assert isinstance(advantages, torch.Tensor)
    assert isinstance(returns, torch.Tensor)
    
    # Test clearing buffer
    buffer.clear()
    
    assert len(buffer.states) == 0
    assert len(buffer.actions) == 0
    assert len(buffer.rewards) == 0
    assert len(buffer.dones) == 0
    assert len(buffer.values) == 0
    assert len(buffer.log_probs) == 0
    assert len(buffer.advantages) == 0
    assert len(buffer.returns) == 0

@pytest.fixture
def training_env():
    memory_store = MemoryStore()
    risk_manager = RiskManager()
    return TradingEnvironment(
        symbol="SOL/USD",
        memory_store=memory_store,
        risk_manager=risk_manager,
        lookback_periods=20,
        max_position_size=1.0,
        transaction_fee=0.001,
        reward_scaling=1.0,
        episode_steps=100
    )

@pytest.fixture
def agent(training_env):
    state_dim = 4  # Simplified for testing
    action_dim = 1
    return PPOAgent(state_dim, action_dim)

def test_training_loop(training_env, agent):
    """Test the main training loop"""
    with tempfile.TemporaryDirectory() as temp_dir:
        metrics = train(
            env=training_env,
            agent=agent,
            total_timesteps=1000,  # Small number for testing
            n_steps=128,
            n_epochs=2,
            batch_size=32,
            eval_freq=500,
            n_eval_episodes=2,
            save_freq=500,
            save_path=os.path.join(temp_dir, "models"),
            log_path=os.path.join(temp_dir, "logs")
        )
    
    assert isinstance(metrics, dict)
    assert "train_returns" in metrics
    assert "eval_returns" in metrics
    assert "episodes" in metrics
    assert "timesteps" in metrics
    assert metrics["timesteps"] == 1000

def test_training_early_stopping(training_env, agent):
    """Test training with early stopping based on KL divergence"""
    with tempfile.TemporaryDirectory() as temp_dir:
        metrics = train(
            env=training_env,
            agent=agent,
            total_timesteps=1000,
            n_steps=128,
            n_epochs=2,
            batch_size=32,
            target_kl=0.01,  # Small KL threshold for testing
            save_path=os.path.join(temp_dir, "models"),
            log_path=os.path.join(temp_dir, "logs")
        )
    
    assert metrics["timesteps"] > 0

def test_training_checkpointing(training_env, agent):
    """Test model checkpointing during training"""
    with tempfile.TemporaryDirectory() as temp_dir:
        save_path = os.path.join(temp_dir, "models")
        train(
            env=training_env,
            agent=agent,
            total_timesteps=1000,
            n_steps=128,
            save_freq=500,
            save_path=save_path,
            log_path=os.path.join(temp_dir, "logs")
        )
        
        # Check if model was saved
        model_files = [f for f in os.listdir(save_path) if f.startswith("model_")]
        assert len(model_files) > 0

def test_training_logging(training_env, agent):
    """Test training metrics logging"""
    with tempfile.TemporaryDirectory() as temp_dir:
        log_path = os.path.join(temp_dir, "logs")
        train(
            env=training_env,
            agent=agent,
            total_timesteps=1000,
            n_steps=128,
            eval_freq=500,
            save_path=os.path.join(temp_dir, "models"),
            log_path=log_path
        )
        
        # Check if log file was created
        log_files = [f for f in os.listdir(log_path) if f.endswith(".json")]
        assert len(log_files) > 0

if __name__ == "__main__":
    pytest.main([__file__]) 