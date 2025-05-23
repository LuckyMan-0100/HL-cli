"""Fill probability estimation based on queue position and spread."""

import numpy as np
import pandas as pd

def estimate_fill_probability(
    bid_price: pd.Series,
    ask_price: pd.Series,
    bid_qty: pd.Series,
    ask_qty: pd.Series,
    *,
    min_prob: float = 0.05,
    max_prob: float = 0.95,
) -> pd.Series:
    """Estimate fill probability based on queue position and spread.
    
    Simple but effective heuristic:
    - Higher probability when our side has less quantity (closer to front)
    - Lower probability when spread is wider (more adverse selection)
    """
    # Relative spread as proxy for adverse selection
    mid = (bid_price + ask_price) / 2
    rel_spread = (ask_price - bid_price) / mid
    spread_factor = np.exp(-2 * rel_spread)  # Decay with wider spreads
    
    # Queue position proxy (qty imbalance)
    qty_ratio = np.minimum(bid_qty, ask_qty) / np.maximum(bid_qty, ask_qty)
    
    # Combined fill probability
    prob = qty_ratio * spread_factor
    
    return prob.clip(min_prob, max_prob) 