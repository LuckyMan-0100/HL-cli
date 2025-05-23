import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from feature_engineering.validation import FeatureValidator, ValidationError

@pytest.fixture
def sample_data():
    np.random.seed(42)
    return pd.DataFrame({
        'price': np.random.uniform(10, 1000, 100),
        'quantity': np.random.randint(1, 100, 100),
        'discount': np.random.uniform(0, 0.5, 100),
        'total_amount': None,  # Will be calculated
        'timestamp': pd.date_range(start='2023-01-01', periods=100, freq='D'),
        'age': np.random.randint(18, 90, 100)
    })

@pytest.fixture
def config_path(tmp_path):
    config = {
        "null_threshold": 0.1,
        "numeric_bounds": {
            "price": {"min": 0, "max": 1000},
            "quantity": {"min": 0, "max": 100},
            "age": {"min": 0, "max": 150}
        },
        "correlation_threshold": 0.95,
        "stationarity_threshold": 0.05,
        "feature_groups": {
            "price_related": {
                "features": ["price", "discount", "total_amount"],
                "rules": {
                    "total_amount": "price * (1 - discount)"
                }
            }
        },
        "alert_thresholds": {
            "missing_data_ratio": 0.2,
            "outlier_zscore": 3.0,
            "variance_threshold": 0.01
        }
    }
    config_file = tmp_path / "test_config.json"
    import json
    with open(config_file, 'w') as f:
        json.dump(config, f)
    return config_file

def test_validator_initialization(config_path):
    validator = FeatureValidator(config_path)
    assert validator.config is not None
    assert "null_threshold" in validator.config

def test_null_validation(config_path, sample_data):
    validator = FeatureValidator(config_path)
    # Introduce some null values
    sample_data.loc[0:9, 'price'] = None
    results = validator.validate_nulls(sample_data)
    assert 'price' in results
    assert results['price']['null_ratio'] == 0.1

def test_numeric_bounds_validation(config_path, sample_data):
    validator = FeatureValidator(config_path)
    # Introduce out-of-bounds values
    sample_data.loc[0, 'price'] = -10
    results = validator.validate_numeric_bounds(sample_data)
    assert 'price' in results
    assert not results['price']['within_bounds']

def test_correlation_validation(config_path, sample_data):
    validator = FeatureValidator(config_path)
    # Create highly correlated features
    sample_data['price_copy'] = sample_data['price'] * 1.1
    results = validator.validate_correlations(sample_data)
    assert ('price', 'price_copy') in str(results)

def test_feature_group_validation(config_path, sample_data):
    validator = FeatureValidator(config_path)
    # Calculate total_amount according to the rule
    sample_data['total_amount'] = sample_data['price'] * (1 - sample_data['discount'])
    results = validator.validate_feature_groups(sample_data)
    assert 'price_related' in results
    assert results['price_related']['valid']

def test_validation_error_handling(config_path):
    with pytest.raises(ValidationError):
        FeatureValidator("nonexistent_config.json")

def test_create_expectation_suite(config_path, sample_data):
    validator = FeatureValidator(config_path)
    suite = validator.create_expectation_suite(sample_data)
    assert 'null_validation' in suite
    assert 'numeric_bounds_validation' in suite
    assert 'correlation_validation' in suite
    assert 'feature_group_validation' in suite