import logging
import numpy as np
import pandas as pd
from pathlib import Path
import joblib
from datetime import datetime, timedelta
from typing import Dict, Optional, List

from config.settings import settings
from data_ingestion.db_writer import PostgresWriter
from feature_engineering.calculator import FeatureCalculator

logger = logging.getLogger(__name__)

class SignalGenerator:
    def __init__(
        self,
        model_dir: Path = settings.ml.model_path.parent,
        threshold: float = 0.5,
        cooldown_minutes: int = 30
    ):
        """
        Initialize signal generator.
        
        Args:
            model_dir: Directory containing model artifacts
            threshold: Probability threshold for trade entry
            cooldown_minutes: Minimum minutes between signals
        """
        self.model_dir = model_dir
        self.threshold = threshold
        self.cooldown_minutes = cooldown_minutes
        self.model = None
        self.scaler = None
        self.last_signal_time = None
        
        self._load_artifacts()
        
    def _load_artifacts(self):
        """Load model and associated artifacts."""
        try:
            model_path = self.model_dir / "boosting_model.joblib"
            scaler_path = self.model_dir / "feature_scaler.joblib"
            
            self.model = joblib.load(model_path)
            self.scaler = joblib.load(scaler_path)
            
            logger.info("Loaded model artifacts successfully")
            
        except Exception as e:
            logger.error(f"Failed to load model artifacts: {e}")
            raise
            
    def generate_signal(
        self,
        klines: List[Dict],
        orderbook: Optional[Dict] = None
    ) -> Dict:
        """
        Generate trading signal from current market data.
        
        Args:
            klines: List of recent kline data
            orderbook: Current orderbook snapshot (optional)
            
        Returns:
            Dictionary containing signal information
        """
        # Check cooldown period
        current_time = datetime.now()
        if (
            self.last_signal_time is not None and
            (current_time - self.last_signal_time).total_seconds() < self.cooldown_minutes * 60
        ):
            return {
                'signal': 0,
                'probability': 0.0,
                'timestamp': current_time,
                'reason': 'Cooldown period active'
            }
            
        # Need minimum number of klines for feature calculation
        if len(klines) < 60:
            return {
                'signal': 0,
                'probability': 0.0,
                'timestamp': current_time,
                'reason': 'Insufficient historical data'
            }
            
        try:
            # Calculate features
            calculator = FeatureCalculator()
            features = calculator.calculate_features(
                orderbook=orderbook,
                klines=klines[-60:]  # Use last 60 klines
            )
            
            # Convert features to array format
            feature_array = calculator.features_to_array(features)
            
            # Scale features
            X = self.scaler.transform(feature_array.reshape(1, -1))
            
            # Generate prediction
            probability = float(self.model.predict_proba(X)[0, 1])
            signal = int(probability >= self.threshold)
            
            # Update last signal time if generating signal
            if signal == 1:
                self.last_signal_time = current_time
            
            return {
                'signal': signal,
                'probability': probability,
                'timestamp': current_time,
                'reason': 'Signal generated successfully'
            }
            
        except Exception as e:
            logger.error(f"Error generating signal: {e}")
            return {
                'signal': 0,
                'probability': 0.0,
                'timestamp': current_time,
                'reason': f'Error: {str(e)}'
            }
            
    def reset_cooldown(self):
        """Reset the signal cooldown timer."""
        self.last_signal_time = None
        logger.info("Reset signal cooldown timer")

def main():
    """Example usage of signal generator."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        # Initialize components
        generator = SignalGenerator()
        db_writer = PostgresWriter()
        
        # Get recent klines for testing
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=2)
        
        klines = db_writer.get_klines_in_range(
            symbol=settings.trading.symbol,
            interval="1m",
            start_time=start_time,
            end_time=end_time
        )
        
        if not klines:
            raise ValueError("No recent klines available")
            
        # Generate test signal
        signal = generator.generate_signal(klines=klines)
        
        logger.info(f"Generated signal: {signal}")
        
    except Exception as e:
        logger.error(f"Signal generation test failed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main() 