import numpy as np, pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD
from typing import Dict, Any, Tuple, List, Optional
from dataclasses import dataclass

@dataclass
class OrderbookSnapshot:
    bids: List[Dict[str, float]]  # List of {price, quantity} dicts
    asks: List[Dict[str, float]]
    timestamp: int

@dataclass
class MicrostructureFeatures:
    queue_imbalance: float
    order_flow_imbalance: float
    depth_slope_bids: float
    depth_slope_asks: float
    timestamp: int

class FeatureCalculator:
    def __init__(self, lookback_window: int = 100):
        self.lookback_window = lookback_window
        self.last_orderbook: Optional[OrderbookSnapshot] = None
        
    def calculate_queue_imbalance(self, orderbook: OrderbookSnapshot, depth: int = 5) -> float:
        """
        Calculate queue imbalance as (bid_volume - ask_volume)/(bid_volume + ask_volume)
        for top N levels.
        """
        bid_vol = sum(bid['quantity'] for bid in orderbook.bids[:depth])
        ask_vol = sum(ask['quantity'] for ask in orderbook.asks[:depth])
        
        if bid_vol + ask_vol == 0:
            return 0.0
            
        return (bid_vol - ask_vol) / (bid_vol + ask_vol)
        
    def calculate_order_flow_imbalance(self, 
                                     current_book: OrderbookSnapshot,
                                     prev_book: Optional[OrderbookSnapshot],
                                     depth: int = 5) -> float:
        """
        Calculate order flow imbalance based on changes in order book levels.
        """
        if prev_book is None:
            return 0.0
            
        # Calculate volume changes at each level
        bid_changes = []
        ask_changes = []
        
        for i in range(min(depth, len(current_book.bids), len(prev_book.bids))):
            curr_bid = current_book.bids[i]
            prev_bid = prev_book.bids[i]
            if curr_bid['price'] == prev_bid['price']:
                bid_changes.append(curr_bid['quantity'] - prev_bid['quantity'])
                
        for i in range(min(depth, len(current_book.asks), len(prev_book.asks))):
            curr_ask = current_book.asks[i]
            prev_ask = prev_book.asks[i]
            if curr_ask['price'] == prev_ask['price']:
                ask_changes.append(curr_ask['quantity'] - prev_ask['quantity'])
                
        total_bid_change = sum(max(0, change) for change in bid_changes)
        total_ask_change = sum(max(0, change) for change in ask_changes)
        
        if total_bid_change + total_ask_change == 0:
            return 0.0
            
        return (total_bid_change - total_ask_change) / (total_bid_change + total_ask_change)
        
    def calculate_depth_slope(self, levels: List[Dict[str, float]], is_bids: bool = True) -> float:
        """
        Calculate the slope of the order book depth curve using linear regression.
        """
        if not levels:
            return 0.0
            
        prices = np.array([level['price'] for level in levels])
        quantities = np.array([level['quantity'] for level in levels])
        
        # Normalize prices relative to best bid/ask
        reference_price = prices[0]
        prices = (prices - reference_price) / reference_price
        
        # Cumulative quantities
        quantities = np.cumsum(quantities)
        
        # Fit line using numpy's polyfit
        if len(prices) > 1:
            slope, _ = np.polyfit(prices, quantities, 1)
            return slope if is_bids else -slope
        return 0.0
        
    def calculate_microstructure_features(self, orderbook: OrderbookSnapshot) -> MicrostructureFeatures:
        """
        Calculate all microstructure features from order book data.
        """
        queue_imb = self.calculate_queue_imbalance(orderbook)
        order_flow_imb = self.calculate_order_flow_imbalance(orderbook, self.last_orderbook)
        depth_slope_bids = self.calculate_depth_slope(orderbook.bids, is_bids=True)
        depth_slope_asks = self.calculate_depth_slope(orderbook.asks, is_bids=False)
        
        # Update last orderbook
        self.last_orderbook = orderbook
        
        return MicrostructureFeatures(
            queue_imbalance=queue_imb,
            order_flow_imbalance=order_flow_imb,
            depth_slope_bids=depth_slope_bids,
            depth_slope_asks=depth_slope_asks,
            timestamp=orderbook.timestamp
        )

def build_features(candles: pd.DataFrame, ob: Dict[str, Any]) -> np.ndarray:
    """Return fixed‑length vector from recent candles & order‑book snapshot."""
    if len(candles) < 30:
        raise ValueError("Need at least 30 candles")

    c = candles.copy()
    c["rsi"] = RSIIndicator(c["close"]).rsi()
    macd = MACD(c["close"])
    c["macd"] = macd.macd_diff()
    c["bb_pos"] = (c["close"] - c["close"].rolling(20).mean()) / (2*c["close"].rolling(20).std())
    recent = c.iloc[-1]

    bid = ob["bids"][0]["price"] if ob["bids"] else recent.close
    ask = ob["asks"][0]["price"] if ob["asks"] else recent.close
    mid = (bid + ask) / 2
    bid_qty = ob["bids"][0]["qty"] if ob["bids"] else 0
    ask_qty = ob["asks"][0]["qty"] if ob["asks"] else 0
    imbalance = bid_qty - ask_qty

    return np.array([
        recent.rsi, recent.macd, recent.bb_pos,
        imbalance, bid, ask, mid
    ], dtype=np.float32)

def label_good_entry(future_returns: pd.Series, threshold: float = 0.0005) -> int:
    """Binary label: 1=good if +/‑0.05% w/o 0.03% adverse."""
    fwd = future_returns.values
    max_up = fwd.max()
    max_dn = fwd.min()
    return int((max_up >= threshold) and (max_dn >= -threshold*0.6))

# Feature validation functions
def validate_rsi(value: float) -> bool:
    """Validate RSI is in [0, 100] range."""
    return 0 <= value <= 100

def validate_atr(value: float) -> bool:
    """Validate ATR is positive."""
    return value > 0

def validate_macd(macd: float, signal: float, hist: float) -> bool:
    """Validate MACD components are finite."""
    return all(np.isfinite([macd, signal, hist]))

def validate_bb(lower: float, middle: float, upper: float) -> bool:
    """Validate Bollinger Bands ordering."""
    return lower <= middle <= upper

def validate_microstructure(features: MicrostructureFeatures) -> bool:
    """Validate microstructure features."""
    return (
        -1 <= features.queue_imbalance <= 1 and
        -1 <= features.order_flow_imbalance <= 1 and
        np.isfinite(features.depth_slope_bids) and
        np.isfinite(features.depth_slope_asks)
    )

# Feature importance tracking
def track_feature_importance(model, feature_names: List[str], run_id: str) -> Dict[str, float]:
    """
    Get feature importance scores and track changes from previous run.
    
    Args:
        model: Trained XGBoost model
        feature_names: List of feature names
        run_id: MLflow run ID
        
    Returns:
        Dictionary of feature importances
    """
    import mlflow
    
    # Get current feature importance
    importance_dict = model.get_score(importance_type='gain')
    
    # Normalize to percentages
    total = sum(importance_dict.values())
    importance_dict = {k: v/total * 100 for k, v in importance_dict.items()}
    
    # Get previous run's importance if available
    try:
        prev_run = mlflow.search_runs(
            filter_string="tags.type = 'production'",
            order_by=["start_time DESC"],
            max_results=1
        ).iloc[0]
        
        prev_importance = prev_run.data.params.get('feature_importance', {})
        if prev_importance:
            prev_importance = eval(prev_importance)
            
            # Calculate changes
            changes = {}
            for feature in feature_names:
                curr_imp = importance_dict.get(feature, 0)
                prev_imp = prev_importance.get(feature, 0)
                changes[feature] = curr_imp - prev_imp
                
            # Log changes to MLflow
            mlflow.log_metrics({
                f"importance_change_{k}": v for k, v in changes.items()
            })
            
    except IndexError:
        # No previous run found
        pass
        
    # Log current importance to MLflow
    mlflow.log_params({
        'feature_importance': importance_dict
    })
    
    return importance_dict