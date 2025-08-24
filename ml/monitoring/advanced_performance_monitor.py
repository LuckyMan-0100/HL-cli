"""
Advanced ML model performance monitoring with sophisticated analytics.
"""

import logging
import os
import sys
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import json
import time

# Add machine-learning directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "machine-learning"))

try:
    from model import annualised_sharpe, edge_statistics
    HAS_ADVANCED_ANALYTICS = True
except ImportError:
    HAS_ADVANCED_ANALYTICS = False

from .performance_monitor import PerformanceMonitor
from feature_engineering.feature_monitor import FeatureMonitor

logger = logging.getLogger(__name__)

class AdvancedPerformanceMonitor(PerformanceMonitor):
    """Advanced performance monitor with sophisticated ML analytics."""

    def __init__(self, feature_names: List[str] = None, 
                 metrics_dir: str = "logs/ml_metrics") -> None:
        """Initialize the advanced performance monitor."""
        super().__init__(feature_names, metrics_dir)
        
        # Initialize sophisticated feature monitor
        self.feature_monitor = FeatureMonitor(
            feature_names=feature_names or [],
            min_samples=100,  # More samples for robust baseline
            drift_threshold=2.0,  # Slightly less sensitive for performance monitoring
            std_epsilon=1e-8
        )
        
        # Advanced metrics
        self.feature_importance_history = []
        self.prediction_accuracy_by_confidence = {}
        self.model_performance_by_timeframe = {}
        self.signal_strength_distribution = []
        
        # Performance buckets
        self.confidence_buckets = [0.0, 0.3, 0.5, 0.7, 0.8, 0.9, 1.0]
        self.timeframe_windows = ["1h", "4h", "12h", "24h"]
        
        # Trading performance analytics
        self.trade_outcomes_by_signal_strength = {}
        self.market_regime_performance = {}
        self.volatility_adjusted_metrics = {}
        
        # Drift alert system
        self.drift_alerts = []
        self.last_drift_check = datetime.now()
        self.drift_alert_cooldown = timedelta(minutes=15)  # Prevent spam
        
        logger.info("Advanced performance monitor with sophisticated feature monitoring initialized")
    
    def record_advanced_prediction(self, timestamp: datetime, prediction: Any, 
                                   features: Dict[str, float], latency_ms: float) -> None:
        """Record an advanced prediction with detailed analytics."""
        # Call parent method
        self.record_prediction(timestamp, features, prediction, latency_ms)
        
        try:
            # Extract advanced prediction attributes
            signal = getattr(prediction, 'signal', 0.0)
            confidence = getattr(prediction, 'confidence', 0.0)
            model_type = getattr(prediction, 'model_type', 'unknown')
            feature_importance = getattr(prediction, 'feature_importance', {})
            prediction_horizon = getattr(prediction, 'prediction_horizon', 24)
            
            # Record feature importance history
            if feature_importance:
                importance_record = {
                    'timestamp': timestamp,
                    'feature_importance': feature_importance,
                    'model_type': model_type,
                    'prediction_horizon': prediction_horizon
                }
                self.feature_importance_history.append(importance_record)
                
                # Maintain history size
                if len(self.feature_importance_history) > 1000:
                    self.feature_importance_history = self.feature_importance_history[-1000:]
            
            # Track signal strength distribution
            self.signal_strength_distribution.append({
                'timestamp': timestamp,
                'signal_strength': abs(signal),
                'confidence': confidence,
                'model_type': model_type
            })
            
            # Update confidence bucket tracking
            confidence_bucket = self._get_confidence_bucket(confidence)
            if confidence_bucket not in self.prediction_accuracy_by_confidence:
                self.prediction_accuracy_by_confidence[confidence_bucket] = {
                    'predictions': 0,
                    'correct': 0,
                    'total_pnl': 0.0
                }
            self.prediction_accuracy_by_confidence[confidence_bucket]['predictions'] += 1
            
            # Track performance by timeframe
            timeframe_key = f"{prediction_horizon}h"
            if timeframe_key not in self.model_performance_by_timeframe:
                self.model_performance_by_timeframe[timeframe_key] = {
                    'predictions': 0,
                    'accuracy': 0.0,
                    'avg_confidence': 0.0,
                    'total_pnl': 0.0
                }
            
            timeframe_stats = self.model_performance_by_timeframe[timeframe_key]
            timeframe_stats['predictions'] += 1
            timeframe_stats['avg_confidence'] = (
                (timeframe_stats['avg_confidence'] * (timeframe_stats['predictions'] - 1) + confidence) /
                timeframe_stats['predictions']
            )
            
            # Calculate feature drift using sophisticated monitor
            self._update_sophisticated_feature_drift(features, timestamp)
            
            logger.debug(f"Advanced prediction recorded: model={model_type}, "
                        f"confidence={confidence:.2%}, signal={signal:.4f}")
            
        except Exception as e:
            logger.error(f"Error recording advanced prediction: {e}")
    
    def record_advanced_trade(self, timestamp: datetime, fill: Any, 
                              prediction: Any, market_conditions: Dict[str, float] = None) -> None:
        """Record a trade with advanced analytics."""
        # Call parent method
        self.record_trade(timestamp, fill, prediction)
        
        try:
            # Extract trade details
            pnl = getattr(fill, 'pnl', 0.0)
            signal = getattr(prediction, 'signal', 0.0)
            confidence = getattr(prediction, 'confidence', 0.0)
            model_type = getattr(prediction, 'model_type', 'unknown')
            
            # Update confidence bucket accuracy
            confidence_bucket = self._get_confidence_bucket(confidence)
            if confidence_bucket in self.prediction_accuracy_by_confidence:
                bucket_stats = self.prediction_accuracy_by_confidence[confidence_bucket]
                if (signal > 0 and pnl > 0) or (signal < 0 and pnl > 0):
                    bucket_stats['correct'] += 1
                bucket_stats['total_pnl'] += pnl
            
            # Update signal strength performance
            signal_strength = abs(signal)
            strength_bucket = self._get_signal_strength_bucket(signal_strength)
            if strength_bucket not in self.trade_outcomes_by_signal_strength:
                self.trade_outcomes_by_signal_strength[strength_bucket] = {
                    'trades': 0,
                    'wins': 0,
                    'total_pnl': 0.0,
                    'avg_pnl': 0.0
                }
            
            strength_stats = self.trade_outcomes_by_signal_strength[strength_bucket]
            strength_stats['trades'] += 1
            if pnl > 0:
                strength_stats['wins'] += 1
            strength_stats['total_pnl'] += pnl
            strength_stats['avg_pnl'] = strength_stats['total_pnl'] / strength_stats['trades']
            
            # Update market regime performance
            if market_conditions:
                self._update_market_regime_performance(pnl, market_conditions, timestamp)
            
            logger.debug(f"Advanced trade recorded: PnL={pnl:.6f}, "
                        f"signal_strength={signal_strength:.4f}, confidence={confidence:.2%}")
            
        except Exception as e:
            logger.error(f"Error recording advanced trade: {e}")
    
    def _get_confidence_bucket(self, confidence: float) -> str:
        """Get confidence bucket for the given confidence score."""
        for i in range(len(self.confidence_buckets) - 1):
            if self.confidence_buckets[i] <= confidence < self.confidence_buckets[i + 1]:
                return f"{self.confidence_buckets[i]:.1f}-{self.confidence_buckets[i + 1]:.1f}"
        return f"{self.confidence_buckets[-2]:.1f}+"
    
    def _get_signal_strength_bucket(self, strength: float) -> str:
        """Get signal strength bucket."""
        if strength < 0.2:
            return "weak (0.0-0.2)"
        elif strength < 0.5:
            return "medium (0.2-0.5)"
        elif strength < 0.8:
            return "strong (0.5-0.8)"
        else:
            return "very_strong (0.8+)"
    
    def _update_sophisticated_feature_drift(self, features: Dict[str, float], timestamp: datetime) -> None:
        """Update feature drift using sophisticated FeatureMonitor with real-time alerts."""
        try:
            # Use sophisticated drift detection
            drift_detected = self.feature_monitor.check_feature_drift(features)
            
            # Handle drift detection with alerts
            if drift_detected:
                drift_status = self.feature_monitor.get_drift_status()
                drifted_features = drift_status.get('drifted_features', [])
                z_scores = drift_status.get('feature_z_scores', {})
                
                # Check if we should send an alert (cooldown mechanism)
                if datetime.now() - self.last_drift_check > self.drift_alert_cooldown:
                    alert = {
                        'timestamp': timestamp,
                        'severity': self._assess_drift_severity(drifted_features, z_scores),
                        'drifted_features': drifted_features,
                        'z_scores': z_scores,
                        'total_features': len(self.feature_monitor.feature_names),
                        'drift_percentage': len(drifted_features) / max(len(self.feature_monitor.feature_names), 1)
                    }
                    
                    self.drift_alerts.append(alert)
                    self.last_drift_check = datetime.now()
                    
                    # Log appropriate severity level
                    if alert['severity'] == 'critical':
                        logger.critical(f"CRITICAL FEATURE DRIFT: {len(drifted_features)} features drifted - {drifted_features}")
                    elif alert['severity'] == 'high':
                        logger.error(f"HIGH FEATURE DRIFT: {len(drifted_features)} features drifted - {drifted_features}")
                    else:
                        logger.warning(f"MODERATE FEATURE DRIFT: {len(drifted_features)} features drifted - {drifted_features}")
                    
                    # Trim alert history
                    if len(self.drift_alerts) > 100:
                        self.drift_alerts = self.drift_alerts[-100:]
            
        except Exception as e:
            logger.error(f"Error updating sophisticated feature drift: {e}")
    
    def _assess_drift_severity(self, drifted_features: List[str], z_scores: Dict[str, float]) -> str:
        """Assess the severity of feature drift."""
        if not drifted_features:
            return 'none'
        
        drift_count = len(drifted_features)
        max_z_score = max(z_scores.values()) if z_scores else 0.0
        
        # Critical: Many features or extremely high Z-scores
        if drift_count >= 5 or max_z_score > 5.0:
            return 'critical'
        # High: Multiple features or high Z-scores  
        elif drift_count >= 3 or max_z_score > 3.5:
            return 'high'
        # Moderate: Few features or moderate Z-scores
        else:
            return 'moderate'
    
    def _update_market_regime_performance(self, pnl: float, 
                                          market_conditions: Dict[str, float], 
                                          timestamp: datetime) -> None:
        """Update performance by market regime."""
        try:
            volatility = market_conditions.get('volatility', 0.01)
            trend = market_conditions.get('trend', 0.0)
            
            # Classify market regime
            if volatility > 0.02:
                regime = "high_vol"
            elif volatility < 0.005:
                regime = "low_vol"
            else:
                regime = "normal_vol"
            
            if abs(trend) > 0.01:
                regime += "_trending"
            else:
                regime += "_sideways"
            
            if regime not in self.market_regime_performance:
                self.market_regime_performance[regime] = {
                    'trades': 0,
                    'total_pnl': 0.0,
                    'win_rate': 0.0,
                    'avg_pnl': 0.0
                }
            
            regime_stats = self.market_regime_performance[regime]
            regime_stats['trades'] += 1
            regime_stats['total_pnl'] += pnl
            regime_stats['avg_pnl'] = regime_stats['total_pnl'] / regime_stats['trades']
            
            # Update win rate
            wins = sum(1 for t in self.trades if t.get('regime') == regime and t.get('pnl', 0) > 0)
            regime_stats['win_rate'] = wins / regime_stats['trades']
            
        except Exception as e:
            logger.error(f"Error updating market regime performance: {e}")
    
    def calculate_advanced_metrics(self) -> Dict[str, Any]:
        """Calculate advanced performance metrics."""
        try:
            metrics = self.get_metrics()  # Get base metrics
            
            # Add advanced metrics
            advanced_metrics = {
                "confidence_performance": self._analyze_confidence_performance(),
                "signal_strength_analysis": self._analyze_signal_strength(),
                "feature_importance_summary": self._analyze_feature_importance(),
                "feature_drift_analysis": self._analyze_feature_drift(),
                "market_regime_performance": self.market_regime_performance,
                "model_stability": self._calculate_model_stability(),
                "prediction_calibration": self._calculate_prediction_calibration(),
            }
            
            # Add sophisticated analytics if available
            if HAS_ADVANCED_ANALYTICS and len(self.trades) > 0:
                trade_returns = pd.Series([t['pnl'] for t in self.trades])
                advanced_metrics.update({
                    "sophisticated_sharpe": self._calculate_sophisticated_sharpe(trade_returns),
                    "edge_statistics": self._calculate_edge_statistics(trade_returns),
                    "drawdown_analysis": self._analyze_drawdowns(trade_returns),
                })
            
            metrics.update(advanced_metrics)
            return metrics
            
        except Exception as e:
            logger.error(f"Error calculating advanced metrics: {e}")
            return self.get_metrics()  # Fallback to basic metrics
    
    def _analyze_confidence_performance(self) -> Dict[str, Any]:
        """Analyze performance by confidence buckets."""
        analysis = {}
        for bucket, stats in self.prediction_accuracy_by_confidence.items():
            if stats['predictions'] > 0:
                accuracy = stats['correct'] / stats['predictions']
                avg_pnl = stats['total_pnl'] / stats['predictions']
                
                analysis[bucket] = {
                    'accuracy': accuracy,
                    'avg_pnl': avg_pnl,
                    'total_predictions': stats['predictions'],
                    'total_pnl': stats['total_pnl']
                }
        return analysis
    
    def _analyze_signal_strength(self) -> Dict[str, Any]:
        """Analyze performance by signal strength."""
        return self.trade_outcomes_by_signal_strength
    
    def _analyze_feature_importance(self) -> Dict[str, Any]:
        """Analyze feature importance trends."""
        if not self.feature_importance_history:
            return {}
        
        # Aggregate feature importance over time
        all_features = set()
        for record in self.feature_importance_history:
            all_features.update(record['feature_importance'].keys())
        
        feature_trends = {}
        for feature in all_features:
            importance_values = [
                record['feature_importance'].get(feature, 0.0)
                for record in self.feature_importance_history
            ]
            
            if importance_values:
                feature_trends[feature] = {
                    'avg_importance': np.mean(importance_values),
                    'std_importance': np.std(importance_values),
                    'trend': self._calculate_trend(importance_values),
                    'stability': 1.0 - (np.std(importance_values) / (np.mean(importance_values) + 1e-6))
                }
        
        return feature_trends
    
    def _analyze_feature_drift(self) -> Dict[str, Any]:
        """Analyze feature drift patterns using sophisticated FeatureMonitor."""
        try:
            # Get comprehensive drift status from sophisticated monitor
            drift_status = self.feature_monitor.get_drift_status()
            
            drift_analysis = {
                'has_baseline': drift_status.get('has_baseline', False),
                'total_samples': drift_status.get('total_samples', 0),
                'current_drifted_features': drift_status.get('drifted_features', []),
                'feature_z_scores': drift_status.get('feature_z_scores', {}),
                'drift_feature_count': len(drift_status.get('drifted_features', [])),
                'drift_percentage': len(drift_status.get('drifted_features', [])) / max(len(self.feature_monitor.feature_names), 1)
            }
            
            # Add individual feature analysis
            feature_details = {}
            z_scores = drift_status.get('feature_z_scores', {})
            for feature, z_score in z_scores.items():
                drift_level = "normal"
                if z_score > 3:
                    drift_level = "high"
                elif z_score > 2:
                    drift_level = "medium"
                
                feature_details[feature] = {
                    'z_score': z_score,
                    'drift_level': drift_level,
                    'requires_attention': z_score > 2.5,
                    'is_drifted': feature in drift_status.get('drifted_features', [])
                }
            
            drift_analysis['feature_details'] = feature_details
            
            # Add recent drift alert history
            recent_alerts = [
                alert for alert in self.drift_alerts 
                if alert['timestamp'] > datetime.now() - timedelta(hours=24)
            ]
            
            drift_analysis['recent_alerts'] = {
                'count_24h': len(recent_alerts),
                'severity_breakdown': self._get_alert_severity_breakdown(recent_alerts),
                'latest_alert': recent_alerts[-1] if recent_alerts else None
            }
            
            # Add drift trend analysis
            if len(self.drift_alerts) > 5:
                alert_frequencies = [
                    len([a for a in self.drift_alerts if a['timestamp'] > datetime.now() - timedelta(hours=h)])
                    for h in [1, 6, 12, 24]
                ]
                drift_analysis['drift_trend'] = {
                    'alerts_last_1h': alert_frequencies[0],
                    'alerts_last_6h': alert_frequencies[1], 
                    'alerts_last_12h': alert_frequencies[2],
                    'alerts_last_24h': alert_frequencies[3],
                    'trend_direction': 'increasing' if alert_frequencies[0] > alert_frequencies[3]/24 else 'stable'
                }
            
            return drift_analysis
            
        except Exception as e:
            logger.error(f"Error analyzing sophisticated feature drift: {e}")
            return {'error': str(e)}
    
    def _get_alert_severity_breakdown(self, alerts: List[Dict]) -> Dict[str, int]:
        """Get breakdown of alert severities."""
        breakdown = {'critical': 0, 'high': 0, 'moderate': 0}
        for alert in alerts:
            severity = alert.get('severity', 'moderate')
            if severity in breakdown:
                breakdown[severity] += 1
        return breakdown
    
    def _calculate_model_stability(self) -> Dict[str, float]:
        """Calculate model stability metrics."""
        if len(self.signal_strength_distribution) < 10:
            return {}
        
        recent_signals = self.signal_strength_distribution[-50:]
        signal_strengths = [s['signal_strength'] for s in recent_signals]
        confidences = [s['confidence'] for s in recent_signals]
        
        return {
            'signal_strength_stability': 1.0 - np.std(signal_strengths),
            'confidence_stability': 1.0 - np.std(confidences),
            'avg_signal_strength': np.mean(signal_strengths),
            'avg_confidence': np.mean(confidences)
        }
    
    def _calculate_prediction_calibration(self) -> Dict[str, float]:
        """Calculate how well-calibrated the model's confidence scores are."""
        if not self.prediction_accuracy_by_confidence:
            return {}
        
        calibration_error = 0.0
        total_predictions = 0
        
        for bucket, stats in self.prediction_accuracy_by_confidence.items():
            if stats['predictions'] > 0:
                # Extract confidence midpoint from bucket name
                bucket_mid = np.mean([float(x) for x in bucket.replace('+', '').split('-')])
                actual_accuracy = stats['correct'] / stats['predictions']
                
                # Calibration error
                calibration_error += abs(bucket_mid - actual_accuracy) * stats['predictions']
                total_predictions += stats['predictions']
        
        return {
            'calibration_error': calibration_error / max(total_predictions, 1),
            'is_well_calibrated': (calibration_error / max(total_predictions, 1)) < 0.1
        }
    
    def _calculate_sophisticated_sharpe(self, returns: pd.Series) -> float:
        """Calculate Sharpe ratio using sophisticated method."""
        try:
            avg_trades_per_day = len(returns) / max(1, (datetime.now() - self.start_time).days)
            return annualised_sharpe(returns, avg_trades_per_day)
        except:
            return 0.0
    
    def _calculate_edge_statistics(self, returns: pd.Series) -> Tuple[float, float]:
        """Calculate edge statistics."""
        try:
            return edge_statistics(returns)
        except:
            return 0.0, 0.0
    
    def _analyze_drawdowns(self, returns: pd.Series) -> Dict[str, float]:
        """Analyze drawdown patterns."""
        try:
            cumulative = returns.cumsum()
            rolling_max = cumulative.expanding().max()
            drawdowns = cumulative - rolling_max
            
            return {
                'max_drawdown': abs(drawdowns.min()),
                'avg_drawdown': abs(drawdowns[drawdowns < 0].mean()),
                'drawdown_duration': len(drawdowns[drawdowns < 0]),
                'recovery_time': self._calculate_recovery_time(drawdowns)
            }
        except:
            return {}
    
    def _calculate_trend(self, values: List[float]) -> float:
        """Calculate trend direction (-1 to 1)."""
        if len(values) < 2:
            return 0.0
        
        x = np.arange(len(values))
        slope = np.polyfit(x, values, 1)[0]
        return np.tanh(slope * 10)  # Normalize to [-1, 1]
    
    def _calculate_recovery_time(self, drawdowns: pd.Series) -> float:
        """Calculate average recovery time from drawdowns."""
        try:
            in_drawdown = False
            drawdown_start = None
            recovery_times = []
            
            for i, dd in enumerate(drawdowns):
                if dd < 0 and not in_drawdown:
                    in_drawdown = True
                    drawdown_start = i
                elif dd >= 0 and in_drawdown:
                    in_drawdown = False
                    if drawdown_start is not None:
                        recovery_times.append(i - drawdown_start)
            
            return np.mean(recovery_times) if recovery_times else 0.0
        except:
            return 0.0
    
    def export_advanced_metrics(self, output_file: Path) -> None:
        """Export advanced metrics to file."""
        try:
            metrics = self.calculate_advanced_metrics()
            
            # Add metadata
            metadata = {
                'export_time': datetime.now().isoformat(),
                'total_runtime_hours': (datetime.now() - self.start_time).total_seconds() / 3600,
                'has_advanced_analytics': HAS_ADVANCED_ANALYTICS,
                'monitoring_version': 'advanced_v1.0'
            }
            
            export_data = {
                'metadata': metadata,
                'metrics': metrics,
                'feature_importance_history': self.feature_importance_history[-100:],  # Last 100
                'signal_distribution': self.signal_strength_distribution[-100:]  # Last 100
            }
            
            with open(output_file, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)
            
            logger.info(f"Advanced metrics exported to {output_file}")
            
        except Exception as e:
            logger.error(f"Error exporting advanced metrics: {e}")
    
    def get_model_health_status(self) -> Dict[str, Any]:
        """Get comprehensive model health status including advanced drift monitoring."""
        try:
            health_status = {}
            
            # Basic model performance health
            recent_predictions = len([p for p in self.predictions if p['timestamp'] > datetime.now() - timedelta(hours=1)])
            recent_trades = len([t for t in self.trades if t['timestamp'] > datetime.now() - timedelta(hours=1)])
            
            # Prediction latency health
            if self.latencies:
                avg_latency = np.mean(self.latencies[-100:])
                latency_health = "good" if avg_latency < 50 else ("warning" if avg_latency < 100 else "critical")
            else:
                avg_latency = 0
                latency_health = "unknown"
            
            # Sophisticated drift analysis from FeatureMonitor
            drift_status = self.feature_monitor.get_drift_status()
            drift_health = self._assess_drift_health_status(drift_status)
            
            # Recent drift alerts
            recent_critical_alerts = len([
                a for a in self.drift_alerts 
                if a['timestamp'] > datetime.now() - timedelta(hours=6) and a['severity'] == 'critical'
            ])
            
            alert_health = "good"
            if recent_critical_alerts > 0:
                alert_health = "critical"
            elif len([a for a in self.drift_alerts if a['timestamp'] > datetime.now() - timedelta(hours=6)]) > 3:
                alert_health = "warning"
            
            # Model stability assessment
            stability_metrics = self._calculate_model_stability()
            stability_health = "good"
            if stability_metrics:
                if stability_metrics.get('confidence_stability', 1.0) < 0.7:
                    stability_health = "warning"
                if stability_metrics.get('signal_strength_stability', 1.0) < 0.6:
                    stability_health = "critical"
            
            # Overall health score calculation
            health_components = {
                'prediction_volume': min(recent_predictions / max(recent_predictions, 1), 1.0),
                'latency': 1.0 if latency_health == "good" else (0.5 if latency_health == "warning" else 0.0),
                'drift': drift_health['score'],
                'alerts': 1.0 if alert_health == "good" else (0.5 if alert_health == "warning" else 0.0),
                'stability': 1.0 if stability_health == "good" else (0.5 if stability_health == "warning" else 0.0)
            }
            
            overall_score = np.mean(list(health_components.values()))
            
            health_status = {
                'overall_score': overall_score,
                'overall_status': "healthy" if overall_score > 0.8 else ("degraded" if overall_score > 0.5 else "critical"),
                'components': {
                    'prediction_latency': {
                        'status': latency_health,
                        'avg_latency_ms': avg_latency,
                        'recent_predictions': recent_predictions
                    },
                    'feature_drift': {
                        'status': drift_health['status'],
                        'drifted_features': drift_status.get('drifted_features', []),
                        'drift_percentage': len(drift_status.get('drifted_features', [])) / max(len(self.feature_monitor.feature_names), 1),
                        'has_baseline': drift_status.get('has_baseline', False),
                        'total_samples': drift_status.get('total_samples', 0)
                    },
                    'drift_alerts': {
                        'status': alert_health,
                        'recent_critical_alerts': recent_critical_alerts,
                        'total_alerts_6h': len([a for a in self.drift_alerts if a['timestamp'] > datetime.now() - timedelta(hours=6)]),
                        'latest_alert_severity': self.drift_alerts[-1]['severity'] if self.drift_alerts else None
                    },
                    'model_stability': {
                        'status': stability_health,
                        'metrics': stability_metrics
                    }
                },
                'recommendations': self._get_health_recommendations(overall_score, len(drift_status.get('drifted_features', [])), recent_critical_alerts),
                'last_updated': datetime.now().isoformat()
            }
            
            return health_status
            
        except Exception as e:
            logger.error(f"Error getting model health status: {e}")
            return {'error': str(e), 'overall_status': 'unknown'}
    
    def _assess_drift_health_status(self, drift_status: Dict[str, Any]) -> Dict[str, Any]:
        """Assess health status based on sophisticated drift monitoring."""
        drifted_features = drift_status.get('drifted_features', [])
        total_features = len(self.feature_monitor.feature_names)
        drift_percentage = len(drifted_features) / max(total_features, 1)
        
        if not drift_status.get('has_baseline', False):
            return {'status': 'establishing_baseline', 'score': 0.8}
        
        if drift_percentage == 0:
            status = 'good'
            score = 1.0
        elif drift_percentage < 0.1:  # Less than 10% of features drifted
            status = 'good'
            score = 0.9
        elif drift_percentage < 0.2:  # Less than 20% of features drifted
            status = 'warning'
            score = 0.6
        else:  # More than 20% of features drifted
            status = 'critical'
            score = 0.2
        
        return {'status': status, 'score': score, 'drift_percentage': drift_percentage}
    
    def _get_health_recommendations(self, health_score: float, high_drift_features: int, recent_critical_alerts: int) -> List[str]:
        """Get recommendations based on model health."""
        recommendations = []
        
        if health_score < 0.7:
            recommendations.append("Consider retraining the model with recent data")
        
        if high_drift_features > 3:
            recommendations.append("Feature drift detected - review feature engineering")
        
        if recent_critical_alerts > 0:
            recommendations.append("Recent critical feature drift detected - immediate attention required")
        
        if not recommendations:
            recommendations.append("Model performing well - continue monitoring")
        
        return recommendations 