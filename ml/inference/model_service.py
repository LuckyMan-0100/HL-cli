"""
Model service for managing ML model lifecycle.
"""

import logging
import os
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from pathlib import Path
import shutil
import json
import sys

# Add machine-learning directory to path so we can import its modules
ml_dir = Path(__file__).parent.parent.joinpath("machine-learning").resolve()
if ml_dir.exists() and str(ml_dir) not in sys.path:
    sys.path.append(str(ml_dir))

# Import from machine-learning directory
try:
    from model import make_xy
    from model_integration import TradingModel
except ImportError as e:
    logging.error(f"Error importing ML modules: {e}")
    raise

logger = logging.getLogger(__name__)

class ModelService:
    """Service for managing ML model lifecycle."""

    def __init__(self, models_dir: str = "ml/models") -> None:
        """Initialize the model service.
        
        Args:
            models_dir: Directory to store models
        """
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        self.trading_model = TradingModel()
        self.current_model_path = None
        self.feature_importance = {}
        self.last_training_time = None
        self.is_training = False
        
    def prepare_features(self, klines_df: pd.DataFrame, window_hours: int = 24) -> pd.DataFrame:
        """Prepare features for model inference.
        
        Args:
            klines_df: DataFrame with OHLCV data
            window_hours: Window size in hours
            
        Returns:
            DataFrame with features
        """
        try:
            # Ensure klines_df has expected columns
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in required_cols:
                if col not in klines_df.columns:
                    raise ValueError(f"Missing required column: {col}")
                    
            # Ensure klines_df has a DatetimeIndex
            if not isinstance(klines_df.index, pd.DatetimeIndex):
                if 'timestamp' in klines_df.columns:
                    klines_df['timestamp'] = pd.to_datetime(klines_df['timestamp'])
                    klines_df = klines_df.set_index('timestamp')
                else:
                    raise ValueError("DataFrame must have a DatetimeIndex or a 'timestamp' column")
                    
            # Ensure columns are numeric
            for col in required_cols:
                klines_df[col] = pd.to_numeric(klines_df[col], errors='coerce')
                
            # Add returns column if it doesn't exist
            if 'returns' not in klines_df.columns:
                klines_df['returns'] = klines_df['close'].pct_change().fillna(0)
                
            # Convert window_hours to bars assuming 1-minute bars
            window_bars = int(window_hours * 60)
            
            # Use make_xy from the ML code to generate features
            X, _ = make_xy(klines_df, window_bars)
            
            return X
        except Exception as e:
            logger.error(f"Error preparing features: {e}")
            return pd.DataFrame()
            
    def get_latest_features(self, klines_df: pd.DataFrame, window_hours: int = 24) -> Dict[str, float]:
        """Get the latest features for model inference.
        
        Args:
            klines_df: DataFrame with OHLCV data
            window_hours: Window size in hours
            
        Returns:
            Dictionary of feature name to value
        """
        X = self.prepare_features(klines_df, window_hours)
        if X.empty:
            return {}
            
        # Get the last row of features
        latest_features = X.iloc[-1].to_dict()
        return latest_features
        
    def save_model(self, model, name: str, metadata: Dict[str, Any] = None) -> str:
        """Save a model to disk.
        
        Args:
            model: The model to save
            name: Name for the model
            metadata: Additional metadata to save
            
        Returns:
            Path to the saved model
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            model_path = self.models_dir / f"{name}_{timestamp}.zip"
            
            # Save model
            model.save(str(model_path))
            
            # Save metadata if provided
            if metadata:
                metadata_path = self.models_dir / f"{name}_{timestamp}_metadata.json"
                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
                    
            logger.info(f"Model saved to {model_path}")
            return str(model_path)
            
        except Exception as e:
            logger.error(f"Error saving model: {e}")
            return ""
            
    async def train_model(self, klines_df: pd.DataFrame) -> Dict[str, Any]:
        """Train a new model.
        
        Args:
            klines_df: DataFrame with OHLCV data
            
        Returns:
            Dictionary with training results
        """
        if self.is_training:
            return {"status": "error", "message": "Training already in progress"}
            
        try:
            self.is_training = True
            
            # Use the trading_model to train
            results = self.trading_model.train(df=klines_df)
            
            if results["status"] == "success":
                self.feature_importance = results.get("feature_importance", {})
                self.last_training_time = datetime.now()
                
            self.is_training = False
            return results
            
        except Exception as e:
            logger.error(f"Error training model: {e}")
            self.is_training = False
            return {"status": "error", "message": str(e)}
            
    def load_model(self, model_path: str) -> bool:
        """Load a model from disk.
        
        Args:
            model_path: Path to the model
            
        Returns:
            True if successful, False otherwise
        """
        try:
            model_path = Path(model_path)
            if not model_path.exists():
                logger.error(f"Model file not found: {model_path}")
                return False
                
            # Import dynamically to avoid dependency issues
            if str(model_path).endswith(".zip"):
                try:
                    from stable_baselines3 import PPO
                    model = PPO.load(str(model_path))
                    self.current_model_path = str(model_path)
                    return True
                except ImportError:
                    logger.error("stable_baselines3 not installed, cannot load PPO model")
                    return False
            else:
                logger.error(f"Unsupported model format: {model_path}")
                return False
                
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            return False
            
    def get_model_status(self) -> Dict[str, Any]:
        """Get the current model status.
        
        Returns:
            Dictionary with model status
        """
        return {
            "model_loaded": self.current_model_path is not None,
            "model_path": self.current_model_path,
            "is_training": self.is_training,
            "last_training_time": self.last_training_time.isoformat() if self.last_training_time else None,
            "feature_importance": self.feature_importance
        } 