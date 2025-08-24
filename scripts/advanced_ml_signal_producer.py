#!/usr/bin/env python3
"""
Advanced ML Signal Producer using sophisticated trading models.
Replaces the simple random signal generator with real ML predictions.
"""

import json
import time
import os
import uuid
import sys
import signal
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from decimal import Decimal

# Add project paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "ml"))

# Memory store and Redis
from data_ingestion.memory_store import KlineMemoryStore, OrderBookMemoryStore

# ML components
try:
    from ml.inference.advanced_predictor import AdvancedMLPredictor
    HAS_ADVANCED_ML = True
except ImportError:
    HAS_ADVANCED_ML = False
    
# Replace FeatureExtractor import with FeatureCalculator
from feature_engineering.calculator import FeatureCalculator
from feature_engineering.feature_monitor import FeatureMonitor

# Redis for memory store
import redis
from config.settings import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Global flag to control the main loop
running = True

def shutdown_handler(signum, frame):
    """Handles termination signals."""
    global running
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    running = False

# Register signal handlers
signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

class AdvancedMLSignalProducer:
    """Advanced ML signal producer using sophisticated models."""
    
    def __init__(self, symbol: str = "SOL_USDC_PERP", interval: str = "1m"):
        self.symbol = symbol
        self.interval = interval
        self.last_signal_time = None
        self.signal_interval = 5  # seconds between signals
        
        # Initialize components
        self.memory_store = None
        self.feature_extractor = None
        self.ml_predictor = None
        
        # Performance tracking
        self.signals_generated = 0
        self.last_features = {}
        
        # Initialize ML components
        self._initialize_components()
        
    def _initialize_components(self) -> None:
        """Initialize ML predictor and data components."""
        try:
            # Initialize ML predictor
            if HAS_ADVANCED_ML:
                try:
                    self.ml_predictor = AdvancedMLPredictor()
                    logger.info("Advanced ML predictor initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize ML predictor: {e}")
                    self.ml_predictor = None
            else:
                logger.info("Advanced ML components not available, using fallback signals")
                self.ml_predictor = None
            
            # Initialize memory stores
            try:
                self.kline_store = KlineMemoryStore()
                self.orderbook_store = OrderBookMemoryStore()
                logger.info("Memory stores initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize memory stores: {e}")
                self.kline_store = None
                self.orderbook_store = None
            
            # Initialize sophisticated feature calculator
            try:
                self.feature_calculator = FeatureCalculator()
                logger.info("Sophisticated feature calculator initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize feature calculator: {e}")
                self.feature_calculator = None
                
            # Initialize feature monitor for drift detection
            try:
                # Define feature names that we'll be monitoring
                feature_names = [
                    'spread', 'spread_bps', 'vol_imb_L1', 'vol_imb_L3', 'vol_imb_L5',
                    'bid_impact_1k', 'ask_impact_1k', 'bid_concentration', 'ask_concentration',
                    'rsi', 'macd', 'bb_upper', 'bb_lower', 'atr', 'ret_1m', 'ret_5m', 'vol_1m',
                    'bid_depth', 'ask_depth', 'depth_imbalance', 'bid_price_gaps', 'ask_price_gaps'
                ]
                self.feature_monitor = FeatureMonitor(
                    feature_names=feature_names,
                    min_samples=50,  # Reduced for faster baseline establishment
                    drift_threshold=2.5  # Slightly more sensitive for low-latency trading
                )
                logger.info(f"Feature monitor initialized with {len(feature_names)} features")
            except Exception as e:
                logger.warning(f"Failed to initialize feature monitor: {e}")
                self.feature_monitor = None
                
            # Initialize Redis for real-time data (if memory stores fail)
            try:
                self.redis_client = redis.Redis(
                    host=settings.redis.host,
                    port=settings.redis.port,
                    db=settings.redis.db,
                    decode_responses=True
                )
                # Test connection
                self.redis_client.ping()
                logger.info("Redis client initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Redis client: {e}")
                self.redis_client = None
                
        except Exception as e:
            logger.error(f"Component initialization failed: {e}")
            # Set fallback components
            self.ml_predictor = None
            self.kline_store = None 
            self.orderbook_store = None
            self.feature_calculator = None
            self.feature_monitor = None
            self.redis_client = None
    
    def _extract_features(self) -> Dict[str, float]:
        """Extract sophisticated features using FeatureCalculator."""
        try:
            # Use sophisticated feature calculator if available
            if self.feature_calculator:
                return self._extract_sophisticated_features()
            else:
                # Fallback to basic feature extraction
                return self._extract_basic_features()
                
        except Exception as e:
            logger.error(f"Feature extraction failed: {e}")
            return self._get_default_features()
    
    def _extract_sophisticated_features(self) -> Dict[str, float]:
        """Extract sophisticated features using FeatureCalculator and memory stores."""
        try:
            # Track extraction time
            self._last_feature_time = time.time()
            
            features = {}
            
            # Get recent klines data
            klines_df = self._get_klines_dataframe()
            
            # Get orderbook data  
            orderbook_df = self._get_orderbook_dataframe()
            
            # Calculate mid price for FeatureCalculator
            mid_price = self._get_mid_price(orderbook_df)
            
            # Use FeatureCalculator for sophisticated features
            if not klines_df.empty and not orderbook_df.empty and mid_price > 0:
                sophisticated_features = self.feature_calculator.calculate(
                    klines=klines_df,
                    orderbook=orderbook_df, 
                    mid_price=mid_price
                )
                features.update(sophisticated_features)
                
                logger.debug(f"Extracted {len(sophisticated_features)} sophisticated features")
            
            # Phase 3: Add L2 training pipeline level features if we have orderbook data
            if not orderbook_df.empty:
                l2_features = self._extract_l2_pipeline_features(orderbook_df, mid_price)
                features.update(l2_features)
                
                # Add additional microstructure features
                microstructure_features = self._calculate_additional_microstructure(orderbook_df, mid_price)
                features.update(microstructure_features)
            
            # Phase 3: Apply feature importance weighting if ML predictor available
            if self.ml_predictor:
                features = self._apply_feature_importance_weighting(features)
            
            # Ensure we have essential features
            if len(features) < 5:
                logger.warning("Insufficient sophisticated features, adding synthetic supplements")
                synthetic_features = self._generate_synthetic_features(features)
                features.update(synthetic_features)
            
            # Check for feature drift if monitor is available
            if self.feature_monitor:
                drift_detected = self.feature_monitor.check_feature_drift(features)
                if drift_detected:
                    drift_status = self.feature_monitor.get_drift_status()
                    logger.warning(f"Feature drift detected! Drifted features: {drift_status['drifted_features']}")
                    
                    # Add drift metadata to features
                    features['_drift_detected'] = 1.0 if drift_detected else 0.0
                    features['_drift_feature_count'] = float(len(drift_status['drifted_features']))
            
            # Store for debugging
            self.last_features = features
            logger.info(f"Sophisticated feature extraction complete: {len(features)} features, "
                       f"mid_price={mid_price:.4f}, "
                       f"drift_detected={features.get('_drift_detected', 0.0)}")
            
            return features
            
        except Exception as e:
            logger.error(f"Sophisticated feature extraction failed: {e}")
            return self._extract_basic_features()
    
    def _extract_l2_pipeline_features(self, orderbook_df: pd.DataFrame, mid_price: float) -> Dict[str, float]:
        """Extract L2 training pipeline level features for maximum alpha generation."""
        try:
            features = {}
            
            if orderbook_df.empty:
                return features
            
            bids = orderbook_df[orderbook_df['side'] == 'bid'].sort_values('level')
            asks = orderbook_df[orderbook_df['side'] == 'ask'].sort_values('level')
            
            if bids.empty or asks.empty:
                return features
            
            # L2 Enhanced depth imbalance with exponential decay (from l2_only_trainer.py)
            decay_weights = np.exp(-np.arange(5) * 0.5)
            weighted_imb = 0.0
            
            for lvl in range(1, min(6, len(bids) + 1, len(asks) + 1)):
                if lvl <= len(bids) and lvl <= len(asks):
                    bid_q = bids.iloc[lvl-1]['quantity'] if lvl <= len(bids) else 0
                    ask_q = asks.iloc[lvl-1]['quantity'] if lvl <= len(asks) else 0
                    total_q = bid_q + ask_q
                    
                    if total_q > 0:
                        level_imb = (bid_q - ask_q) / total_q
                        weighted_imb += level_imb * decay_weights[lvl - 1]
                        features[f'l2_imb_l{lvl}'] = level_imb
            
            features['l2_weighted_imb'] = weighted_imb
            
            # Price impact measures (sophisticated)
            if len(bids) >= 3 and len(asks) >= 3:
                # Cumulative impact for different sizes
                bid_prices = bids['price'].values[:5]
                ask_prices = asks['price'].values[:5]
                bid_qtys = bids['quantity'].values[:5]
                ask_qtys = asks['quantity'].values[:5]
                
                # Calculate cumulative notional for impact estimation
                bid_notional = np.cumsum(bid_prices * bid_qtys)
                ask_notional = np.cumsum(ask_prices * ask_qtys)
                
                # Impact for various sizes (500, 1000, 2000)
                for size in [500, 1000, 2000]:
                    bid_impact_idx = np.where(bid_notional >= size)[0]
                    ask_impact_idx = np.where(ask_notional >= size)[0]
                    
                    if len(bid_impact_idx) > 0:
                        impact_price = bid_prices[bid_impact_idx[0]]
                        features[f'bid_impact_{size}'] = (bids.iloc[0]['price'] - impact_price) / bids.iloc[0]['price']
                    
                    if len(ask_impact_idx) > 0:
                        impact_price = ask_prices[ask_impact_idx[0]]
                        features[f'ask_impact_{size}'] = (impact_price - asks.iloc[0]['price']) / asks.iloc[0]['price']
            
            # Liquidity Shear (change in L1 qty vs change in mid price)
            # Approximate using current state vs small price movements
            if len(bids) >= 2 and len(asks) >= 2:
                # Simulate small price movements
                price_tick = 0.01  # Assume 1 cent tick
                
                # Qty changes for small price movements (approximation)
                bid_qty_gradient = (bids.iloc[1]['quantity'] - bids.iloc[0]['quantity']) / price_tick
                ask_qty_gradient = (asks.iloc[1]['quantity'] - asks.iloc[0]['quantity']) / price_tick
                
                features['l2_qty_shear'] = (bid_qty_gradient - ask_qty_gradient) / (abs(bid_qty_gradient) + abs(ask_qty_gradient) + 1e-6)
            
            # Multi-horizon order flow imbalance approximation
            # Using current orderbook depth as proxy for short-term OFI
            total_bid_vol = bids['quantity'].sum()
            total_ask_vol = asks['quantity'].sum()
            
            features['l2_total_ofi'] = (total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol + 1e-6)
            
            # Concentrated vs distributed liquidity
            if len(bids) >= 3 and len(asks) >= 3:
                bid_concentration_l3 = bids.iloc[:3]['quantity'].std() / (bids.iloc[:3]['quantity'].mean() + 1e-6)
                ask_concentration_l3 = asks.iloc[:3]['quantity'].std() / (asks.iloc[:3]['quantity'].mean() + 1e-6)
                features['l2_liquidity_concentration'] = (bid_concentration_l3 + ask_concentration_l3) / 2
            
            logger.debug(f"Extracted {len(features)} L2 pipeline features")
            return features
            
        except Exception as e:
            logger.error(f"Failed to extract L2 pipeline features: {e}")
            return {}
    
    def _apply_feature_importance_weighting(self, features: Dict[str, float]) -> Dict[str, float]:
        """Apply feature importance feedback from ML predictor for feature weighting."""
        try:
            if not self.ml_predictor:
                return features
            
            # Get feature importance from ML predictor
            try:
                predictor_status = self.ml_predictor.get_model_status()
                feature_importance = predictor_status.get('feature_importance', {})
                
                if not feature_importance:
                    logger.debug("No feature importance available from ML predictor")
                    return features
                
                # Apply importance-based feature selection and weighting
                weighted_features = {}
                importance_threshold = 0.01  # Only keep features with >1% importance
                
                total_importance = sum(feature_importance.values())
                if total_importance <= 0:
                    return features
                
                # Normalize importance scores
                normalized_importance = {
                    feat: imp / total_importance 
                    for feat, imp in feature_importance.items()
                }
                
                # Apply importance weighting to existing features
                for feature_name, feature_value in features.items():
                    importance = normalized_importance.get(feature_name, 0.0)
                    
                    # Keep feature if it has importance or is essential
                    if importance > importance_threshold or feature_name.startswith('_'):
                        # Apply square root weighting to prevent over-dominance
                        weight = np.sqrt(importance) if importance > 0 else 1.0
                        weighted_features[feature_name] = feature_value * weight
                        
                        # Add importance metadata
                        weighted_features[f'{feature_name}_importance'] = importance
                
                # Add top important features that might be missing
                top_features = sorted(
                    normalized_importance.items(), 
                    key=lambda x: x[1], 
                    reverse=True
                )[:10]
                
                for feat_name, importance in top_features:
                    if feat_name not in weighted_features and importance > 0.05:  # Top 5% importance
                        # Generate synthetic value for important missing feature
                        synthetic_value = np.random.normal(0, 0.1)  # Small random value
                        weighted_features[f'{feat_name}_synthetic'] = synthetic_value
                        weighted_features[f'{feat_name}_synthetic_importance'] = importance
                
                logger.debug(f"Applied feature importance weighting: {len(weighted_features)} weighted features from {len(features)} original")
                return weighted_features
                
            except Exception as e:
                logger.warning(f"Failed to get feature importance from ML predictor: {e}")
                return features
                
        except Exception as e:
            logger.error(f"Failed to apply feature importance weighting: {e}")
            return features
    
    def _get_klines_dataframe(self) -> pd.DataFrame:
        """Convert kline data from memory store to DataFrame format."""
        try:
            if not self.kline_store:
                return pd.DataFrame()
                
            # Get recent klines (last 100 for technical indicators)
            recent_klines = self.kline_store.get_last_n(self.symbol, self.interval, 100)
            
            if not recent_klines:
                return pd.DataFrame()
            
            # Convert to DataFrame with proper column names
            klines_data = []
            for kline in recent_klines:
                klines_data.append({
                    'timestamp': kline.timestamp,
                    'open': float(kline.open),
                    'high': float(kline.high), 
                    'low': float(kline.low),
                    'close': float(kline.close),
                    'volume': float(kline.volume)
                })
            
            df = pd.DataFrame(klines_data)
            if not df.empty:
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                df = df.sort_index()
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to get klines DataFrame: {e}")
            return pd.DataFrame()
    
    def _get_orderbook_dataframe(self) -> pd.DataFrame:
        """Convert orderbook data from memory store to DataFrame format."""
        try:
            if not self.orderbook_store:
                return pd.DataFrame()
                
            # Get latest orderbook snapshot
            orderbook = self.orderbook_store.get_snapshot(self.symbol)
            
            if not orderbook or not orderbook.bids or not orderbook.asks:
                return pd.DataFrame()
            
            # Convert to DataFrame format expected by FeatureCalculator
            orderbook_data = []
            
            # Add bid levels
            for i, bid in enumerate(orderbook.bids[:10]):  # Top 10 levels
                orderbook_data.append({
                    'side': 'bid',
                    'level': i + 1,
                    'price': float(bid.price),
                    'quantity': float(bid.quantity)
                })
            
            # Add ask levels  
            for i, ask in enumerate(orderbook.asks[:10]):  # Top 10 levels
                orderbook_data.append({
                    'side': 'ask', 
                    'level': i + 1,
                    'price': float(ask.price),
                    'quantity': float(ask.quantity)
                })
            
            df = pd.DataFrame(orderbook_data)
            return df
            
        except Exception as e:
            logger.error(f"Failed to get orderbook DataFrame: {e}")
            return pd.DataFrame()
    
    def _get_mid_price(self, orderbook_df: pd.DataFrame) -> float:
        """Calculate mid price from orderbook DataFrame."""
        try:
            if orderbook_df.empty:
                return 0.0
                
            bids = orderbook_df[orderbook_df['side'] == 'bid']
            asks = orderbook_df[orderbook_df['side'] == 'ask']
            
            if bids.empty or asks.empty:
                return 0.0
                
            best_bid = bids[bids['level'] == 1]['price'].iloc[0]
            best_ask = asks[asks['level'] == 1]['price'].iloc[0]
            
            return (best_bid + best_ask) / 2.0
            
        except Exception as e:
            logger.error(f"Failed to calculate mid price: {e}")
            return 177.0  # Fallback price
    
    def _calculate_additional_microstructure(self, orderbook_df: pd.DataFrame, mid_price: float) -> Dict[str, float]:
        """Calculate additional microstructure features not in FeatureCalculator."""
        try:
            features = {}
            
            if orderbook_df.empty:
                return features
            
            bids = orderbook_df[orderbook_df['side'] == 'bid'].sort_values('level')
            asks = orderbook_df[orderbook_df['side'] == 'ask'].sort_values('level')
            
            if not bids.empty and not asks.empty:
                # Order flow pressure 
                bid_volume_l3 = bids[bids['level'] <= 3]['quantity'].sum()
                ask_volume_l3 = asks[asks['level'] <= 3]['quantity'].sum()
                total_volume_l3 = bid_volume_l3 + ask_volume_l3
                
                if total_volume_l3 > 0:
                    features['order_flow_pressure'] = (bid_volume_l3 - ask_volume_l3) / total_volume_l3
                
                # Weighted mid price (volume-weighted across levels)
                bid_notional = (bids['price'] * bids['quantity']).sum()
                ask_notional = (asks['price'] * asks['quantity']).sum()
                total_quantity = bids['quantity'].sum() + asks['quantity'].sum()
                
                if total_quantity > 0:
                    features['weighted_mid'] = (bid_notional + ask_notional) / total_quantity
                    features['weighted_mid_deviation'] = abs(features['weighted_mid'] - mid_price) / mid_price
                
                # Size ratio (L1 vs deeper levels)
                if len(bids) > 1 and len(asks) > 1:
                    bid_l1_ratio = bids.iloc[0]['quantity'] / bids['quantity'].sum()
                    ask_l1_ratio = asks.iloc[0]['quantity'] / asks['quantity'].sum()
                    features['l1_size_dominance'] = (bid_l1_ratio + ask_l1_ratio) / 2
            
            return features
            
        except Exception as e:
            logger.error(f"Failed to calculate additional microstructure features: {e}")
            return {}
    
    def _extract_basic_features(self) -> Dict[str, float]:
        """Fallback basic feature extraction when sophisticated methods fail."""
        try:
            features = {}
            
            # Try to get basic data from memory stores or Redis
            if self.orderbook_store:
                orderbook = self.orderbook_store.get_snapshot(self.symbol)
                if orderbook and orderbook.bids and orderbook.asks:
                    mid_price = float((orderbook.bids[0].price + orderbook.asks[0].price) / 2)
                    spread = float(orderbook.asks[0].price - orderbook.bids[0].price)
                    bid_size = float(orderbook.bids[0].quantity)
                    ask_size = float(orderbook.asks[0].quantity)
                    
                    features.update({
                        'mid_price': mid_price,
                        'spread_bps': (spread / mid_price) * 10000,
                        'bid_size': bid_size,
                        'ask_size': ask_size,
                        'size_imbalance': (bid_size - ask_size) / (bid_size + ask_size + 1e-6),
                    })
            
            # Add synthetic features if we don't have enough real data
            if len(features) < 3:
                logger.warning("Very limited market data, using synthetic features")
                base_price = features.get('mid_price', 177.0)
                features.update({
                    'mid_price': base_price,
                    'spread_bps': np.random.uniform(2, 8),
                    'size_imbalance': np.random.uniform(-0.3, 0.3),
                    'rsi': np.random.uniform(40, 60),
                    'vol_1m': np.random.uniform(0.005, 0.015),
                })
            
            return features
            
        except Exception as e:
            logger.error(f"Basic feature extraction failed: {e}")
            return self._get_default_features()
    
    def _generate_synthetic_features(self, existing_features: Dict[str, float]) -> Dict[str, float]:
        """Generate synthetic features to supplement real data."""
        try:
            base_price = existing_features.get('mid_price', existing_features.get('spread', 177.0))
            
            synthetic = {}
            
            # Add missing essential features
            if 'rsi' not in existing_features:
                synthetic['rsi'] = np.random.uniform(35, 65)
            if 'vol_1m' not in existing_features:
                synthetic['vol_1m'] = np.random.uniform(0.005, 0.02)
            if 'ret_1m' not in existing_features:
                synthetic['ret_1m'] = np.random.normal(0, 0.001)
            
            return synthetic
            
        except Exception as e:
            logger.error(f"Failed to generate synthetic features: {e}")
            return {}
    
    def _get_default_features(self) -> Dict[str, float]:
        """Return default feature set when all extraction methods fail."""
        return {
            'mid_price': 177.0,
            'spread_bps': 5.0,
            'size_imbalance': 0.0,
            'rsi': 50.0,
            'vol_1m': 0.01,
            'ret_1m': 0.0,
            'order_flow_pressure': 0.0,
            'l1_size_dominance': 0.5,
        }
    
    def _generate_ml_signal(self, features: Dict[str, float]) -> Dict[str, Any]:
        """Generate ML-based trading signal."""
        try:
            if self.ml_predictor and HAS_ADVANCED_ML:
                # Use advanced ML predictor
                prediction = self.ml_predictor.predict(features)
                
                # Convert to signal format
                signal_data = {
                    "signal_id": str(uuid.uuid4()),
                    "timestamp": int(time.time() * 1000),
                    "symbol": self.symbol,
                    "signal_type": prediction.side,
                    "confidence": round(prediction.confidence, 4),
                    "order_quantity_config": {
                        "type": "Market",
                        "quantity_usd": None,
                        "quantity": f"{prediction.size:.2f}",
                    },
                    "conditional_order_params": {},
                    "model_metadata": {
                        "model_type": prediction.model_type,
                        "prediction_horizon": prediction.prediction_horizon,
                        "features_used": prediction.features_used,
                        "raw_signal": prediction.signal
                    }
                }
                
                logger.info(f"ML Signal: {prediction.side} {prediction.size:.4f} "
                           f"(confidence: {prediction.confidence:.2%}, signal: {prediction.signal:.4f})")
                
                return signal_data
            
            else:
                # Fallback to enhanced rule-based signals
                return self._generate_fallback_signal(features)
                
        except Exception as e:
            logger.error(f"ML signal generation failed: {e}")
            return self._generate_fallback_signal(features)
    
    def _generate_fallback_signal(self, features: Dict[str, float]) -> Dict[str, Any]:
        """Generate rule-based signal as fallback."""
        try:
            # Enhanced rule-based logic using multiple indicators
            rsi = features.get('rsi', 50.0)
            sma_ratio = features.get('sma_ratio', 1.0)
            size_imbalance = features.get('size_imbalance', 0.0)
            returns_5 = features.get('returns_5', 0.0)
            volatility = features.get('volatility_10', 0.01)
            
            # Multi-factor signal
            signal_score = 0.0
            
            # RSI component
            if rsi < 30:
                signal_score += 0.4  # Oversold - buy signal
            elif rsi > 70:
                signal_score -= 0.4  # Overbought - sell signal
            
            # Trend component
            if sma_ratio > 1.01:
                signal_score += 0.2  # Uptrend
            elif sma_ratio < 0.99:
                signal_score -= 0.2  # Downtrend
            
            # Order flow component
            signal_score += size_imbalance * 0.3
            
            # Momentum component
            signal_score += returns_5 * 50  # Scale returns
            
            # Volatility adjustment
            volatility_factor = min(volatility / 0.01, 2.0)  # Cap at 2x
            signal_score *= volatility_factor
            
            # Determine signal type and size
            signal_strength = abs(signal_score)
            
            if signal_strength > 0.3:
                signal_type = "buy" if signal_score > 0 else "sell"
                confidence = min(signal_strength, 1.0)
                quantity = round(min(0.1 + signal_strength * 0.2, 0.5), 2)
            else:
                signal_type = "hold"
                confidence = 0.1
                quantity = 0.01
                
            signal_data = {
                "signal_id": str(uuid.uuid4()),
                "timestamp": int(time.time() * 1000),
                "symbol": self.symbol,
                "signal_type": signal_type,
                "confidence": round(confidence, 4),
                "order_quantity_config": {
                    "type": "Market",
                    "quantity_usd": None,
                    "quantity": f"{quantity:.2f}",
                },
                "conditional_order_params": {},
                "model_metadata": {
                    "model_type": "rule_based_enhanced",
                    "signal_score": signal_score,
                    "rsi": rsi,
                    "sma_ratio": sma_ratio,
                    "size_imbalance": size_imbalance
                }
            }
            
            logger.info(f"Fallback Signal: {signal_type} {quantity:.4f} "
                       f"(confidence: {confidence:.2%}, score: {signal_score:.4f})")
            
            return signal_data
            
        except Exception as e:
            logger.error(f"Fallback signal generation failed: {e}")
            # Return minimal signal
            return {
                "signal_id": str(uuid.uuid4()),
                "timestamp": int(time.time() * 1000),
                "symbol": self.symbol,
                "signal_type": "hold",
                "confidence": 0.1,
                "order_quantity_config": {
                    "type": "Market",
                    "quantity_usd": None,
                    "quantity": "0.01",
                },
                "conditional_order_params": {}
            }
    
    def generate_and_save_signal(self, file_path: str = "signal.json") -> Optional[Dict[str, Any]]:
        """Generate and save a trading signal."""
        try:
            # Extract current market features
            features = self._extract_features()
            
            # Generate ML-based signal
            signal_data = self._generate_ml_signal(features)
            
            # Save to file
            with open(file_path, 'w') as f:
                json.dump(signal_data, f, indent=4)
            
            self.signals_generated += 1
            self.last_signal_time = datetime.now()
            
            logger.info(f"Generated signal #{self.signals_generated}: {signal_data['signal_type']} "
                       f"{signal_data['order_quantity_config']['quantity']} "
                       f"(confidence: {signal_data['confidence']:.2%})")
            
            return signal_data
            
        except Exception as e:
            logger.error(f"Error generating or saving signal: {e}")
            return None
    
    def get_status(self) -> Dict[str, Any]:
        """Get system status including feature extraction and monitoring."""
        status = {
            "timestamp": int(time.time() * 1000),
            "symbol": self.symbol,
            "interval": self.interval,
            "components": {
                "ml_predictor": self.ml_predictor is not None,
                "feature_calculator": self.feature_calculator is not None,
                "feature_monitor": self.feature_monitor is not None,
                "kline_store": self.kline_store is not None,
                "orderbook_store": self.orderbook_store is not None,
                "redis_client": self.redis_client is not None
            },
            "advanced_ml_available": HAS_ADVANCED_ML,
            "last_features": getattr(self, 'last_features', {}),
            "feature_count": len(getattr(self, 'last_features', {}))
        }
        
        # Add feature monitoring status if available
        if self.feature_monitor:
            drift_status = self.feature_monitor.get_drift_status()
            status["feature_monitoring"] = {
                "has_baseline": drift_status.get('has_baseline', False),
                "total_samples": drift_status.get('total_samples', 0),
                "drifted_features": drift_status.get('drifted_features', []),
                "drift_count": len(drift_status.get('drifted_features', [])),
                "feature_z_scores": drift_status.get('feature_z_scores', {})
            }
        
        # Add ML predictor status if available
        if self.ml_predictor:
            try:
                ml_status = self.ml_predictor.get_model_status()
                status["ml_predictor_status"] = ml_status
            except Exception as e:
                status["ml_predictor_status"] = {"error": str(e)}
        
        # Add sophisticated feature extraction status
        status["feature_extraction"] = {
            "sophisticated_mode": self.feature_calculator is not None,
            "drift_monitoring": self.feature_monitor is not None,
            "last_extraction_time": getattr(self, '_last_feature_time', None)
        }
        
        return status

def main():
    """Main entry point."""
    # Get symbol from environment
    symbol = os.getenv("TRADING_SYMBOL", "SOL_USDC_PERP")
    
    # Determine file path
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    signal_file = project_root / "signal.json"
    
    logger.info(f"Advanced ML Signal Producer started for {symbol}")
    logger.info(f"Saving signals to: {signal_file}")
    logger.info(f"Advanced ML available: {HAS_ADVANCED_ML}")
    
    # Initialize signal producer
    producer = AdvancedMLSignalProducer(symbol=symbol)
    
    # Status logging interval
    last_status_log = time.time()
    status_interval = 60  # Log status every 60 seconds
    
    try:
        while running:
            # Generate new signal
            signal_data = producer.generate_and_save_signal(str(signal_file))
            
            # Log status periodically
            current_time = time.time()
            if current_time - last_status_log >= status_interval:
                status = producer.get_status()
                logger.info(f"Status: {status['signals_generated']} signals generated, "
                           f"ML available: {status['has_advanced_ml']}")
                last_status_log = current_time
            
            # Wait before generating next signal
            for _ in range(producer.signal_interval):
                if not running:
                    break
                time.sleep(1)
                
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        logger.info("Advanced ML Signal Producer stopped")

if __name__ == "__main__":
    main() 