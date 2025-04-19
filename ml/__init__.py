"""
ML sub‑package public interface.

Importing `ml` gives quick access to the predictor, trainer and
evaluation tooling without digging into module paths.
"""

from .predictor import ModelPredictor
from .signal_generator import SignalGenerator
from .evaluate import ModelEvaluator
from .train_boosting import train_model, save_model

__all__ = [
    "ModelPredictor",
    "SignalGenerator",
    "ModelEvaluator",
    "train_model",
    "save_model",
]