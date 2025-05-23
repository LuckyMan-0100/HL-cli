# ML Integration

This module integrates machine learning models into the high-frequency trading system, enabling model-driven trading decisions.

## Structure

- `inference/`: Contains code for model inference and prediction
- `monitoring/`: Contains code for monitoring model performance
- `models/`: Storage directory for trained models
- `utils/`: Utility functions for ML integration
- `machine-learning/`: Submodule containing the ML model code

## Quick Start

To run paper trading with ML integration:

```bash
# Install dependencies
pip install -r requirements.txt

# Set up ML environment
python ml/setup_ml.py

# Run paper trading with ML
python ml/run_ml_integration.py
```

## Components

### Model Predictor

The `ModelPredictor` class in `inference/predictor.py` is responsible for loading ML models and generating predictions. It supports:

- PPO reinforcement learning models
- Feature extraction and preprocessing
- Trading signal generation

### Performance Monitoring

The `PerformanceMonitor` class in `monitoring/performance_monitor.py` tracks model performance metrics:

- Prediction accuracy
- Trading P&L
- Model latency
- Sharpe ratio and other key metrics

### Feature Drift Detection

The `FeatureMonitor` class in `feature_engineering/feature_monitor.py` monitors features for drift:

- Baseline statistics computation
- Z-score based drift detection
- Feature distribution monitoring

## Usage

### Paper Trading

```bash
# Run with ML model (default)
python run_paper_trading.py

# Run without ML model
python run_paper_trading.py --no-ml

# Run for specific duration
python run_paper_trading.py --days=0.5
```

### Live Trading (Future)

```bash
# Not yet implemented
```

## Parameters

Key parameters are configured through environment variables in the `.env` file:

- `ML_MODEL_PATH`: Path to the trained model file
- `ML_WINDOW_HOURS`: Window size for feature calculation
- `ML_CONFIDENCE_THRESHOLD`: Minimum confidence for executing trades 