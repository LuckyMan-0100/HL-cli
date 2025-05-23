"""
Model predictor for ML-based trading decisions.
"""

import logging
import os
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, NamedTuple
from datetime import datetime
from pathlib import Path
import json
import random

try:
    from stable_baselines3 import PPO
except ImportError:
    logging.warning("stable_baselines3 not found, RL model functionality will be limited")

logger = logging.getLogger(__name__)

class Prediction(NamedTuple):
    """Trading decision prediction output."""
    signal: float  # Raw signal from the model (-1.0 to 1.0)
    confidence: float  # Confidence score (0.0 to 1.0)
    should_trade: bool  # Whether to execute a trade
    side: str  # "buy" or "sell"
    size: float  # Position size to take
    timestamp: datetime  # When the prediction was made
    features_used: List[str]  # Features used in the prediction


class ModelPredictor:
    """Inference engine for ML trading models."""

    def __init__(self, model_path: Optional[str] = None) -> None:
        """Initialize the predictor.
        
        Args:
            model_path: Path to the model file. If None, will use environment variable ML_MODEL_PATH
                or default to 'ml/models/ppo_trading_agent_24h.zip'
        """
        self.model = None
        self.model_type = "none"  # Options: "none", "ppo", "lightgbm", "metadata"
        self.features_used = []
        self.position = 0.0  # Current position (-1.0 to 1.0)
        self.cum_pnl = 0.0  # Cumulative PnL
        self.min_confidence = 0.6  # Minimum confidence to trade
        self.position_size = 0.01  # Default position size in BTC (or fixed amount)
        self.max_position = 1.0  # Maximum position size (in BTC or asset)
        self.last_prediction_time = datetime.min
        
        # Load model if path provided
        if model_path is None:
            model_path = os.environ.get("ML_MODEL_PATH", "ml/models/ppo_trading_agent_24h.zip")
        
        self.model_path = model_path
        self._try_load_model()
    
    def _try_load_model(self) -> bool:
        """Try to load the model if it exists."""
        try:
            model_path = Path(self.model_path)
            if not model_path.exists():
                logger.warning(f"Model file not found: {self.model_path}")
                return False
                
            # Determine model type from extension
            if str(model_path).endswith(".zip"):
                # Load PPO model
                logger.info(f"Loading PPO model from {self.model_path}")
                try:
                    self.model = PPO.load(self.model_path)
                    self.model_type = "ppo"
                    # PPO uses normalized features and position tracking
                    self.features_used = ["rsi", "macd", "vol_1m", "ret_1m", "ret_5m", 
                                         "spread_bps", "vol_imb_L1", "vol_imb_L3"]
                    return True
                except Exception as e:
                    logger.error(f"Failed to load PPO model: {e}")
                    # Fall back to metadata mode
                    self.model_type = "metadata"
                    return self._load_metadata_fallback()
                
            elif str(model_path).endswith(".json") or str(model_path).endswith(".txt"):
                # Could be metadata about features or a simple JSON-based model
                return self._load_metadata_fallback()
                
            else:
                logger.warning(f"Unsupported model format: {self.model_path}")
                return False
                
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            return False
            
    def _load_metadata_fallback(self) -> bool:
        """Load model metadata as a fallback when no model is available."""
        try:
            with open(self.model_path, 'r') as f:
                model_info = json.load(f)
                
                # Extract features
                if "features" in model_info:
                    self.features_used = model_info["features"]
                    
                # Extract other parameters
                if "window_hours" in model_info:
                    self.window_hours = model_info["window_hours"]
                    
                # Set model type to metadata
                self.model_type = "metadata"
                
                logger.info(f"Loaded model metadata from {self.model_path}")
                return True
        except Exception as e:
            logger.error(f"Failed to load metadata: {e}")
            return False

    def predict(self, features: Dict[str, float]) -> Prediction:
        """Generate a trading prediction based on input features.
        
        Args:
            features: Dictionary of feature names and values
            
        Returns:
            Prediction object with trading decision
        """
        now = datetime.now()
        
        # Default neutral prediction
        default_pred = Prediction(
            signal=0.0,
            confidence=0.0,
            should_trade=False,
            side="none",
            size=0.0,
            timestamp=now,
            features_used=self.features_used
        )
        
        try:
            # Format features based on model type
            if self.model_type == "ppo" and self.model is not None:
                # For PPO, we need to create the observation vector
                # First extract features in the right order
                feature_vector = []
                for feat in self.features_used:
                    if feat in features:
                        feature_vector.append(features[feat])
                    else:
                        logger.warning(f"Missing feature: {feat}")
                        feature_vector.append(0.0)  # Default value
                
                # Add current position and PnL to observation
                obs = np.array(feature_vector + [self.position, self.cum_pnl], dtype=np.float32)
                
                # Get raw action from model 
                action, _states = self.model.predict(obs, deterministic=True)
                signal = float(action[0])  # Raw signal -1.0 to 1.0
                
                # Calculate confidence based on signal strength
                confidence = abs(signal)
                
                # Determine if we should trade
                should_trade = confidence >= self.min_confidence
                
                # Determine side and size
                side = "buy" if signal > 0 else "sell"
                size = self.position_size
                
                # Update position tracking
                if should_trade:
                    self.position = max(min(self.position + signal, self.max_position), -self.max_position)
                
                return Prediction(
                    signal=signal,
                    confidence=confidence,
                    should_trade=should_trade,
                    side=side,
                    size=size,
                    timestamp=now,
                    features_used=self.features_used
                )
                
            elif self.model_type == "metadata":
                # In metadata mode, we generate synthetic predictions based on feature values
                # This is useful for testing the system without a real model
                
                # Use RSI as a simple trading signal if available
                rsi_value = features.get('rsi', 50.0)
                
                # Normalize to [-1, 1]
                if rsi_value < 30:
                    # Oversold - buy signal
                    signal = min((30 - rsi_value) / 30, 1.0)
                elif rsi_value > 70:
                    # Overbought - sell signal
                    signal = max((70 - rsi_value) / 30, -1.0)
                else:
                    # Neutral zone - small random signal
                    signal = random.uniform(-0.3, 0.3)
                
                # Calculate confidence based on signal strength
                confidence = abs(signal)
                
                # Determine if we should trade
                should_trade = confidence >= self.min_confidence
                
                # Determine side and size
                side = "buy" if signal > 0 else "sell"
                size = self.position_size
                
                # Update position tracking
                if should_trade:
                    self.position = max(min(self.position + signal, self.max_position), -self.max_position)
                
                return Prediction(
                    signal=signal,
                    confidence=confidence,
                    should_trade=should_trade,
                    side=side,
                    size=size,
                    timestamp=now,
                    features_used=self.features_used
                )
                
            else:
                # Unknown model type or no model loaded
                # Generate baseline signals
                
                # Pick a random feature for signal generation
                if features and self.features_used:
                    # Use a feature if available
                    for feature in self.features_used:
                        if feature in features:
                            # Normalize to [-0.5, 0.5] and add small noise
                            value = features[feature]
                            if isinstance(value, (int, float)) and not np.isnan(value):
                                # Simple Z-score normalization
                                signal = (value - 0) / (1.0 + abs(value)) * 0.5
                                signal += random.uniform(-0.2, 0.2)  # Add noise
                                signal = max(min(signal, 1.0), -1.0)  # Clamp to [-1, 1]
                                break
                    else:
                        # No valid features found, use small random signal
                        signal = random.uniform(-0.2, 0.2)
                else:
                    # No features available, use very small random signal
                    signal = random.uniform(-0.1, 0.1)
                
                # Low confidence for baseline predictions
                confidence = abs(signal) * 0.5
                
                # Determine if we should trade (lower threshold for baseline)
                should_trade = confidence >= 0.4  # Lower threshold 
                
                # Determine side and size
                side = "buy" if signal > 0 else "sell"
                size = self.position_size * 0.5  # Smaller size for baseline predictions
                
                return Prediction(
                    signal=signal,
                    confidence=confidence,
                    should_trade=should_trade,
                    side=side,
                    size=size,
                    timestamp=now,
                    features_used=self.features_used
                )
                
        except Exception as e:
            logger.error(f"Error making prediction: {e}")
            return default_pred
            
    def update_pnl(self, pnl_change: float) -> None:
        """Update cumulative PnL after a trade.
        
        Args:
            pnl_change: Change in PnL
        """
        self.cum_pnl += pnl_change
        
    def reset(self) -> None:
        """Reset position and PnL tracking."""
        self.position = 0.0
        self.cum_pnl = 0.0 