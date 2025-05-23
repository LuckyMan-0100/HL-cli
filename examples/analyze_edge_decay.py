"""Example script demonstrating edge decay analysis."""

import numpy as np
import pandas as pd
from analysis.edge_analysis import EdgeAnalyzer
import matplotlib.pyplot as plt

def main():
    # Create analyzer with custom parameters
    analyzer = EdgeAnalyzer(
        base_cost=0.0003,  # 3bp trading cost
        min_edge_bp=5.0,   # Require 5bp edge
        min_sharpe=1.0     # Require Sharpe >= 1
    )
    
    # Load or generate sample data
    # Here we'll generate synthetic data for demonstration
    n_samples = 10000
    
    # Generate synthetic predictions
    # Higher probabilities should correlate with higher returns
    true_edge = np.random.normal(0.0003, 0.0001, n_samples)  # 3bp average edge
    noise = np.random.normal(0, 0.0005, n_samples)  # 5bp noise
    returns = true_edge + noise
    
    # Generate probabilities that correlate with returns
    base_probs = (returns - returns.mean()) / returns.std()
    base_probs = 1 / (1 + np.exp(-2 * base_probs))  # Sigmoid transform
    
    # Add noise to probabilities
    prob_noise = np.random.normal(0, 0.1, n_samples)
    val_probs = np.clip(base_probs.reshape(-1, 1) + prob_noise.reshape(-1, 1), 0, 1)
    val_probs = np.hstack([val_probs, 1-val_probs])  # [p(long), p(short)]
    
    # Analyze threshold sweep
    print("Analyzing threshold sweep...")
    metrics = analyzer.analyze_threshold_sweep(val_probs, returns)
    
    # Plot edge decay
    analyzer.plot_edge_decay(metrics)
    
    # Find optimal threshold
    try:
        opt_tau, opt_metrics = analyzer.find_optimal_threshold(metrics)
        print(f"\nOptimal threshold found: {opt_tau:.4f}")
        print(f"Trades per day: {opt_metrics.n_trades}")
        print(f"Mean return: {opt_metrics.mean_bp:.1f} bp")
        print(f"Return std: {opt_metrics.std_bp:.1f} bp")
        print(f"Sharpe ratio: {opt_metrics.sharpe:.2f}")
        
        # Analyze potential enhancements
        print("\nAnalyzing enhancement strategies...")
        enhancements = analyzer.analyze_enhancement_impact(
            opt_metrics,
            maker_ratio=0.6,      # 60% maker orders
            size_scale=0.7,       # Scale to 70% size on average
            hold_time_ratio=0.4,  # 40% of original hold time
            symbol_count=3,       # Trade 3 symbols
            model_count=2         # 2 model ensemble
        )
        
        # Plot enhancement comparison
        analyzer.plot_enhancement_comparison(enhancements)
        
        # Print enhancement impacts
        print("\nEnhancement Impacts:")
        print("-" * 50)
        for name, metrics in enhancements.items():
            print(f"\n{name.upper()}:")
            print(f"Trades per day: {metrics.n_trades}")
            print(f"Mean return: {metrics.mean_bp:.1f} bp")
            print(f"Sharpe ratio: {metrics.sharpe:.2f}")
            
    except ValueError as e:
        print(f"\nNo valid threshold found: {e}")

if __name__ == "__main__":
    main() 