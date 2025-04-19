"""
Training script for PPO agent.
"""

import os
import numpy as np
from typing import Dict, List, Optional, Tuple
import gymnasium as gym
from collections import defaultdict
import torch
import logging
from datetime import datetime
import json
from tqdm import tqdm

from .agent import PPOAgent, PPOConfig
from .environment import TradingEnvironment

def compute_gae(
    rewards: np.ndarray,
    values: np.ndarray,
    dones: np.ndarray,
    next_values: np.ndarray,
    gamma: float = 0.99,
    gae_lambda: float = 0.95
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute Generalized Advantage Estimation (GAE).
    
    Args:
        rewards: Array of rewards for each timestep
        values: Array of value estimates for each timestep
        dones: Array of done flags for each timestep
        next_values: Array of value estimates for next timesteps
        gamma: Discount factor
        gae_lambda: GAE smoothing parameter
        
    Returns:
        advantages: Array of advantage estimates
        returns: Array of return estimates
    """
    advantages = np.zeros_like(rewards)
    last_gae = 0
    
    for t in reversed(range(len(rewards))):
        if t == len(rewards) - 1:
            next_value = next_values[t]
        else:
            next_value = values[t + 1]
            
        delta = rewards[t] + gamma * next_value * (1 - dones[t]) - values[t]
        advantages[t] = last_gae = delta + gamma * gae_lambda * (1 - dones[t]) * last_gae
        
    returns = advantages + values
    return advantages, returns

class RolloutBuffer:
    """Buffer for storing trajectories collected during training."""
    
    def __init__(self):
        self.states = []
        self.actions = []
        self.rewards = []
        self.dones = []
        self.values = []
        self.log_probs = []
        self.advantages = []
        self.returns = []
        
    def add(
        self,
        state: np.ndarray,
        action: np.ndarray,
        reward: float,
        done: bool,
        value: float,
        log_prob: float
    ):
        """Add a transition to the buffer."""
        self.states.append(state)
        self.actions.append(action)
        self.rewards.append(reward)
        self.dones.append(done)
        self.values.append(value)
        self.log_probs.append(log_prob)
        
    def compute_returns_and_advantages(
        self,
        last_value: float,
        gamma: float,
        gae_lambda: float
    ):
        """Compute returns and advantages for all stored transitions."""
        values = np.array(self.values + [last_value])
        advantages, returns = compute_gae(
            np.array(self.rewards),
            np.array(self.values),
            np.array(self.dones),
            values[1:],
            gamma,
            gae_lambda
        )
        
        self.advantages = advantages
        self.returns = returns
        
    def get(self) -> Tuple[torch.Tensor, ...]:
        """Get all data from the buffer and convert to PyTorch tensors."""
        states = torch.FloatTensor(np.array(self.states))
        actions = torch.FloatTensor(np.array(self.actions))
        old_log_probs = torch.FloatTensor(np.array(self.log_probs))
        advantages = torch.FloatTensor(np.array(self.advantages))
        returns = torch.FloatTensor(np.array(self.returns))
        
        # Normalize advantages
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
        
        return states, actions, old_log_probs, advantages, returns
        
    def clear(self):
        """Clear the buffer."""
        self.states.clear()
        self.actions.clear()
        self.rewards.clear()
        self.dones.clear()
        self.values.clear()
        self.log_probs.clear()
        self.advantages.clear()
        self.returns.clear()

def train(
    env: gym.Env,
    agent: 'PPOAgent',
    total_timesteps: int = 1_000_000,
    n_steps: int = 2048,
    n_epochs: int = 10,
    batch_size: int = 64,
    learning_rate: float = 3e-4,
    gamma: float = 0.99,
    gae_lambda: float = 0.95,
    clip_range: float = 0.2,
    clip_range_vf: float = None,
    ent_coef: float = 0.0,
    vf_coef: float = 0.5,
    max_grad_norm: float = 0.5,
    target_kl: float = None,
    eval_freq: int = 10000,
    n_eval_episodes: int = 5,
    save_freq: int = 10000,
    save_path: str = "models",
    log_path: str = "logs"
) -> Dict:
    """
    Train a PPO agent.
    
    Args:
        env: Training environment
        agent: PPO agent instance
        total_timesteps: Total timesteps to train for
        n_steps: Number of steps to run for each environment per update
        n_epochs: Number of epochs when optimizing the surrogate loss
        batch_size: Minibatch size
        learning_rate: Learning rate
        gamma: Discount factor
        gae_lambda: Factor for trade-off of bias vs variance for GAE
        clip_range: Clipping parameter for the value function
        clip_range_vf: Clipping parameter for the value function
        ent_coef: Entropy coefficient for the loss calculation
        vf_coef: Value function coefficient for the loss calculation
        max_grad_norm: Maximum norm for gradient clipping
        target_kl: Target KL divergence threshold
        eval_freq: How many steps between evaluations
        n_eval_episodes: Number of episodes to evaluate for
        save_freq: How many steps between saving the model
        save_path: Path to save the model
        log_path: Path to save the logs
        
    Returns:
        Dictionary containing training metrics
    """
    # Create directories if they don't exist
    os.makedirs(save_path, exist_ok=True)
    os.makedirs(log_path, exist_ok=True)
    
    # Initialize logging
    log_file = os.path.join(log_path, f"training_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    metrics = {
        "train_returns": [],
        "eval_returns": [],
        "episodes": 0,
        "timesteps": 0
    }
    
    # Initialize rollout buffer
    buffer = RolloutBuffer()
    
    # Training loop
    state, _ = env.reset()
    for timestep in tqdm(range(total_timesteps), desc="Training"):
        # Collect rollout
        for step in range(n_steps):
            # Get action and value from the agent
            with torch.no_grad():
                action, log_prob, value = agent.get_action_and_value(state)
            
            # Execute action in environment
            next_state, reward, done, truncated, info = env.step(action)
            
            # Store transition in buffer
            buffer.add(state, action, reward, done or truncated, value, log_prob)
            
            state = next_state if not (done or truncated) else env.reset()[0]
            
            metrics["timesteps"] += 1
            if done or truncated:
                metrics["episodes"] += 1
                metrics["train_returns"].append(info.get("episode", {}).get("r", 0))
        
        # Compute returns and advantages
        with torch.no_grad():
            last_value = agent.get_value(state)
        buffer.compute_returns_and_advantages(last_value, gamma, gae_lambda)
        
        # Update policy
        for epoch in range(n_epochs):
            # Get data from buffer
            states, actions, old_log_probs, advantages, returns = buffer.get()
            
            # Create data loader
            dataset = torch.utils.data.TensorDataset(
                states, actions, old_log_probs, advantages, returns
            )
            data_loader = torch.utils.data.DataLoader(
                dataset, batch_size=batch_size, shuffle=True
            )
            
            for batch in data_loader:
                b_states, b_actions, b_old_log_probs, b_advantages, b_returns = batch
                
                # Get current policy outputs
                new_log_probs, values = agent.evaluate_actions(b_states, b_actions)
                
                # Calculate policy loss
                ratio = torch.exp(new_log_probs - b_old_log_probs)
                policy_loss_1 = -b_advantages * ratio
                policy_loss_2 = -b_advantages * torch.clamp(
                    ratio, 1 - clip_range, 1 + clip_range
                )
                policy_loss = torch.mean(torch.max(policy_loss_1, policy_loss_2))
                
                # Calculate value loss
                if clip_range_vf is None:
                    value_loss = torch.mean((b_returns - values) ** 2)
                else:
                    values_clipped = b_returns + torch.clamp(
                        values - b_returns, -clip_range_vf, clip_range_vf
                    )
                    value_loss_1 = (values - b_returns) ** 2
                    value_loss_2 = (values_clipped - b_returns) ** 2
                    value_loss = torch.mean(torch.max(value_loss_1, value_loss_2))
                
                # Calculate entropy loss
                entropy_loss = -torch.mean(agent.get_entropy())
                
                # Calculate total loss
                loss = policy_loss + vf_coef * value_loss + ent_coef * entropy_loss
                
                # Optimize
                agent.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(agent.parameters(), max_grad_norm)
                agent.optimizer.step()
                
                # Check KL divergence
                if target_kl is not None:
                    approx_kl = torch.mean(b_old_log_probs - new_log_probs)
                    if approx_kl > target_kl:
                        break
        
        # Clear buffer
        buffer.clear()
        
        # Evaluate agent
        if (timestep + 1) % eval_freq == 0:
            eval_returns = []
            for _ in range(n_eval_episodes):
                state, _ = env.reset()
                episode_return = 0
                done = False
                while not done:
                    action = agent.get_action(state)
                    state, reward, done, truncated, _ = env.step(action)
                    episode_return += reward
                    done = done or truncated
                eval_returns.append(episode_return)
            
            metrics["eval_returns"].append(np.mean(eval_returns))
            
            # Save metrics
            with open(log_file, 'w') as f:
                json.dump(metrics, f)
        
        # Save model
        if (timestep + 1) % save_freq == 0:
            agent.save(os.path.join(save_path, f"model_{timestep + 1}.pt"))
    
    return metrics

if __name__ == "__main__":
    # Example usage
    from memory_store import MemoryStore
    from risk_manager import RiskManager
    
    # Initialize components
    memory_store = MemoryStore()
    risk_manager = RiskManager()
    
    # Create environment
    env = TradingEnvironment(
        symbol="SOL/USD",
        memory_store=memory_store,
        risk_manager=risk_manager,
        lookback_periods=100,
        max_position_size=1.0,
        transaction_fee=0.001,
        reward_scaling=1.0,
        episode_steps=1000
    )
    
    # Create agent
    agent = PPOAgent(PPOConfig())
    agent.build_model(
        ob_feature_dim=env.ob_feature_dim,
        tech_feature_dim=env.tech_feature_dim,
        lookback_periods=env.lookback_periods
    )
    
    # Train agent
    train(
        env=env,
        agent=agent,
        total_timesteps=1_000_000,
        n_steps=2048,
        eval_freq=10000,
        n_eval_episodes=5,
        save_freq=10000,
        save_path="models",
        log_path="logs"
    ) 