"""
ML model performance monitoring.
"""

import logging
import os
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import json
import time

logger = logging.getLogger(__name__)

class PerformanceMonitor:
    """Monitor ML model performance metrics."""

    def __init__(self, feature_names: List[str] = None, 
                 metrics_dir: str = "logs/ml_metrics") -> None:
        """Initialize the performance monitor.
        
        Args:
            feature_names: List of feature names to track
            metrics_dir: Directory to store metrics
        """
        self.feature_names = feature_names or []
        self.metrics_dir = Path(metrics_dir)
        self.metrics_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize metrics storage
        self.predictions = []
        self.trades = []
        self.latencies = []
        self.features = []
        
        # Performance metrics
        self.accuracy = 0.0
        self.sharpe_ratio = 0.0
        self.profit_factor = 0.0
        
        # Trading metrics
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.avg_profit = 0.0
        self.avg_loss = 0.0
        self.total_profit = 0.0
        self.total_loss = 0.0
        self.max_drawdown = 0.0
        
        # Timing metrics
        self.last_update = datetime.now()
        self.start_time = datetime.now()
        
    def record_prediction(self, timestamp: datetime, features: Dict[str, float], 
                          prediction: Any, latency_ms: float) -> None:
        """Record a prediction.
        
        Args:
            timestamp: Time of prediction
            features: Dictionary of feature values
            prediction: Prediction output (can be any object with a signal attribute)
            latency_ms: Prediction latency in milliseconds
        """
        # Extract signal from prediction
        signal = getattr(prediction, 'signal', 0.0)
        if not isinstance(signal, (int, float)):
            signal = 0.0
            
        # Record prediction
        self.predictions.append({
            'timestamp': timestamp,
            'signal': signal,
            'latency_ms': latency_ms,
            'features': features,
        })
        
        # Record latency
        self.latencies.append(latency_ms)
        
        # Save features as a separate entry
        self.features.append({
            'timestamp': timestamp,
            **features
        })
        
        # Log prediction if debug enabled
        logger.debug(f"Prediction recorded: signal={signal:.4f}, latency={latency_ms:.2f}ms")
        
        # Update timestamp
        self.last_update = timestamp
    
    def record_trade(self, timestamp: datetime, fill: Any, prediction: Any) -> None:
        """Record a trade execution.
        
        Args:
            timestamp: Time of trade
            fill: Fill information (object with price, qty, side attributes)
            prediction: Prediction that led to this trade
        """
        try:
            # Extract values from fill
            price = getattr(fill, 'price', 0.0)
            qty = getattr(fill, 'qty', 0.0)
            side = getattr(fill, 'side', 'none')
            
            # Calculate PnL (placeholder, real PnL calculation would be more complex)
            pnl = 0.0
            if hasattr(fill, 'pnl'):
                pnl = getattr(fill, 'pnl')
            
            # Record trade
            self.trades.append({
                'timestamp': timestamp,
                'price': price,
                'qty': qty,
                'side': side,
                'pnl': pnl,
                'signal': getattr(prediction, 'signal', 0.0),
                'timestamp_diff_ms': (timestamp - self.last_update).total_seconds() * 1000
            })
            
            # Update trading metrics
            self.total_trades += 1
            if pnl > 0:
                self.winning_trades += 1
                self.total_profit += pnl
            else:
                self.losing_trades += 1
                self.total_loss += abs(pnl)
                
            # Log trade
            logger.info(f"Trade recorded: {side} {qty:.6f} @ {price:.2f}, PnL={pnl:.6f}")
            
            # Update timestamp
            self.last_update = timestamp
            
        except Exception as e:
            logger.error(f"Error recording trade: {e}")
    
    def update_metrics(self) -> None:
        """Update performance metrics based on recorded data."""
        try:
            # Calculate basic metrics
            self.avg_profit = self.total_profit / max(1, self.winning_trades)
            self.avg_loss = self.total_loss / max(1, self.losing_trades)
            
            # Calculate accuracy
            self.accuracy = self.winning_trades / max(1, self.total_trades)
            
            # Calculate profit factor
            self.profit_factor = self.total_profit / max(0.01, self.total_loss)
            
            # Calculate Sharpe ratio if we have enough trades
            if len(self.trades) > 10:
                # Extract PnL values
                pnls = [trade['pnl'] for trade in self.trades]
                
                # Calculate returns and Sharpe
                returns = np.array(pnls)
                mean_return = np.mean(returns)
                std_return = np.std(returns) + 1e-6  # Add small epsilon to prevent division by zero
                self.sharpe_ratio = mean_return / std_return * np.sqrt(252 * 24 * 60)  # Annualized assuming 1-minute bars
                
            # Calculate max drawdown
            if len(self.trades) > 0:
                # Calculate cumulative PnL
                cumulative_pnl = np.cumsum([trade['pnl'] for trade in self.trades])
                
                # Calculate max drawdown
                peak = np.maximum.accumulate(cumulative_pnl)
                drawdown = peak - cumulative_pnl
                self.max_drawdown = np.max(drawdown)
                
            logger.info(f"Updated metrics: accuracy={self.accuracy:.2f}, profit_factor={self.profit_factor:.2f}, sharpe={self.sharpe_ratio:.2f}")
            
        except Exception as e:
            logger.error(f"Error updating metrics: {e}")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current performance metrics.
        
        Returns:
            Dictionary of metrics
        """
        # Update metrics before returning
        self.update_metrics()
        
        return {
            'accuracy': self.accuracy,
            'sharpe_ratio': self.sharpe_ratio,
            'profit_factor': self.profit_factor,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'avg_profit': self.avg_profit,
            'avg_loss': self.avg_loss,
            'total_profit': self.total_profit,
            'total_loss': self.total_loss,
            'max_drawdown': self.max_drawdown,
            'avg_latency_ms': np.mean(self.latencies) if self.latencies else 0.0,
            'p95_latency_ms': np.percentile(self.latencies, 95) if self.latencies else 0.0,
            'uptime_minutes': (datetime.now() - self.start_time).total_seconds() / 60
        }
    
    def export_metrics(self, output_file: Path) -> None:
        """Export metrics to a file.
        
        Args:
            output_file: Path to output file
        """
        try:
            # Get current metrics
            metrics = self.get_metrics()
            
            # Add trade history summary (last 10 trades)
            last_trades = self.trades[-10:] if self.trades else []
            
            # Convert datetime objects to strings
            for trade in last_trades:
                trade['timestamp'] = trade['timestamp'].isoformat()
                
            metrics['recent_trades'] = last_trades
            
            # Save to file
            with open(output_file, 'w') as f:
                json.dump(metrics, f, indent=2)
                
            logger.info(f"Metrics exported to {output_file}")
            
        except Exception as e:
            logger.error(f"Error exporting metrics: {e}")
    
    def close(self) -> None:
        """Clean up resources."""
        try:
            # Export final metrics
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = self.metrics_dir / f"metrics_{timestamp}.json"
            self.export_metrics(output_file)
            
            logger.info("Performance monitor closed")
            
        except Exception as e:
            logger.error(f"Error closing performance monitor: {e}") 