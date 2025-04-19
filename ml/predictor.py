import logging
import numpy as np
from typing import Optional
import joblib
import threading
from datetime import datetime, timedelta

from sklearn.base import BaseEstimator
from config.settings import settings
from feature_engineering.calculator import Features

logger = logging.getLogger(__name__)

class ModelPredictor:
    """Thread-safe wrapper for ML model predictions."""

    def __init__(self, model_path: str = str(settings.ml.model_path)):
        self.model_path = model_path
        self._model: Optional[BaseEstimator] = None
        self._lock = threading.Lock()
        self._last_load_time = None
        self.reload_interval = timedelta(
            seconds=settings.strategy_loop.model_reload_interval_seconds
        )
        self._load_model()

    def _load_model(self) -> None:
        """Load the model from disk."""
        try:
            self._model = joblib.load(self.model_path)
            self._last_load_time = datetime.now()
            logger.info(f"Loaded model from {self.model_path}")
        except Exception as e:
            logger.error(f"Failed to load model: {e}", exc_info=True)
            raise

    def reload_if_needed(self) -> None:
        """Reload the model if the reload interval has elapsed."""
        if (
            self._last_load_time is None or
            datetime.now() - self._last_load_time > self.reload_interval
        ):
            with self._lock:
                # Check again in case another thread reloaded while we were waiting
                if (
                    self._last_load_time is None or
                    datetime.now() - self._last_load_time > self.reload_interval
                ):
                    try:
                        self._load_model()
                    except Exception as e:
                        logger.error(
                            f"Failed to reload model, using existing: {e}",
                            exc_info=True
                        )

    def predict_proba(self, features: Features) -> float:
        """
        Get probability prediction for a single feature vector.
        
        Args:
            features: Features object containing all necessary features
            
        Returns:
            Probability of positive class (good entry point)
        """
        if self._model is None:
            raise RuntimeError("Model not loaded")

        # Convert features to the format expected by the model
        X = np.array([
            features.imbalance_1pct,
            features.depth_ratio,
            features.spread_bps,
            features.rsi_14,
            features.macd,
            features.macd_signal,
            features.macd_hist,
            features.bb_width,
            features.bb_pct,
            features.atr_14_pct,
            features.returns_1m,
            features.returns_5m,
            features.volatility_1h,
            features.volume_ma_ratio
        ]).reshape(1, -1)

        # Get prediction
        with self._lock:
            try:
                # Some models return probabilities for both classes
                proba = self._model.predict_proba(X)
                return float(proba[0, 1])  # Probability of positive class
            except Exception as e:
                logger.error(f"Prediction failed: {e}", exc_info=True)
                return 0.0

    def should_enter(
        self,
        features: Features,
        threshold: float = settings.ml.prediction_threshold
    ) -> bool:
        """
        Determine if we should enter a position based on model prediction.
        
        Args:
            features: Features object
            threshold: Minimum probability threshold for entry
            
        Returns:
            True if probability exceeds threshold
        """
        self.reload_if_needed()
        prob = self.predict_proba(features)
        return prob >= threshold 