"""Tests for edge analysis functionality."""

import numpy as np
import pytest
from analysis.edge_analysis import EdgeAnalyzer, EdgeMetrics

def test_analyze_threshold_sweep():
    """Test threshold sweep analysis."""
    analyzer = EdgeAnalyzer()
    
    # Generate synthetic data
    n_samples = 1000
    val_probs = np.random.random((n_samples, 2))
    returns = np.random.normal(0.0002, 0.001, n_samples)  # 2bp mean, 10bp vol
    
    taus = np.array([0.02, 0.03, 0.04])
    metrics = analyzer.analyze_threshold_sweep(val_probs, returns, taus)
    
    assert len(metrics) == 3
    for m in metrics:
        assert isinstance(m, EdgeMetrics)
        assert m.tau in taus
        assert m.n_trades > 0
        assert isinstance(m.mean_bp, float)
        assert isinstance(m.std_bp, float)
        assert isinstance(m.sharpe, float)

def test_find_optimal_threshold():
    """Test optimal threshold finding."""
    analyzer = EdgeAnalyzer(min_edge_bp=3.0, min_sharpe=0.5)
    
    metrics = [
        EdgeMetrics(tau=0.02, n_trades=100, mean_bp=2.0, std_bp=10.0, sharpe=0.6),
        EdgeMetrics(tau=0.03, n_trades=80, mean_bp=3.5, std_bp=9.0, sharpe=0.8),
        EdgeMetrics(tau=0.04, n_trades=60, mean_bp=4.0, std_bp=8.0, sharpe=0.9)
    ]
    
    opt_tau, opt_metrics = analyzer.find_optimal_threshold(metrics)
    assert opt_tau == 0.04
    assert opt_metrics.mean_bp == 4.0
    assert opt_metrics.sharpe == 0.9

def test_analyze_enhancement_impact():
    """Test enhancement impact analysis."""
    analyzer = EdgeAnalyzer()
    
    base_metrics = EdgeMetrics(
        tau=0.03,
        n_trades=100,
        mean_bp=5.0,
        std_bp=10.0,
        sharpe=1.5
    )
    
    enhancements = analyzer.analyze_enhancement_impact(
        base_metrics,
        maker_ratio=0.6,
        size_scale=0.7,
        hold_time_ratio=0.4,
        symbol_count=3,
        model_count=2
    )
    
    assert len(enhancements) == 6  # base + 5 enhancements
    assert 'base' in enhancements
    assert 'maker_orders' in enhancements
    assert 'size_scaling' in enhancements
    assert 'shorter_holding' in enhancements
    assert 'multi_symbol' in enhancements
    assert 'model_ensemble' in enhancements
    
    # Verify maker orders impact
    maker = enhancements['maker_orders']
    assert maker.mean_bp > base_metrics.mean_bp  # Cost reduction increases mean
    assert maker.sharpe > base_metrics.sharpe
    
    # Verify multi-symbol impact
    multi = enhancements['multi_symbol']
    assert multi.n_trades == base_metrics.n_trades * 3
    assert multi.sharpe > base_metrics.sharpe  # Diversification benefit 