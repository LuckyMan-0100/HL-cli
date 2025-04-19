import logging
import numpy as np
import pandas as pd
from pathlib import Path
import joblib
from datetime import datetime, timedelta
from typing import Tuple, Dict, List

from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, roc_auc_score, confusion_matrix
)

from config.settings import settings
from data_ingestion.db_writer import PostgresWriter
from feature_engineering.calculator import FeatureCalculator
from feature_engineering.labelling import prepare_training_data, analyze_label_distribution

logger = logging.getLogger(__name__)

class ModelEvaluator:
    def __init__(
        self,
        model_dir: Path = settings.ml.model_path.parent,
        threshold: float = 0.5
    ):
        """
        Initialize model evaluator.
        
        Args:
            model_dir: Directory containing model artifacts
            threshold: Probability threshold for trade entry
        """
        self.model_dir = model_dir
        self.threshold = threshold
        self.model = None
        self.scaler = None
        self.metrics = None
        
        self._load_artifacts()
    
    def _load_artifacts(self):
        """Load model and associated artifacts."""
        try:
            model_path = self.model_dir / "boosting_model.joblib"
            scaler_path = self.model_dir / "feature_scaler.joblib"
            metrics_path = self.model_dir / "model_metrics.joblib"
            
            self.model = joblib.load(model_path)
            self.scaler = joblib.load(scaler_path)
            self.metrics = joblib.load(metrics_path)
            
            logger.info("Loaded model artifacts successfully")
            
        except Exception as e:
            logger.error(f"Failed to load model artifacts: {e}")
            raise
    
    def evaluate_period(
        self,
        db_writer: PostgresWriter,
        start_time: datetime,
        end_time: datetime,
        symbol: str = settings.trading.symbol,
        interval: str = "1m"
    ) -> Dict:
        """
        Evaluate model performance over a specific time period.
        
        Args:
            db_writer: Database connection
            start_time: Start of evaluation period
            end_time: End of evaluation period
            symbol: Trading symbol
            interval: Kline interval
            
        Returns:
            Dictionary containing evaluation metrics and trade statistics
        """
        # Get historical data
        klines = db_writer.get_klines_in_range(
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time
        )
        
        if not klines:
            raise ValueError("No data available for specified period")
        
        # Calculate features
        calculator = FeatureCalculator()
        features_list = []
        timestamps = []
        
        for i in range(len(klines)):
            if i < 60:  # Need enough bars for all features
                continue
                
            window = klines[max(0, i-60):i+1]
            features = calculator.calculate_features(
                orderbook=None,
                klines=window
            )
            features_list.append(calculator.features_to_array(features))
            timestamps.append(klines[i].timestamp)
        
        # Convert to DataFrame
        feature_names = [
            'imbalance_1pct', 'depth_ratio', 'spread_bps',
            'rsi_14', 'macd', 'macd_signal', 'macd_hist',
            'bb_width', 'bb_pct', 'atr_14_pct',
            'returns_1m', 'returns_5m', 'volatility_1h',
            'volume_ma_ratio'
        ]
        
        X = pd.DataFrame(
            features_list,
            columns=feature_names,
            index=pd.DatetimeIndex(timestamps)
        )
        
        # Generate labels for performance evaluation
        X_eval, y_true = prepare_training_data(
            klines=klines[60:],
            features=X,
            look_forward=10,
            entry_bar_offset=6,
            profit_target_bps=50.0,
            stop_loss_bps=30.0
        )
        
        # Make predictions
        X_scaled = self.scaler.transform(X_eval)
        y_pred_proba = self.model.predict_proba(X_scaled)[:, 1]
        y_pred = (y_pred_proba >= self.threshold).astype(int)
        
        # Calculate metrics
        metrics = {
            'accuracy': accuracy_score(y_true, y_pred),
            'precision': precision_score(y_true, y_pred),
            'recall': recall_score(y_true, y_pred),
            'f1': f1_score(y_true, y_pred),
            'roc_auc': roc_auc_score(y_true, y_pred_proba),
            'confusion_matrix': confusion_matrix(y_true, y_pred).tolist()
        }
        
        # Calculate trade statistics
        trade_stats = self._calculate_trade_stats(
            y_true=y_true,
            y_pred=y_pred,
            timestamps=X_eval.index
        )
        
        return {
            'metrics': metrics,
            'trade_stats': trade_stats,
            'predictions': pd.DataFrame({
                'timestamp': X_eval.index,
                'probability': y_pred_proba,
                'predicted': y_pred,
                'actual': y_true
            })
        }
    
    def _calculate_trade_stats(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        timestamps: pd.DatetimeIndex
    ) -> Dict:
        """
        Calculate trading statistics.
        
        Args:
            y_true: True labels
            y_pred: Predicted labels
            timestamps: Timestamps for each prediction
            
        Returns:
            Dictionary of trading statistics
        """
        total_trades = np.sum(y_pred)
        correct_trades = np.sum((y_pred == 1) & (y_true == 1))
        incorrect_trades = np.sum((y_pred == 1) & (y_true == 0))
        
        # Calculate trade timing metrics
        trade_times = timestamps[y_pred == 1]
        trade_gaps = pd.Series(trade_times).diff()
        
        stats = {
            'total_trades': int(total_trades),
            'correct_trades': int(correct_trades),
            'incorrect_trades': int(incorrect_trades),
            'win_rate': float(correct_trades / total_trades if total_trades > 0 else 0),
            'avg_trades_per_day': float(total_trades / ((timestamps[-1] - timestamps[0]).days + 1)),
            'avg_time_between_trades': str(trade_gaps.mean()) if len(trade_gaps) > 1 else "N/A",
            'median_time_between_trades': str(trade_gaps.median()) if len(trade_gaps) > 1 else "N/A"
        }
        
        return stats

def main():
    """Main evaluation script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        # Initialize evaluator
        evaluator = ModelEvaluator()
        
        # Set evaluation period (last 30 days)
        end_time = datetime.now()
        start_time = end_time - timedelta(days=30)
        
        # Run evaluation
        db_writer = PostgresWriter()
        results = evaluator.evaluate_period(
            db_writer=db_writer,
            start_time=start_time,
            end_time=end_time
        )
        
        # Log results
        logger.info("Evaluation Results:")
        logger.info(f"Metrics: {results['metrics']}")
        logger.info(f"Trade Stats: {results['trade_stats']}")
        
        # Save predictions to CSV
        output_dir = settings.ml.model_path.parent / "evaluation"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        predictions_path = output_dir / f"predictions_{start_time.strftime('%Y%m%d')}_{end_time.strftime('%Y%m%d')}.csv"
        results['predictions'].to_csv(predictions_path)
        logger.info(f"Saved predictions to {predictions_path}")
        
    except Exception as e:
        logger.error(f"Evaluation failed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main() 