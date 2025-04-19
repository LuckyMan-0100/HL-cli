#!/usr/bin/env python3
"""
Script for running the trading system in dry-run mode.
Simulates live trading without executing real orders.
"""

import os
import sys
import argparse
import logging
import time
from datetime import datetime, timedelta
import json
from typing import Dict, Any
import torch
import numpy as np
from dotenv import load_dotenv

from rl.environment import TradingEnvironment
from rl.agent import PPOAgent
from data_ingestion.memory_store import MemoryStore
from risk_management.risk_manager import RiskManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DryRunner:
    def __init__(
        self,
        symbol: str,
        model_path: str,
        memory_store: MemoryStore,
        risk_manager: RiskManager,
        update_interval: int = 60,  # seconds
        max_position_size: float = 1.0,
        transaction_fee: float = 0.001
    ):
        self.symbol = symbol
        self.update_interval = update_interval
        
        # Initialize environment
        self.env = TradingEnvironment(
            symbol=symbol,
            memory_store=memory_store,
            risk_manager=risk_manager,
            max_position_size=max_position_size,
            transaction_fee=transaction_fee
        )
        
        # Load agent
        self.agent = self._load_agent(model_path)
        
        # Initialize metrics
        self.metrics = {
            'total_pnl': 0.0,
            'total_trades': 0,
            'win_rate': 0.0,
            'avg_trade_duration': 0.0,
            'max_drawdown': 0.0,
            'sharpe_ratio': 0.0,
            'current_position': 0.0,
            'current_value': 0.0
        }
        
        self.trade_history = []
        self.position_start_time = None
        self.position_start_price = None
        
    def _load_agent(self, model_path: str) -> PPOAgent:
        """Load trained agent from disk."""
        try:
            agent = PPOAgent(
                state_dim=self.env.observation_space['book_features'].shape[1],
                action_dim=1
            )
            agent.load(model_path)
            logger.info(f"Loaded model from {model_path}")
            return agent
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            sys.exit(1)
            
    def _update_metrics(self, info: Dict[str, Any]) -> None:
        """Update trading metrics."""
        if 'trade' in info:
            trade = info['trade']
            self.trade_history.append(trade)
            
            # Update basic metrics
            self.metrics['total_trades'] += 1
            self.metrics['total_pnl'] += trade['pnl']
            
            # Calculate win rate
            winning_trades = sum(1 for t in self.trade_history if t['pnl'] > 0)
            self.metrics['win_rate'] = winning_trades / len(self.trade_history)
            
            # Calculate average trade duration
            durations = [t['duration'].total_seconds() for t in self.trade_history]
            self.metrics['avg_trade_duration'] = sum(durations) / len(durations)
            
            # Calculate max drawdown
            cumulative_pnl = np.cumsum([t['pnl'] for t in self.trade_history])
            max_drawdown = 0
            peak = float('-inf')
            for pnl in cumulative_pnl:
                peak = max(peak, pnl)
                drawdown = peak - pnl
                max_drawdown = max(max_drawdown, drawdown)
            self.metrics['max_drawdown'] = max_drawdown
            
            # Calculate Sharpe ratio (simplified)
            returns = [t['pnl'] for t in self.trade_history]
            if len(returns) > 1:
                returns_mean = np.mean(returns)
                returns_std = np.std(returns)
                if returns_std > 0:
                    self.metrics['sharpe_ratio'] = returns_mean / returns_std * np.sqrt(252)
        
        # Update current position and value
        self.metrics['current_position'] = info.get('position', 0.0)
        self.metrics['current_value'] = info.get('value', 0.0)
        
    def _save_metrics(self, metrics_file: str) -> None:
        """Save metrics to file."""
        try:
            with open(metrics_file, 'w') as f:
                json.dump(self.metrics, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")
            
    def run(self, metrics_file: str) -> None:
        """Run the dry-run loop."""
        logger.info(f"Starting dry-run for {self.symbol}")
        
        state, _ = self.env.reset()
        last_update = time.time()
        
        try:
            while True:
                current_time = time.time()
                
                # Check if it's time to update
                if current_time - last_update >= self.update_interval:
                    # Get action from agent
                    with torch.no_grad():
                        action = self.agent.get_action(state, deterministic=True)
                    
                    # Execute action
                    next_state, reward, done, truncated, info = self.env.step(action)
                    
                    # Update metrics
                    self._update_metrics(info)
                    
                    # Save metrics
                    self._save_metrics(metrics_file)
                    
                    # Log current state
                    logger.info(
                        f"Position: {self.metrics['current_position']:.3f}, "
                        f"Value: {self.metrics['current_value']:.2f}, "
                        f"Total PnL: {self.metrics['total_pnl']:.2f}"
                    )
                    
                    # Update state
                    state = next_state
                    last_update = current_time
                    
                    if done or truncated:
                        state, _ = self.env.reset()
                
                # Sleep to prevent high CPU usage
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Dry-run stopped by user")
        except Exception as e:
            logger.error(f"Error in dry-run loop: {e}")
        finally:
            # Save final metrics
            self._save_metrics(metrics_file)

def main():
    parser = argparse.ArgumentParser(description='Run trading system in dry-run mode')
    parser.add_argument('--symbol', type=str, required=True,
                      help='Trading symbol')
    parser.add_argument('--model-path', type=str, required=True,
                      help='Path to trained model')
    parser.add_argument('--update-interval', type=int, default=60,
                      help='Update interval in seconds')
    parser.add_argument('--max-position', type=float, default=1.0,
                      help='Maximum position size')
    parser.add_argument('--fee', type=float, default=0.001,
                      help='Transaction fee')
    parser.add_argument('--metrics-file', type=str, default='dry_run_metrics.json',
                      help='Path to save metrics')
    parser.add_argument('--env-file', type=str, default='.env',
                      help='Path to .env file')
    args = parser.parse_args()
    
    # Load environment variables
    load_dotenv(args.env_file)
    
    # Initialize components
    memory_store = MemoryStore()
    risk_manager = RiskManager()
    
    # Create dry runner
    runner = DryRunner(
        symbol=args.symbol,
        model_path=args.model_path,
        memory_store=memory_store,
        risk_manager=risk_manager,
        update_interval=args.update_interval,
        max_position_size=args.max_position,
        transaction_fee=args.fee
    )
    
    # Start dry-run
    runner.run(args.metrics_file)

if __name__ == '__main__':
    main() 