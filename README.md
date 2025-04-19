# PPO Trading Agent Training

This repository contains a training script for a PPO (Proximal Policy Optimization) agent designed for trading in financial markets.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Ensure you have the trading environment and agent components set up in your project structure.

## Training the Agent

The training script (`rl/train.py`) provides a comprehensive implementation for training a PPO agent. Key features include:

- Generalized Advantage Estimation (GAE)
- Rollout buffer for trajectory storage
- Periodic evaluation and model checkpointing
- Training metrics logging

### Example Usage

```python
from rl.train import train
from rl.env import TradingEnvironment
from rl.agent import PPOAgent
from rl.memory import MemoryStore
from rl.risk import RiskManager

# Initialize components
memory_store = MemoryStore()
risk_manager = RiskManager()
env = TradingEnvironment(memory_store, risk_manager)
agent = PPOAgent(env)

# Start training
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
```

### Training Parameters

- `total_timesteps`: Total number of environment steps for training
- `n_steps`: Number of steps to run for each environment per update
- `eval_freq`: Frequency of evaluation during training
- `n_eval_episodes`: Number of episodes to run during evaluation
- `save_freq`: Frequency of model checkpointing
- `save_path`: Directory to save model checkpoints
- `log_path`: Directory to save training logs

## Project Structure

```
.
├── rl/
│   ├── train.py       # Training script
│   ├── env.py         # Trading environment
│   ├── agent.py       # PPO agent implementation
│   ├── memory.py      # Memory store
│   └── risk.py        # Risk manager
├── models/            # Saved model checkpoints
├── logs/             # Training logs
├── requirements.txt   # Project dependencies
└── README.md         # This file
```

## Monitoring Training

Training progress can be monitored through the logs directory, which contains:
- Training metrics (rewards, losses)
- Evaluation results
- Model checkpoints

## Contributing

Feel free to submit issues and enhancement requests! 