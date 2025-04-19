import pytest
import torch
import numpy as np
from rl.agent import Actor, Critic, PPOAgent

def test_actor():
    state_dim = 4
    action_dim = 2
    batch_size = 3
    actor = Actor(state_dim, action_dim)
    
    # Test single state
    state = torch.randn(state_dim)
    mu, log_std = actor(state)
    assert mu.shape == (action_dim,)
    assert log_std.shape == (action_dim,)
    assert torch.all(log_std >= actor.log_std_min)
    assert torch.all(log_std <= actor.log_std_max)
    
    # Test batch of states
    states = torch.randn(batch_size, state_dim)
    mu, log_std = actor(states)
    assert mu.shape == (batch_size, action_dim)
    assert log_std.shape == (batch_size, action_dim)
    assert torch.all(log_std >= actor.log_std_min)
    assert torch.all(log_std <= actor.log_std_max)

def test_critic():
    state_dim = 4
    batch_size = 3
    critic = Critic(state_dim)
    
    # Test single state
    state = torch.randn(state_dim)
    value = critic(state)
    assert value.shape == (1,)
    
    # Test batch of states
    states = torch.randn(batch_size, state_dim)
    values = critic(states)
    assert values.shape == (batch_size, 1)

def test_ppo_agent():
    state_dim = 4
    action_dim = 2
    batch_size = 3
    agent = PPOAgent(state_dim, action_dim)
    
    # Test get_action_and_value with numpy array
    state = np.random.randn(state_dim)
    action, log_prob, value = agent.get_action_and_value(state)
    assert isinstance(action, np.ndarray)
    assert action.shape == (action_dim,)
    assert isinstance(value, float)
    
    # Test get_action_and_value with torch tensor
    state = torch.randn(state_dim)
    action, log_prob, value = agent.get_action_and_value(state)
    assert isinstance(action, np.ndarray)
    assert action.shape == (action_dim,)
    assert isinstance(value, float)
    
    # Test deterministic action
    state = torch.randn(state_dim)
    action, log_prob, value = agent.get_action_and_value(state, deterministic=True)
    assert isinstance(action, np.ndarray)
    assert action.shape == (action_dim,)
    assert log_prob is None
    assert isinstance(value, float)
    
    # Test evaluate_actions
    states = torch.randn(batch_size, state_dim)
    actions = torch.randn(batch_size, action_dim)
    log_probs, values = agent.evaluate_actions(states, actions)
    assert log_probs.shape == (batch_size,)
    assert values.shape == (batch_size,)
    
    # Test get_entropy
    entropy = agent.get_entropy()
    assert isinstance(entropy, torch.Tensor)
    assert entropy.shape == (1,)
    
    # Test save and load (using temporary file)
    import tempfile
    import os
    
    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = f.name
        
    try:
        # Save model
        agent.save(path)
        assert os.path.exists(path)
        
        # Load model
        new_agent = PPOAgent(state_dim, action_dim)
        new_agent.load(path)
        
        # Compare outputs
        state = torch.randn(state_dim)
        with torch.no_grad():
            action1, _, value1 = agent.get_action_and_value(state, deterministic=True)
            action2, _, value2 = new_agent.get_action_and_value(state, deterministic=True)
            
        np.testing.assert_array_almost_equal(action1, action2)
        assert abs(value1 - value2) < 1e-6
        
    finally:
        os.unlink(path)

if __name__ == "__main__":
    pytest.main([__file__]) 