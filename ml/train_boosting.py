import logging
import numpy as np
import pandas as pd
from typing import Tuple, Optional
from pathlib import Path
import joblib
from datetime import datetime, timedelta

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, roc_auc_score, confusion_matrix
)
import optuna
from lightgbm import LGBMClassifier

from config.settings import settings
from data_ingestion.db_writer import PostgresWriter
from feature_engineering.calculator import FeatureCalculator
from feature_engineering.labelling import prepare_training_data, analyze_label_distribution

logger = logging.getLogger(__name__)

def load_training_data(
    db_writer: PostgresWriter,
    symbol: str = settings.trading.symbol,
    interval: str = "1m",
    lookback_days: int = 90
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Load and prepare training data from the database.
    
    Args:
        db_writer: Database connection
        symbol: Trading symbol
        interval: Kline interval
        lookback_days: Number of days of historical data to use
        
    Returns:
        X: Feature matrix
        y: Target labels
    """
    # Get historical klines
    end_time = datetime.now()
    start_time = end_time - timedelta(days=lookback_days)
    
    klines = db_writer.get_latest_klines(
        symbol=symbol,
        interval=interval,
        limit=int(lookback_days * 24 * 60)  # Approximate number of 1m klines
    )
    
    if not klines:
        raise ValueError("No historical data available")
    
    # Calculate features
    calculator = FeatureCalculator()
    features_list = []
    
    for i in range(len(klines)):
        if i < 60:  # Need enough bars for all features
            continue
            
        # Use a window of recent klines for feature calculation
        window = klines[max(0, i-60):i+1]
        features = calculator.calculate_features(
            orderbook=None,  # Historical order book not available
            klines=window
        )
        features_list.append(calculator.features_to_array(features))
    
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
        index=pd.DatetimeIndex([k.timestamp for k in klines[60:]])
    )
    
    # Prepare labels
    X, y = prepare_training_data(
        klines=klines[60:],
        features=X,
        look_forward=10,
        entry_bar_offset=6,
        profit_target_bps=50.0,
        stop_loss_bps=30.0
    )
    
    return X, y

def objective(
    trial: optuna.Trial,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray
) -> float:
    """
    Optuna objective function for hyperparameter optimization.
    
    Args:
        trial: Optuna trial object
        X_train: Training features
        y_train: Training labels
        X_val: Validation features
        y_val: Validation labels
        
    Returns:
        Validation metric to optimize
    """
    param = {
        'objective': 'binary',
        'metric': 'auc',
        'verbosity': -1,
        'boosting_type': 'gbdt',
        'n_estimators': trial.suggest_int('n_estimators', 100, 1000),
        'learning_rate': trial.suggest_float('learning_rate', 1e-3, 0.1, log=True),
        'num_leaves': trial.suggest_int('num_leaves', 16, 256),
        'max_depth': trial.suggest_int('max_depth', 3, 12),
        'min_child_samples': trial.suggest_int('min_child_samples', 10, 100),
        'subsample': trial.suggest_float('subsample', 0.6, 1.0),
        'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
        'reg_alpha': trial.suggest_float('reg_alpha', 1e-8, 10.0, log=True),
        'reg_lambda': trial.suggest_float('reg_lambda', 1e-8, 10.0, log=True),
    }
    
    model = LGBMClassifier(**param)
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        early_stopping_rounds=50,
        verbose=False
    )
    
    y_pred_proba = model.predict_proba(X_val)[:, 1]
    return roc_auc_score(y_val, y_pred_proba)

def train_model(
    X: pd.DataFrame,
    y: pd.Series,
    n_trials: int = 100,
    random_state: int = 42
) -> Tuple[LGBMClassifier, StandardScaler, dict]:
    """
    Train and optimize the model.
    
    Args:
        X: Feature matrix
        y: Target labels
        n_trials: Number of optimization trials
        random_state: Random seed
        
    Returns:
        Best model and its metrics
    """
    # Train/validation split
    X_train, X_val, y_train, y_val = train_test_split(
        X, y,
        test_size=0.2,
        shuffle=False  # Time series data
    )
    
    # Scale features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    
    # Optimize hyperparameters
    study = optuna.create_study(direction='maximize')
    study.optimize(
        lambda trial: objective(
            trial, X_train_scaled, y_train, X_val_scaled, y_val
        ),
        n_trials=n_trials
    )
    
    # Train final model with best parameters
    best_params = study.best_params
    best_params.update({
        'objective': 'binary',
        'metric': 'auc',
        'verbosity': -1,
        'boosting_type': 'gbdt'
    })
    
    model = LGBMClassifier(**best_params)
    model.fit(
        X_train_scaled, y_train,
        eval_set=[(X_val_scaled, y_val)],
        early_stopping_rounds=50,
        verbose=False
    )
    
    # Calculate metrics
    y_pred = model.predict(X_val_scaled)
    y_pred_proba = model.predict_proba(X_val_scaled)[:, 1]
    
    metrics = {
        'accuracy': accuracy_score(y_val, y_pred),
        'precision': precision_score(y_val, y_pred),
        'recall': recall_score(y_val, y_pred),
        'f1': f1_score(y_val, y_pred),
        'roc_auc': roc_auc_score(y_val, y_pred_proba),
        'confusion_matrix': confusion_matrix(y_val, y_pred).tolist(),
        'feature_importance': dict(zip(X.columns, model.feature_importances_)),
        'best_params': best_params
    }
    
    return model, scaler, metrics

def save_model(
    model: LGBMClassifier,
    scaler: StandardScaler,
    metrics: dict,
    model_dir: Path = settings.ml.model_path.parent
):
    """
    Save the trained model and associated artifacts.
    
    Args:
        model: Trained model
        scaler: Fitted feature scaler
        metrics: Model metrics
        model_dir: Directory to save artifacts
    """
    # Create model directory if it doesn't exist
    model_dir.mkdir(parents=True, exist_ok=True)
    
    # Save model
    model_path = model_dir / "boosting_model.joblib"
    joblib.dump(model, model_path)
    
    # Save scaler
    scaler_path = model_dir / "feature_scaler.joblib"
    joblib.dump(scaler, scaler_path)
    
    # Save metrics
    metrics_path = model_dir / "model_metrics.joblib"
    joblib.dump(metrics, metrics_path)
    
    logger.info(f"Saved model artifacts to {model_dir}")
    logger.info(f"Model metrics: {metrics}")

def main():
    """Main training script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        # Load data
        db_writer = PostgresWriter()
        X, y = load_training_data(db_writer)
        
        # Analyze label distribution
        label_stats = analyze_label_distribution(y)
        logger.info(f"Label distribution:\n{label_stats}")
        
        # Train model
        model, scaler, metrics = train_model(X, y)
        
        # Save artifacts
        save_model(model, scaler, metrics)
        
        logger.info("Training completed successfully")
        
    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main() 