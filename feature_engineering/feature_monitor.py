"""
Feature monitoring for drift detection.
"""

import logging
import os
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Set
from datetime import datetime
from pathlib import Path
import json

logger = logging.getLogger(__name__)

class FeatureMonitor:
    """Monitor feature drift."""

    def __init__(self, feature_names: List[str] = None, 
                 min_samples: int = 100, drift_threshold: float = 3.0,
                 std_epsilon: float = 1e-8) -> None:
        """Initialize the feature monitor.
        
        Args:
            feature_names: List of feature names to monitor
            min_samples: Minimum samples required to establish baseline
            drift_threshold: Z-score threshold for drift detection
            std_epsilon: Small value to prevent division by zero
        """
        self.feature_names = feature_names or []
        self.min_samples = min_samples
        self.drift_threshold = drift_threshold
        self.std_epsilon = std_epsilon
        
        # Initialize feature statistics
        self.feature_samples: Dict[str, List[float]] = {
            feature: [] for feature in self.feature_names
        }
        
        # Baseline statistics
        self.baseline_mean: Dict[str, float] = {}
        self.baseline_std: Dict[str, float] = {}
        self.baseline_min: Dict[str, float] = {}
        self.baseline_max: Dict[str, float] = {}
        
        # Moving window statistics 
        self.window_size = 100
        self.window_mean: Dict[str, float] = {}
        self.window_std: Dict[str, float] = {}
        
        # Drift tracking
        self.has_baseline = False
        self.drifted_features: Set[str] = set()
        self.feature_z_scores: Dict[str, float] = {}
        
        # Sample count
        self.total_samples = 0
        
    def add_sample(self, features: Dict[str, float]) -> None:
        """Add a feature sample.
        
        Args:
            features: Dictionary of feature values
        """
        self.total_samples += 1
        
        # Extract relevant features
        for feature in self.feature_names:
            if feature in features:
                value = features[feature]
                
                # Skip NaN or non-numeric values
                if not isinstance(value, (int, float)) or np.isnan(value):
                    continue
                    
                # Add to samples
                self.feature_samples[feature].append(value)
                
                # Trim to window size
                if len(self.feature_samples[feature]) > self.window_size:
                    self.feature_samples[feature] = self.feature_samples[feature][-self.window_size:]
        
        # Compute baseline if we have enough samples
        if not self.has_baseline and self.total_samples >= self.min_samples:
            self.compute_baseline_stats()
            
    def compute_baseline_stats(self, initial_features: Optional[Dict[str, float]] = None) -> None:
        """Compute baseline statistics.
        
        Args:
            initial_features: Optional initial feature values if samples not available
        """
        logger.info("Computing baseline feature statistics")
        
        for feature in self.feature_names:
            samples = self.feature_samples.get(feature, [])
            
            # Use initial features if no samples available
            if not samples and initial_features and feature in initial_features:
                # Add small random noise around the initial value for more robust baseline
                initial_value = initial_features[feature]
                if isinstance(initial_value, (int, float)) and not np.isnan(initial_value):
                    noise_scale = abs(initial_value) * 0.01 + 1e-6
                    samples = [initial_value + np.random.normal(0, noise_scale) for _ in range(10)]
                    self.feature_samples[feature] = samples
            
            if samples:
                self.baseline_mean[feature] = np.mean(samples)
                self.baseline_std[feature] = np.std(samples) + self.std_epsilon
                self.baseline_min[feature] = np.min(samples)
                self.baseline_max[feature] = np.max(samples)
                
                logger.debug(f"Baseline stats for {feature}: "
                            f"mean={self.baseline_mean[feature]:.6f}, "
                            f"std={self.baseline_std[feature]:.6f}")
            else:
                logger.warning(f"No samples available for feature: {feature}")
                
        self.has_baseline = True
        
    def update_window_stats(self) -> None:
        """Update moving window statistics."""
        if not self.has_baseline:
            return
            
        for feature in self.feature_names:
            samples = self.feature_samples.get(feature, [])
            if samples:
                self.window_mean[feature] = np.mean(samples)
                self.window_std[feature] = np.std(samples) + self.std_epsilon
    
    def check_feature_drift(self, features: Dict[str, float]) -> bool:
        """Check if there is significant feature drift.
        
        Args:
            features: Dictionary of feature values
            
        Returns:
            True if drift detected, False otherwise
        """
        # Add sample first
        self.add_sample(features)
        
        # If we don't have a baseline yet, return False
        if not self.has_baseline:
            return False
            
        # Update window statistics
        self.update_window_stats()
        
        # Check for drift
        drifted_features = set()
        for feature in self.feature_names:
            if feature in self.window_mean and feature in self.baseline_mean:
                # Calculate z-score of window mean relative to baseline
                z_score = abs(self.window_mean[feature] - self.baseline_mean[feature]) / self.baseline_std[feature]
                self.feature_z_scores[feature] = z_score
                
                # Check if z-score exceeds threshold
                if z_score > self.drift_threshold:
                    drifted_features.add(feature)
                    logger.warning(f"Feature drift detected for {feature}: "
                                 f"z-score={z_score:.2f}, "
                                 f"window_mean={self.window_mean[feature]:.6f}, "
                                 f"baseline_mean={self.baseline_mean[feature]:.6f}")
                    
        # Update drifted features
        self.drifted_features = drifted_features
        
        # Return True if any feature has drifted
        return len(drifted_features) > 0
    
    def get_drift_status(self) -> Dict[str, Any]:
        """Get current drift status.
        
        Returns:
            Dictionary with drift status
        """
        return {
            'has_baseline': self.has_baseline,
            'drifted_features': list(self.drifted_features),
            'feature_z_scores': self.feature_z_scores,
            'total_samples': self.total_samples
        }
        
    def save_drift_report(self, output_file: Path) -> None:
        """Save drift report to a file.
        
        Args:
            output_file: Path to output file
        """
        try:
            # Get drift status
            drift_status = self.get_drift_status()
            
            # Add baseline statistics
            drift_status['baseline_stats'] = {
                feature: {
                    'mean': self.baseline_mean.get(feature, 0.0),
                    'std': self.baseline_std.get(feature, 0.0),
                    'min': self.baseline_min.get(feature, 0.0),
                    'max': self.baseline_max.get(feature, 0.0)
                } for feature in self.feature_names
            }
            
            # Add window statistics
            drift_status['window_stats'] = {
                feature: {
                    'mean': self.window_mean.get(feature, 0.0),
                    'std': self.window_std.get(feature, 0.0)
                } for feature in self.feature_names
            }
            
            # Save to file
            with open(output_file, 'w') as f:
                json.dump(drift_status, f, indent=2)
                
            logger.info(f"Drift report saved to {output_file}")
            
        except Exception as e:
            logger.error(f"Error saving drift report: {e}")
            raise

    def calculate_psi(self, feature_name: str, current_data: np.ndarray) -> float:
        """Calculate Population Stability Index for a feature"""
        if feature_name not in self.baseline_stats:
            raise ValueError(f"No baseline statistics for feature {feature_name}")
            
        baseline_hist = np.array(self.baseline_stats[feature_name]['hist'])
        baseline_edges = np.array(self.baseline_stats[feature_name]['bin_edges'])
        
        # Calculate histogram for current data using same bins
        current_hist, _ = np.histogram(current_data, bins=baseline_edges, density=True)
        
        # Add small epsilon to avoid division by zero
        epsilon = 1e-10
        baseline_hist = baseline_hist + epsilon
        current_hist = current_hist + epsilon
        
        # Calculate PSI
        psi = np.sum((current_hist - baseline_hist) * np.log(current_hist / baseline_hist))
        
        return psi
    
    def save_drift_report(self, file_path: str) -> None:
        """Save drift reports to JSON file."""
        with open(file_path, 'w') as f:
            json.dump({
                'baseline_stats': self.baseline_stats,
                'drift_reports': self.drift_reports
            }, f, indent=2)
            
        logger.info(f"Feature drift report saved to {file_path}")
        
    def update_baseline_stats(self, features: Dict[str, float]) -> None:
        """Update baseline statistics with new observation."""
        if not self.baseline_stats:
            self.compute_baseline_stats(features)
            return
            
        # Simple online update of statistics
        for feature, value in features.items():
            if feature not in self.baseline_stats['mean']:
                continue
                
            old_mean = self.baseline_stats['mean'][feature]
            old_std = self.baseline_stats['std'][feature]
            
            # Update mean
            self.baseline_stats['mean'][feature] = (old_mean + value) / 2
            
            # Update std with Welford's online algorithm
            if old_std == 0:
                self.baseline_stats['std'][feature] = abs(value - old_mean)
            else:
                self.baseline_stats['std'][feature] = np.sqrt(
                    (old_std**2 + (value - old_mean)**2) / 2
                )
                
            # Update min/max
            self.baseline_stats['min'][feature] = min(
                self.baseline_stats['min'][feature],
                value
            )
            self.baseline_stats['max'][feature] = max(
                self.baseline_stats['max'][feature],
                value
            )
            
        # Save updated stats
        with open(self.stats_file, 'w') as f:
            json.dump(self.baseline_stats, f, indent=2)
    
    def log_feature_histograms(self, features_path: str, output_path: str):
        """Log daily feature histograms for visualization"""
        df = pl.scan_parquet(features_path)
        
        # Create output directory if it doesn't exist
        os.makedirs(output_path, exist_ok=True)
        
        # Get current timestamp for filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        feature_stats = {}
        for feature in self.baseline_stats.keys():
            if feature in ['timestamp', 'label', 'order_id']:
                continue
                
            # Compute histogram and statistics
            data = df.select(feature).collect().to_numpy().flatten()
            hist, bin_edges = np.histogram(data, bins=10, density=True)
            
            feature_stats[feature] = {
                'histogram': hist.tolist(),
                'bin_edges': bin_edges.tolist(),
                'mean': float(np.mean(data)),
                'std': float(np.std(data)),
                'q05': float(np.percentile(data, 5)),
                'q95': float(np.percentile(data, 95))
            }
        
        # Save to file
        with open(f"{output_path}/feature_stats_{timestamp}.json", 'w') as f:
            json.dump(feature_stats, f)
            
        return feature_stats 