import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from decimal import Decimal
import talib
from dataclasses import dataclass

from data_ingestion.models import OrderBook, Kline
from config.settings import settings

@dataclass
class Features:
    """Container for all calculated features."""
    # Order book features
    mid_price: float
    imbalance_1pct: float
    depth_ratio: float
    micro_price: float
    spread_bps: float  # Spread in basis points

    # Technical indicators
    rsi_14: float
    macd: float
    macd_signal: float
    macd_hist: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_width: float
    bb_pct: float  # Current price position within BB
    atr_14: float
    atr_14_pct: float  # ATR as percentage of price

    # Volatility and momentum
    returns_1m: float
    returns_5m: float
    volatility_1h: float
    volume_1m_usd: float
    volume_ma_ratio: float  # Current volume vs 10-period MA

class FeatureCalculator:
    """Calculates technical and order book features."""

    def __init__(self):
        """Initialize the calculator with configuration."""
        self.symbol = settings.trading.symbol

    def _calculate_orderbook_features(self, orderbook: OrderBook) -> Dict[str, float]:
        """Calculate features from the current order book state."""
        features = {}

        # Basic order book features
        mid_price = float(orderbook.mid_price or 0)
        features['mid_price'] = mid_price

        best_bid = orderbook.best_bid
        best_ask = orderbook.best_ask
        
        if best_bid and best_ask and mid_price > 0:
            spread = float(best_ask.price - best_bid.price)
            features['spread_bps'] = (spread / mid_price) * 10000  # Convert to basis points
        else:
            features['spread_bps'] = 0

        # Imbalance within 1% of mid price
        imbalance = orderbook.get_imbalance_1pct()
        features['imbalance_1pct'] = float(imbalance if imbalance is not None else 0)

        # Depth ratio
        depth_ratio = orderbook.get_depth_ratio()
        features['depth_ratio'] = float(depth_ratio if depth_ratio is not None else 1.0)

        # Micro price
        micro_price = orderbook.get_micro_price()
        features['micro_price'] = float(micro_price if micro_price is not None else mid_price)

        return features

    def _calculate_technical_indicators(
        self, 
        klines: List[Kline],
        price_type: str = 'close'
    ) -> Dict[str, float]:
        """Calculate technical indicators from kline data."""
        if not klines:
            return self._get_default_technical_features()

        # Convert klines to numpy arrays
        prices = np.array([float(getattr(k, price_type)) for k in klines])
        highs = np.array([float(k.high) for k in klines])
        lows = np.array([float(k.low) for k in klines])
        volumes = np.array([float(k.volume) for k in klines])

        features = {}

        # RSI
        features['rsi_14'] = talib.RSI(prices, timeperiod=14)[-1]

        # MACD
        macd, signal, hist = talib.MACD(
            prices, 
            fastperiod=12, 
            slowperiod=26, 
            signalperiod=9
        )
        features['macd'] = macd[-1]
        features['macd_signal'] = signal[-1]
        features['macd_hist'] = hist[-1]

        # Bollinger Bands
        upper, middle, lower = talib.BBANDS(
            prices,
            timeperiod=20,
            nbdevup=2,
            nbdevdn=2,
            matype=0
        )
        features['bb_upper'] = upper[-1]
        features['bb_middle'] = middle[-1]
        features['bb_lower'] = lower[-1]
        
        # BB width and position
        bb_width = (upper[-1] - lower[-1]) / middle[-1]
        features['bb_width'] = bb_width
        
        if prices[-1] > upper[-1]:
            bb_pct = 1.0
        elif prices[-1] < lower[-1]:
            bb_pct = 0.0
        else:
            bb_pct = (prices[-1] - lower[-1]) / (upper[-1] - lower[-1])
        features['bb_pct'] = bb_pct

        # ATR
        atr = talib.ATR(highs, lows, prices, timeperiod=14)[-1]
        features['atr_14'] = atr
        features['atr_14_pct'] = (atr / prices[-1]) * 100

        # Returns
        features['returns_1m'] = (prices[-1] / prices[-2] - 1) * 100 if len(prices) > 1 else 0
        features['returns_5m'] = (prices[-1] / prices[-5] - 1) * 100 if len(prices) > 5 else 0

        # Volatility (standard deviation of returns)
        returns = np.diff(np.log(prices))
        features['volatility_1h'] = np.std(returns[-60:]) * 100 if len(returns) >= 60 else 0

        # Volume
        features['volume_1m_usd'] = volumes[-1] * prices[-1]
        volume_ma = np.mean(volumes[-10:])
        features['volume_ma_ratio'] = volumes[-1] / volume_ma if volume_ma > 0 else 1.0

        return features

    def _get_default_technical_features(self) -> Dict[str, float]:
        """Return default values when technical indicators cannot be calculated."""
        return {
            'rsi_14': 50.0,
            'macd': 0.0,
            'macd_signal': 0.0,
            'macd_hist': 0.0,
            'bb_upper': 0.0,
            'bb_middle': 0.0,
            'bb_lower': 0.0,
            'bb_width': 0.0,
            'bb_pct': 0.5,
            'atr_14': 0.0,
            'atr_14_pct': 0.0,
            'returns_1m': 0.0,
            'returns_5m': 0.0,
            'volatility_1h': 0.0,
            'volume_1m_usd': 0.0,
            'volume_ma_ratio': 1.0
        }

    def calculate_features(
        self, 
        orderbook: OrderBook,
        klines: List[Kline]
    ) -> Features:
        """Calculate all features from order book and kline data."""
        # Get order book features
        ob_features = self._calculate_orderbook_features(orderbook)
        
        # Get technical indicators
        tech_features = self._calculate_technical_indicators(klines)
        
        # Combine all features
        return Features(
            # Order book features
            mid_price=ob_features['mid_price'],
            imbalance_1pct=ob_features['imbalance_1pct'],
            depth_ratio=ob_features['depth_ratio'],
            micro_price=ob_features['micro_price'],
            spread_bps=ob_features['spread_bps'],
            
            # Technical indicators
            rsi_14=tech_features['rsi_14'],
            macd=tech_features['macd'],
            macd_signal=tech_features['macd_signal'],
            macd_hist=tech_features['macd_hist'],
            bb_upper=tech_features['bb_upper'],
            bb_middle=tech_features['bb_middle'],
            bb_lower=tech_features['bb_lower'],
            bb_width=tech_features['bb_width'],
            bb_pct=tech_features['bb_pct'],
            atr_14=tech_features['atr_14'],
            atr_14_pct=tech_features['atr_14_pct'],
            
            # Volatility and momentum
            returns_1m=tech_features['returns_1m'],
            returns_5m=tech_features['returns_5m'],
            volatility_1h=tech_features['volatility_1h'],
            volume_1m_usd=tech_features['volume_1m_usd'],
            volume_ma_ratio=tech_features['volume_ma_ratio']
        )

    def features_to_array(self, features: Features) -> np.ndarray:
        """Convert Features object to numpy array for ML model input."""
        return np.array([
            features.imbalance_1pct,
            features.depth_ratio,
            features.spread_bps,
            features.rsi_14,
            features.macd,
            features.macd_signal,
            features.macd_hist,
            features.bb_width,
            features.bb_pct,
            features.atr_14_pct,
            features.returns_1m,
            features.returns_5m,
            features.volatility_1h,
            features.volume_ma_ratio
        ], dtype=np.float32) 