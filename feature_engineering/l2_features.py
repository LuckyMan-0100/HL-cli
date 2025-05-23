"""L2 (order book) feature calculations."""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple

from .validation_schema import L2FeaturesSchema

def calculate_queue_imbalance(bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]) -> float:
    """
    Calculate queue imbalance from order book sides.
    
    Args:
        bids: List of (price, quantity) tuples for bid side
        asks: List of (price, quantity) tuples for ask side
        
    Returns:
        Queue imbalance in [-1, 1] range
    """
    bid_qty = sum(qty for _, qty in bids[:3])  # Top 3 levels
    ask_qty = sum(qty for _, qty in asks[:3])
    
    total_qty = bid_qty + ask_qty
    if total_qty == 0:
        return 0.0
        
    return (bid_qty - ask_qty) / total_qty

def calculate_order_flow_imbalance(
    bids: List[Tuple[float, float]],
    asks: List[Tuple[float, float]],
    window: int = 10
) -> float:
    """
    Calculate order flow imbalance (OFI) from order book sides.
    
    Args:
        bids: List of (price, quantity) tuples for bid side
        asks: List of (price, quantity) tuples for ask side
        window: Number of levels to consider
        
    Returns:
        OFI in [-1, 1] range
    """
    bid_qty = sum(qty for _, qty in bids[:window])
    ask_qty = sum(qty for _, qty in asks[:window])
    
    total_qty = bid_qty + ask_qty
    if total_qty == 0:
        return 0.0
        
    return (bid_qty - ask_qty) / total_qty

def calculate_depth_slope(
    prices: List[float],
    quantities: List[float],
    reference_price: float
) -> float:
    """
    Calculate depth curve slope.
    
    Args:
        prices: List of prices
        quantities: List of quantities
        reference_price: Reference price for normalization
        
    Returns:
        Slope of the depth curve
    """
    if not prices or not quantities:
        return 0.0
        
    # Normalize prices
    norm_prices = [(p - reference_price) / reference_price for p in prices]
    
    # Calculate cumulative quantities
    cum_qty = np.cumsum(quantities)
    
    # Fit line to normalized depth curve
    if len(norm_prices) > 1:
        slope, _ = np.polyfit(norm_prices, cum_qty, 1)
        return slope
    return 0.0

def build_l2_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build L2 features from order book data.
    
    Args:
        df: DataFrame with order book data
        
    Returns:
        DataFrame with L2 features
    """
    features = pd.DataFrame(index=df.index)
    
    # Price-based features
    mid = (df['ask_px_1'] + df['bid_px_1']) / 2
    spread = df['ask_px_1'] - df['bid_px_1']
    features['rel_spread'] = spread / mid
    features['spread_ma'] = features['rel_spread'].rolling(10).mean()
    features['spread_std'] = features['rel_spread'].rolling(10).std()
    features['spread_ticks'] = spread / spread.min()
    
    # Volume imbalance
    features['vol_imb'] = (df['bid_qty_1'] - df['ask_qty_1']) / (df['bid_qty_1'] + df['ask_qty_1'])
    
    # Order flow imbalance at different horizons
    for lag in (1, 3, 10):
        delta_bid = df['bid_qty_1'].diff(lag)
        delta_ask = df['ask_qty_1'].diff(lag)
        vol_norm = df['bid_qty_1'].rolling(100).mean() + df['ask_qty_1'].rolling(100).mean()
        raw_ofi = (delta_bid - delta_ask) / vol_norm
        features[f'ofi_{lag}'] = raw_ofi.clip(-10, 10)
        features[f'ofi_{lag}_ma'] = raw_ofi.ewm(span=5).mean()
        features[f'ofi_{lag}_std'] = raw_ofi.rolling(5).std()
    
    # Microprice features
    w_bid = df['ask_qty_1'] / (df['ask_qty_1'] + df['bid_qty_1'])
    w_ask = df['bid_qty_1'] / (df['ask_qty_1'] + df['bid_qty_1'])
    mp = w_bid * df['bid_px_1'] + w_ask * df['ask_px_1']
    features['mp_slope'] = mp.diff(2)  # 2-tick latency
    features['mp_accel'] = features['mp_slope'].diff()
    
    # Flow-weighted microprice
    flow_weights = pd.DataFrame({
        'bid': features['ofi_1'].clip(-1, 1).add(1).div(2),
        'ask': features['ofi_1'].clip(-1, 1).mul(-1).add(1).div(2)
    })
    flow_mp = df['bid_px_1'] * flow_weights['bid'] + df['ask_px_1'] * flow_weights['ask']
    features['flow_mp_slope'] = flow_mp.diff(2)
    
    # Queue position features
    for lvl in (1, 2):
        bid_depth_ma = df[f'bid_qty_{lvl}'].rolling(100).mean()
        ask_depth_ma = df[f'ask_qty_{lvl}'].rolling(100).mean()
        
        features[f'bid_depth_ratio_{lvl}'] = df[f'bid_qty_{lvl}'] / bid_depth_ma
        features[f'ask_depth_ratio_{lvl}'] = df[f'ask_qty_{lvl}'] / ask_depth_ma
    
    # Fill probability
    bid_imb = df.apply(lambda x: calculate_queue_imbalance(
        [(x[f'bid_px_{i}'], x[f'bid_qty_{i}']) for i in range(1, 4)],
        [(x[f'ask_px_{i}'], x[f'ask_qty_{i}']) for i in range(1, 4)]
    ), axis=1)
    
    ofi = df.apply(lambda x: calculate_order_flow_imbalance(
        [(x[f'bid_px_{i}'], x[f'bid_qty_{i}']) for i in range(1, 11)],
        [(x[f'ask_px_{i}'], x[f'ask_qty_{i}']) for i in range(1, 11)]
    ), axis=1)
    
    features['fill_prob'] = 0.5 + 0.5 * (bid_imb + ofi) / 2
    
    # Validate features
    return L2FeaturesSchema.validate(features)

# Example usage:
# bids = [(100.0, 1.0), (99.0, 2.0), ...]
# asks = [(101.0, 1.5), (102.0, 2.5), ...]
# features = calculate_l2_features("BTC_USD", 1234567890, bids, asks) 