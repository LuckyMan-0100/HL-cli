"""
feature_engineering/calculator.py
---------------------------------
Loads OHLCV Parquet (written by gather_ohlcv.py), computes a suite of technical
indicators with `pandas_ta`, and writes a feature set to
`data/features.parquet`.

Run:
    python -m feature_engineering.calculator
"""

import pathlib
import numpy as np
np.NaN = np.nan
import pandas as pd
from typing import Dict, List, Tuple, Optional
import logging
from datetime import datetime, timedelta
import time
import pyarrow as pa
import pyarrow.parquet as pq
from .orderbook_reader import OrderbookReader

import pandas_ta as ta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

INDICATORS = {
    "rsi": dict(length=14),
    "macd": dict(fast=12, slow=26, signal=9),
    "bbands": dict(length=20, std=2.0),
    "atr": dict(length=14),
}


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out.ta.rsi(close="close", append=True, **INDICATORS["rsi"])
    out.ta.macd(close="close", append=True, **INDICATORS["macd"])
    out.ta.bbands(close="close", append=True, **INDICATORS["bbands"])
    out.ta.atr(high="high", low="low", close="close", append=True, **INDICATORS["atr"])

    # Drop rows that do not have all indicator values
    return out.dropna()


def main() -> None:
    in_path = pathlib.Path("data/ohlcv.parquet")
    if not in_path.exists():
        raise FileNotFoundError(
            "data/ohlcv.parquet not found. Run `python scripts/gather_ohlcv.py` first."
        )

    df = pd.read_parquet(in_path)
    features = add_indicators(df)

    out_path = pathlib.Path("data/features.parquet")
    features.to_parquet(out_path)
    print(f"Generated features: {len(features)} rows ➜ {out_path}")


class Features:
    """Feature calculator for market data."""
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.reader = OrderbookReader(symbol)
        
    def calculate_features(self) -> pd.DataFrame:
        """Calculate all features."""
        # Get latest data
        snapshot = self.reader.get_snapshot()
        if snapshot.empty:
            return pd.DataFrame()
            
        # Calculate features
        features = {}
        features.update(self._calculate_orderbook_features(snapshot))
        
        return pd.DataFrame([features])
        
    def _calculate_orderbook_features(self, snapshot: pd.DataFrame) -> Dict:
        """Calculate orderbook-based features."""
        features = {}
        
        # Basic features
        features['spread'] = snapshot['ask_price'].iloc[0] - snapshot['bid_price'].iloc[0]
        features['mid_price'] = (snapshot['ask_price'].iloc[0] + snapshot['bid_price'].iloc[0]) / 2
        
        # Volume imbalance
        bid_vol = snapshot['bid_qty'].sum()
        ask_vol = snapshot['ask_qty'].sum()
        features['volume_imbalance'] = (bid_vol - ask_vol) / (bid_vol + ask_vol)
        
        return features


class FeatureCalculator:
    """Calculate features for high-frequency trading strategy."""
    
    def __init__(self):
        self.price_levels = 10  # Number of price levels to consider
        self.volume_threshold = 1000  # Minimum volume for liquidity analysis
        
    def calculate(self, klines: pd.DataFrame, orderbook: pd.DataFrame, mid_price: float) -> Dict[str, float]:
        """Calculate all features for strategy decisions."""
        features = {}
        
        # L2 Orderbook Features
        if not orderbook.empty:
            features.update(self._calculate_l2_features(orderbook))
            
        # Price Action Features
        if not klines.empty:
            features.update(self._calculate_price_features(klines, mid_price))
            
        # Microstructure Features
        features.update(self._calculate_microstructure(orderbook, mid_price))
        
        return features
        
    def _calculate_l2_features(self, orderbook: pd.DataFrame) -> Dict[str, float]:
        """Calculate sophisticated L2 orderbook features."""
        features = {}
        
        # Basic orderbook features
        bids = orderbook[orderbook['side'] == 'bid'].iloc[:self.price_levels]
        asks = orderbook[orderbook['side'] == 'ask'].iloc[:self.price_levels]
        
        # Spread and mid price
        best_bid = bids['price'].iloc[0]
        best_ask = asks['price'].iloc[0]
        spread = best_ask - best_bid
        mid = (best_ask + best_bid) / 2
        
        features['spread'] = spread
        features['spread_bps'] = (spread / mid) * 10000  # Spread in basis points
        
        # Volume imbalance at different levels
        bid_volumes = bids['quantity'].values
        ask_volumes = asks['quantity'].values
        
        features['vol_imb_L1'] = (bid_volumes[0] - ask_volumes[0]) / (bid_volumes[0] + ask_volumes[0])
        features['vol_imb_L3'] = (bid_volumes[:3].sum() - ask_volumes[:3].sum()) / (bid_volumes[:3].sum() + ask_volumes[:3].sum())
        features['vol_imb_L5'] = (bid_volumes[:5].sum() - ask_volumes[:5].sum()) / (bid_volumes[:5].sum() + ask_volumes[:5].sum())
        
        # Price impact estimates
        bid_notional = (bids['price'] * bids['quantity']).cumsum()
        ask_notional = (asks['price'] * asks['quantity']).cumsum()
        
        features['bid_impact_1k'] = (best_bid - bids['price'][bid_notional >= 1000].iloc[0]) / best_bid if len(bid_notional[bid_notional >= 1000]) > 0 else 0
        features['ask_impact_1k'] = (asks['price'][ask_notional >= 1000].iloc[0] - best_ask) / best_ask if len(ask_notional[ask_notional >= 1000]) > 0 else 0
        
        # Liquidity concentration
        features['bid_concentration'] = bid_volumes[0] / bid_volumes.sum()
        features['ask_concentration'] = ask_volumes[0] / ask_volumes.sum()
        
        return features
        
    def _calculate_price_features(self, klines: pd.DataFrame, mid_price: float) -> Dict[str, float]:
        """Calculate price action features."""
        features = {}
        
        # Add technical indicators
        klines_with_indicators = add_indicators(klines)
        if not klines_with_indicators.empty:
            last_row = klines_with_indicators.iloc[-1]
            features.update({
                'rsi': last_row.get('RSI_14', 50),
                'macd': last_row.get('MACD_12_26_9', 0),
                'bb_upper': last_row.get('BBU_20_2.0', mid_price * 1.02),
                'bb_lower': last_row.get('BBL_20_2.0', mid_price * 0.98),
                'atr': last_row.get('ATR_14', mid_price * 0.01)
            })
            
        # Short-term momentum
        returns = klines['close'].pct_change()
        features['ret_1m'] = returns.iloc[-1]
        features['ret_5m'] = returns.iloc[-5:].mean()
        features['vol_1m'] = returns.iloc[-60:].std()
        
        return features
        
    def _calculate_microstructure(self, orderbook: pd.DataFrame, mid_price: float) -> Dict[str, float]:
        """Calculate market microstructure features."""
        features = {}
        
        # Liquidity analysis
        bids = orderbook[orderbook['side'] == 'bid']
        asks = orderbook[orderbook['side'] == 'ask']
        
        # Depth analysis
        bid_depth = bids[bids['quantity'] >= self.volume_threshold]['price'].count()
        ask_depth = asks[asks['quantity'] >= self.volume_threshold]['price'].count()
        
        features['bid_depth'] = bid_depth
        features['ask_depth'] = ask_depth
        
        # Safe division for depth imbalance
        total_depth = bid_depth + ask_depth
        features['depth_imbalance'] = (bid_depth - ask_depth) / total_depth if total_depth > 0 else 0.0
        
        # Price clustering with safe handling of empty arrays
        bid_prices = bids['price'].values[:self.price_levels]
        ask_prices = asks['price'].values[:self.price_levels]
        
        # Safe calculation of price gaps
        features['bid_price_gaps'] = np.diff(bid_prices).mean() if len(bid_prices) > 1 else 0.0
        features['ask_price_gaps'] = np.diff(ask_prices).mean() if len(ask_prices) > 1 else 0.0
        
        return features


if __name__ == "__main__":
    calculator = Features("SOL_USDC_PERP")
    features_df = calculator.calculate_features()
    if not features_df.empty:
        out_path = pathlib.Path("data/features.parquet")
        features_df.to_parquet(out_path)
        print(f"Generated features: {len(features_df)} rows ➜ {out_path}")
    else:
        print("No features calculated. Snapshot is empty.")