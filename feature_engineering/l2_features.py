import numpy as np
import pandas as pd
from typing import Tuple, List, Dict
from .validation_schema import L2FeaturesSchema

def calculate_queue_imbalance(bids: List[Tuple[float, float]], 
                            asks: List[Tuple[float, float]]) -> float:
    """
    Calculate queue imbalance at best bid/ask.
    
    Args:
        bids: List of (price, quantity) tuples for bids
        asks: List of (price, quantity) tuples for asks
        
    Returns:
        float: Queue imbalance in range [-1, 1]
    """
    if not bids or not asks:
        return 0.0
        
    best_bid_qty = bids[0][1]
    best_ask_qty = asks[0][1]
    
    total = best_bid_qty + best_ask_qty
    if total == 0:
        return 0.0
        
    return (best_bid_qty - best_ask_qty) / total

def calculate_order_flow_imbalance(bids: List[Tuple[float, float]], 
                                 asks: List[Tuple[float, float]], 
                                 depth: int = 5) -> float:
    """
    Calculate order flow imbalance up to specified depth.
    
    Args:
        bids: List of (price, quantity) tuples for bids
        asks: List of (price, quantity) tuples for asks
        depth: Number of price levels to consider
        
    Returns:
        float: Order flow imbalance in range [-1, 1]
    """
    bid_vol = sum(qty for _, qty in bids[:depth])
    ask_vol = sum(qty for _, qty in asks[:depth])
    
    total = bid_vol + ask_vol
    if total == 0:
        return 0.0
        
    return (bid_vol - ask_vol) / total

def calculate_depth_slope(levels: List[Tuple[float, float]], 
                        side: str,
                        depth: int = 5) -> float:
    """
    Calculate slope of the order book depth.
    
    Args:
        levels: List of (price, quantity) tuples
        side: 'bids' or 'asks'
        depth: Number of price levels to consider
        
    Returns:
        float: Slope of the depth curve
    """
    if len(levels) < 2:
        return 0.0
        
    prices = np.array([price for price, _ in levels[:depth]])
    quantities = np.array([qty for _, qty in levels[:depth]])
    cumulative_qty = np.cumsum(quantities)
    
    # For bids, prices decrease; for asks, prices increase
    if side == 'bids':
        prices = -prices  # Make prices increase for consistent slope calculation
        
    # Calculate slope using linear regression
    x = prices - prices[0]  # Normalize x values
    y = cumulative_qty
    
    if len(x) < 2:
        return 0.0
        
    slope = np.polyfit(x, y, 1)[0]
    return -slope if side == 'bids' else slope

def calculate_l2_features(symbol: str,
                        timestamp: int,
                        bids: List[Tuple[float, float]],
                        asks: List[Tuple[float, float]]) -> Dict:
    """
    Calculate all L2 features from order book data.
    
    Args:
        symbol: Trading symbol
        timestamp: Unix timestamp in microseconds
        bids: List of (price, quantity) tuples for bids
        asks: List of (price, quantity) tuples for asks
        
    Returns:
        dict: Dictionary containing all L2 features
    """
    features = {
        'symbol': symbol,
        'timestamp': timestamp,
        'queue_imbalance': calculate_queue_imbalance(bids, asks),
        'order_flow_imbalance': calculate_order_flow_imbalance(bids, asks),
        'depth_slope_bids': calculate_depth_slope(bids, 'bids'),
        'depth_slope_asks': calculate_depth_slope(asks, 'asks')
    }
    
    # Validate features using schema
    df = pd.DataFrame([features])
    validated_df = L2FeaturesSchema.validate(df)
    
    return validated_df.iloc[0].to_dict()

# Example usage:
# bids = [(100.0, 1.0), (99.0, 2.0), ...]
# asks = [(101.0, 1.5), (102.0, 2.5), ...]
# features = calculate_l2_features("BTC_USD", 1234567890, bids, asks) 