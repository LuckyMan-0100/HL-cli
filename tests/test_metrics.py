import numpy as np
import pytest
from ml.metrics import calculate_metrics, regime_aware_metric
from ml.model_evaluation import evaluate_model, evaluate_predictions
from sklearn.dummy import DummyClassifier

def test_metrics_empty_arrays():
    """Test metrics calculation with empty arrays"""
    metrics = calculate_metrics([], [])
    assert metrics['accuracy'] == 0.0
    assert metrics['precision'] == 0.0
    assert metrics['recall'] == 0.0
    assert metrics['f1'] == 0.0
    assert metrics['regime_aware_accuracy'] == 0.0

def test_metrics_single_value():
    """Test metrics calculation with single value"""
    metrics = calculate_metrics([1], [1])
    assert np.isclose(metrics['accuracy'], 1.0)
    assert np.isclose(metrics['precision'], 1.0)
    assert np.isclose(metrics['recall'], 1.0)
    assert np.isclose(metrics['f1'], 1.0)
    assert np.isclose(metrics['regime_aware_accuracy'], 1.0)

def test_metrics_nan_values():
    """Test metrics calculation with NaN values"""
    y_true = np.array([0, 1, np.nan, 1])
    y_pred = np.array([0, 1, 0, 1])
    metrics = calculate_metrics(y_true, y_pred)
    for metric in metrics.values():
        assert not np.isnan(metric)

def test_regime_aware_metric():
    """Test regime aware metric calculation"""
    y_true = np.array([0, 0, 1, 1, 0, 0])
    y_pred = np.array([0, 0, 1, 1, 0, 0])
    score = regime_aware_metric(y_true, y_pred)
    assert np.isclose(score, 1.0)

    # Test with mismatched predictions at regime changes
    y_pred = np.array([0, 0, 0, 1, 0, 0])
    score = regime_aware_metric(y_true, y_pred)
    assert score < 1.0

def test_evaluate_predictions():
    """Test prediction evaluation"""
    y_true = np.array([0, 1, 0, 1])
    y_pred = np.array([0, 1, 0, 1])
    metrics = evaluate_predictions(y_true, y_pred)
    assert np.isclose(metrics['accuracy'], 1.0)
    assert np.isclose(metrics['precision'], 1.0)
    assert np.isclose(metrics['recall'], 1.0)
    assert np.isclose(metrics['f1'], 1.0)
    assert np.isclose(metrics['regime_aware_accuracy'], 1.0)

def test_evaluate_model():
    """Test model evaluation using dummy classifier"""
    X = np.random.rand(100, 2)
    y = np.random.randint(0, 2, 100)
    model = DummyClassifier()
    metrics = evaluate_model(model, X, y)
    assert all(not np.isnan(v) for v in metrics.values())

def test_evaluate_model_edge_cases():
    """Test model evaluation with edge cases"""
    # Create more samples to satisfy TimeSeriesSplit requirements
    X = np.array([[1], [2], [3], [4], [5], [6]])
    y = np.array([0, 1, 0, 1, 0, 1])
    model = DummyClassifier()
    
    # Test with minimal data
    metrics = evaluate_model(model, X, y, n_splits=2)
    assert all(not np.isnan(v) for v in metrics.values())
    
    # Test with data containing NaN
    X_with_nan = np.array([[1], [2], [np.nan], [4], [5], [6]])
    metrics_nan = evaluate_model(model, X_with_nan, y, n_splits=2)
    assert all(not np.isnan(v) for v in metrics_nan.values()) 