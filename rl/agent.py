"""
PPO agent implementation for trading environment.
"""

import os
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from torch.distributions import Normal

@dataclass
class PPOConfig:
    # Network architecture
    hidden_size: int = 256
    activation: nn.Module = nn.ReLU
    
    # Training hyperparameters
    learning_rate: float = 3e-4
    n_epochs: int = 10
    batch_size: int = 256
    clip_range: float = 0.2
    value_clip_range: float = 0.2
    entropy_coef: float = 0.01
    value_coef: float = 0.5
    max_grad_norm: float = 0.5
    target_kl: float = 0.015
    gamma: float = 0.99
    gae_lambda: float = 0.95

class Actor(nn.Module):
    """Actor network for continuous action space."""
    
    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dim: int = 256,
        log_std_min: float = -20,
        log_std_max: float = 2
    ):
        """
        Initialize the actor network.
        
        Args:
            state_dim: Dimension of state space
            action_dim: Dimension of action space
            hidden_dim: Dimension of hidden layers
            log_std_min: Minimum log standard deviation
            log_std_max: Maximum log standard deviation
        """
        super().__init__()
        
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU()
        )
        
        self.mu = nn.Linear(hidden_dim, action_dim)
        self.log_std = nn.Linear(hidden_dim, action_dim)
        
        self.log_std_min = log_std_min
        self.log_std_max = log_std_max
        
    def forward(self, state: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Forward pass through the network.
        
        Args:
            state: Input state tensor
            
        Returns:
            Mean and log standard deviation of action distribution
        """
        features = self.net(state)
        mu = self.mu(features)
        log_std = self.log_std(features)
        log_std = torch.clamp(log_std, self.log_std_min, self.log_std_max)
        return mu, log_std

class Critic(nn.Module):
    """Critic network for value function estimation."""
    
    def __init__(self, state_dim: int, hidden_dim: int = 256):
        """
        Initialize the critic network.
        
        Args:
            state_dim: Dimension of state space
            hidden_dim: Dimension of hidden layers
        """
        super().__init__()
        
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1)
        )
        
    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """
        Forward pass through the network.
        
        Args:
            state: Input state tensor
            
        Returns:
            Value estimate
        """
        return self.net(state)

class PPOAgent(nn.Module):
    """PPO agent implementation."""
    
    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dim: int = 256,
        lr: float = 3e-4,
        device: str = "cuda" if torch.cuda.is_available() else "cpu"
    ):
        """
        Initialize the PPO agent.
        
        Args:
            state_dim: Dimension of state space
            action_dim: Dimension of action space
            hidden_dim: Dimension of hidden layers
            lr: Learning rate
            device: Device to run the model on
        """
        super().__init__()
        
        self.actor = Actor(state_dim, action_dim, hidden_dim)
        self.critic = Critic(state_dim, hidden_dim)
        
        self.optimizer = torch.optim.Adam(self.parameters(), lr=lr)
        
        self.device = device
        self.to(device)
        
    def get_action_and_value(
        self,
        state: Union[np.ndarray, torch.Tensor],
        deterministic: bool = False
    ) -> Tuple[np.ndarray, float, float]:
        """
        Get action and value estimate for a state.
        
        Args:
            state: Input state
            deterministic: Whether to use deterministic action
            
        Returns:
            Action, log probability, and value estimate
        """
        if isinstance(state, np.ndarray):
            state = torch.FloatTensor(state).to(self.device)
        
        with torch.no_grad():
            mu, log_std = self.actor(state)
            std = log_std.exp()
            
            if deterministic:
                action = mu
                log_prob = None
            else:
                dist = Normal(mu, std)
                action = dist.sample()
                log_prob = dist.log_prob(action).sum(-1)
            
            value = self.critic(state)
        
        return action.cpu().numpy(), log_prob, value.item()
    
    def get_value(self, state: Union[np.ndarray, torch.Tensor]) -> float:
        """
        Get value estimate for a state.
        
        Args:
            state: Input state
            
        Returns:
            Value estimate
        """
        if isinstance(state, np.ndarray):
            state = torch.FloatTensor(state).to(self.device)
        
        with torch.no_grad():
            value = self.critic(state)
        
        return value.item()
    
    def evaluate_actions(
        self,
        states: torch.Tensor,
        actions: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Evaluate actions for given states.
        
        Args:
            states: Input states
            actions: Actions to evaluate
            
        Returns:
            Log probabilities and value estimates
        """
        mu, log_std = self.actor(states)
        std = log_std.exp()
        
        dist = Normal(mu, std)
        log_probs = dist.log_prob(actions).sum(-1)
        
        values = self.critic(states).squeeze()
        
        return log_probs, values
    
    def get_entropy(self) -> torch.Tensor:
        """
        Get entropy of the current policy.
        
        Returns:
            Entropy of the policy
        """
        _, log_std = self.actor(torch.zeros(1, self.actor.net[0].in_features).to(self.device))
        std = log_std.exp()
        dist = Normal(torch.zeros_like(std), std)
        return dist.entropy().sum(-1)
    
    def save(self, path: str) -> None:
        """
        Save the model to disk.
        
        Args:
            path: Path to save the model
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save(self.state_dict(), path)
    
    def load(self, path: str) -> None:
        """
        Load the model from disk.
        
        Args:
            path: Path to load the model from
        """
        self.load_state_dict(torch.load(path, map_location=self.device)) 