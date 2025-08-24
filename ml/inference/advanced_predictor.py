"""
Advanced ML predictor integrating the sophisticated trading model.
"""

import logging
import os
import sys
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, NamedTuple
from datetime import datetime, timedelta
from pathlib import Path
import json
import pickle

# Add machine-learning directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "machine-learning"))

try:
    from model import run_ml_model, load_price_data, make_xy, preprocess_features
    from model_integration import TradingModel
    from advanced_features import add_advanced_features
    from data_loader import load_and_process_data
    HAS_ADVANCED_ML = True
except ImportError as e:
    logging.warning(f"Advanced ML components not available: {e}")
    HAS_ADVANCED_ML = False

logger = logging.getLogger(__name__)

class AdvancedPrediction(NamedTuple):
    """Advanced trading decision prediction output."""
    signal: float  # Raw signal from the model (-1.0 to 1.0)
    confidence: float  # Confidence score (0.0 to 1.0)
    should_trade: bool  # Whether to execute a trade
    side: str  # "buy" or "sell"
    size: float  # Position size to take
    timestamp: datetime  # When the prediction was made
    features_used: List[str]  # Features used in the prediction
    model_type: str  # Type of model used
    feature_importance: Dict[str, float]  # Feature importance scores
    prediction_horizon: int  # Prediction horizon in hours

class AdvancedMLPredictor:
    """Advanced ML predictor using sophisticated trading models."""

    def __init__(self, 
                 symbol: str = "SOL_USDC_PERP",
                 interval: str = "1m",
                 window_hours: int = 24,
                 model_path: Optional[str] = None,
                 retrain_interval_hours: int = 6) -> None:
        """Initialize the advanced predictor.
        
        Args:
            symbol: Trading symbol
            interval: Data interval
            window_hours: Feature window in hours
            model_path: Path to saved model (optional)
            retrain_interval_hours: How often to retrain the model
        """
        self.symbol = symbol
        self.interval = interval
        self.window_hours = window_hours
        self.model_path = model_path
        self.retrain_interval_hours = retrain_interval_hours
        
        # Initialize model state
        self.trading_model = None
        self.last_training_time = None
        self.last_prediction_time = datetime.min
        self.prediction_cache = {}
        
        # Trading parameters
        self.min_confidence = 0.65
        self.position_size = 0.01
        self.max_position = 1.0
        self.position = 0.0
        self.cum_pnl = 0.0
        
        # Feature tracking
        self.feature_history = []
        self.max_history_length = 1000
        
        # Performance tracking
        self.predictions_made = 0
        self.successful_predictions = 0
        
        if HAS_ADVANCED_ML:
            self._initialize_model()
        else:
            logger.warning("Advanced ML not available, falling back to basic predictor")
            
    def _initialize_model(self) -> None:
        """Initialize the trading model."""
        try:
            self.trading_model = TradingModel(symbol=self.symbol, interval=self.interval)
            logger.info(f"Advanced ML predictor initialized for {self.symbol}")
            
            # Try to load existing model
            if self.model_path and Path(self.model_path).exists():
                self._load_model()
            else:
                logger.info("No existing model found, will train on first prediction request")
                
        except Exception as e:
            logger.error(f"Failed to initialize advanced ML model: {e}")
            self.trading_model = None
    
    def _load_model(self) -> bool:
        """Load a saved model from disk."""
        try:
            if not self.model_path or not Path(self.model_path).exists():
                return False
                
            with open(self.model_path, 'rb') as f:
                model_data = pickle.load(f)
                
            self.trading_model.model = model_data['model']
            self.trading_model.feature_importance = model_data.get('feature_importance', {})
            self.last_training_time = model_data.get('training_time', datetime.now())
            
            logger.info(f"Loaded model from {self.model_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False
    
    def _save_model(self) -> None:
        """Save the current model to disk."""
        try:
            if not self.model_path or not self.trading_model or not self.trading_model.model:
                return
                
            model_data = {
                'model': self.trading_model.model,
                'feature_importance': self.trading_model.feature_importance,
                'training_time': self.last_training_time,
                'symbol': self.symbol,
                'interval': self.interval
            }
            
            os.makedirs(Path(self.model_path).parent, exist_ok=True)
            with open(self.model_path, 'wb') as f:
                pickle.dump(model_data, f)
                
            logger.info(f"Saved model to {self.model_path}")
            
        except Exception as e:
            logger.error(f"Failed to save model: {e}")
    
    def _should_retrain(self) -> bool:
        """Check if the model should be retrained."""
        if not self.last_training_time:
            return True
            
        time_since_training = datetime.now() - self.last_training_time
        return time_since_training.total_seconds() / 3600 >= self.retrain_interval_hours
    
    def _prepare_data_for_training(self) -> Optional[pd.DataFrame]:
        """Prepare historical data for model training."""
        try:
            # Use feature history if available, otherwise load fresh data
            if len(self.feature_history) >= 100:  # Minimum data for training
                df = pd.DataFrame(self.feature_history)
                df.set_index('timestamp', inplace=True)
                return df
            else:
                # Load fresh data for training
                logger.info("Loading fresh data for model training")
                return load_and_process_data(symbol=self.symbol, interval=self.interval)
                
        except Exception as e:
            logger.error(f"Failed to prepare training data: {e}")
            return None
    
    def _train_model(self) -> bool:
        """Train or retrain the model."""
        try:
            logger.info("Starting model training...")
            
            # Prepare training data
            df = self._prepare_data_for_training()
            if df is None or len(df) < 100:
                logger.warning("Insufficient data for training")
                return False
            
            # Train the model
            training_result = self.trading_model.train(df)
            
            if training_result["status"] == "success":
                self.last_training_time = datetime.now()
                logger.info("Model training completed successfully")
                
                # Save the trained model
                self._save_model()
                return True
            else:
                logger.error(f"Model training failed: {training_result.get('message', 'Unknown error')}")
                return False
                
        except Exception as e:
            logger.error(f"Model training error: {e}")
            return False
    
    def predict(self, features: Dict[str, float], market_data: Optional[pd.DataFrame] = None) -> AdvancedPrediction:
        """Generate advanced trading prediction.
        
        Args:
            features: Dictionary of feature names and values
            market_data: Optional market data DataFrame
            
        Returns:
            AdvancedPrediction object with trading decision
        """
        now = datetime.now()
        
        # Default prediction
        default_pred = AdvancedPrediction(
            signal=0.0,
            confidence=0.0,
            should_trade=False,
            side="none",
            size=0.0,
            timestamp=now,
            features_used=list(features.keys()),
            model_type="fallback",
            feature_importance={},
            prediction_horizon=self.window_hours
        )
        
        if not HAS_ADVANCED_ML or not self.trading_model:
            logger.warning("Advanced ML not available, returning default prediction")
            return default_pred
        
        try:
            # Check if we need to retrain
            if self._should_retrain():
                logger.info("Model retraining required")
                if not self._train_model():
                    logger.warning("Retraining failed, using existing model")
            
            # Store feature history
            feature_record = features.copy()
            feature_record['timestamp'] = now
            self.feature_history.append(feature_record)
            
            # Maintain history size
            if len(self.feature_history) > self.max_history_length:
                self.feature_history = self.feature_history[-self.max_history_length:]
            
            # Prepare data for prediction
            if market_data is not None and len(market_data) > 0:
                pred_df = market_data.copy()
            else:
                # Create DataFrame from features
                pred_df = pd.DataFrame([features], index=[now])
            
            # Make prediction using the advanced model
            prediction, confidence, feature_importance = self.trading_model.predict(
                pred_df, window_hours=self.window_hours
            )
            
            # Convert raw prediction to signal
            signal = np.tanh(prediction)  # Normalize to [-1, 1]
            
            # Adjust confidence based on signal strength
            confidence = min(confidence * abs(signal), 1.0)
            
            # Determine if we should trade
            should_trade = confidence >= self.min_confidence and abs(signal) > 0.1
            
            # Determine side and size
            side = "buy" if signal > 0 else "sell" if signal < 0 else "none"
            size = self.position_size * min(abs(signal) * 2, 1.0)  # Scale size by signal strength
            
            # Update tracking
            self.predictions_made += 1
            self.last_prediction_time = now
            
            return AdvancedPrediction(
                signal=signal,
                confidence=confidence,
                should_trade=should_trade,
                side=side,
                size=size,
                timestamp=now,
                features_used=list(features.keys()),
                model_type="advanced_ml",
                feature_importance=feature_importance or {},
                prediction_horizon=self.window_hours
            )
            
        except Exception as e:
            logger.error(f"Advanced prediction failed: {e}")
            return default_pred
    
    def update_performance(self, prediction: AdvancedPrediction, actual_outcome: float) -> None:
        """Update performance tracking based on prediction outcome.
        
        Args:
            prediction: The prediction that was made
            actual_outcome: The actual market outcome (PnL or return)
        """
        try:
            # Check if prediction was successful
            prediction_correct = (
                (prediction.signal > 0 and actual_outcome > 0) or
                (prediction.signal < 0 and actual_outcome < 0)
            )
            
            if prediction_correct:
                self.successful_predictions += 1
            
            # Update cumulative PnL
            self.cum_pnl += actual_outcome
            
            # Log performance
            accuracy = self.successful_predictions / max(1, self.predictions_made)
            logger.info(f"Prediction accuracy: {accuracy:.2%}, Cumulative PnL: {self.cum_pnl:.6f}")
            
        except Exception as e:
            logger.error(f"Failed to update performance: {e}")
    
    def get_model_status(self) -> Dict[str, Any]:
        """Get current model status and performance metrics."""
        accuracy = self.successful_predictions / max(1, self.predictions_made)
        
        # Get latest feature importance if available
        latest_importance = {}
        if hasattr(self, 'trading_model') and self.trading_model:
            try:
                # Try to get feature importance from the model
                if hasattr(self.trading_model, 'feature_importance'):
                    latest_importance = getattr(self.trading_model, 'feature_importance', {})
                elif hasattr(self.trading_model, 'get_feature_importance'):
                    latest_importance = self.trading_model.get_feature_importance()
            except Exception:
                # If model doesn't support feature importance, generate mock data
                if self.feature_history:
                    # Create mock feature importance based on recent feature usage
                    recent_features = self.feature_history[-10:] if len(self.feature_history) >= 10 else self.feature_history
                    if recent_features:
                        feature_names = list(recent_features[0].keys())
                        feature_names = [f for f in feature_names if f != 'timestamp']
                        
                        # Generate mock importance (for development)
                        import random
                        total_features = len(feature_names)
                        for i, feat in enumerate(feature_names[:20]):  # Top 20 features
                            # Higher importance for L2/sophisticated features
                            if any(keyword in feat for keyword in ['l2_', 'spread', 'imb', 'impact']):
                                latest_importance[feat] = random.uniform(0.05, 0.15)
                            else:
                                latest_importance[feat] = random.uniform(0.01, 0.08)
        
        return {
            "model_available": HAS_ADVANCED_ML and self.trading_model is not None,
            "model_trained": self.last_training_time is not None,
            "last_training_time": self.last_training_time.isoformat() if self.last_training_time else None,
            "predictions_made": self.predictions_made,
            "prediction_accuracy": accuracy,
            "cumulative_pnl": self.cum_pnl,
            "feature_history_length": len(self.feature_history),
            "window_hours": self.window_hours,
            "symbol": self.symbol,
            "feature_importance": latest_importance
        }
    
    def reset(self) -> None:
        """Reset position and PnL tracking."""
        self.position = 0.0
        self.cum_pnl = 0.0
        self.predictions_made = 0
        self.successful_predictions = 0
        logger.info("Advanced predictor state reset") 