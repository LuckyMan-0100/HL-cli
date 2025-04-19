import numpy as np
import pandas as pd
from typing import List, Tuple
from datetime import datetime, timedelta
from decimal import Decimal

from data_ingestion.models import Kline, Trade
from config.settings import settings

def label_trades(
    klines: List[Kline],
    look_forward: int = 10,
    entry_bar_offset: int = 6,
    profit_target_bps: float = 50.0,  # 0.5%
    stop_loss_bps: float = 30.0,      # 0.3%
) -> List[bool]:
    """
    Label each kline as a good entry point based on future price movement.
    
    A "good entry" is defined as:
    - Price moves in the predicted direction by profit_target_bps within the next
      look_forward bars after entry_bar_offset bars
    - Without first hitting the stop_loss_bps level in the adverse direction
    
    Args:
        klines: List of chronologically ordered klines
        look_forward: Number of bars to look ahead for profit target
        entry_bar_offset: Minimum number of bars before entry (avoid lookahead bias)
        profit_target_bps: Profit target in basis points
        stop_loss_bps: Stop loss level in basis points
    
    Returns:
        List of boolean labels aligned with input klines
    """
    if not klines:
        return []

    n = len(klines)
    labels = []

    for i in range(n):
        # If we can't look forward enough bars, label as False
        if i + entry_bar_offset + look_forward >= n:
            labels.append(False)
            continue

        # Get the entry price (close of current bar)
        entry_price = float(klines[i].close)

        # Calculate profit target and stop loss levels
        long_target = entry_price * (1 + profit_target_bps / 10000)
        long_stop = entry_price * (1 - stop_loss_bps / 10000)
        short_target = entry_price * (1 - profit_target_bps / 10000)
        short_stop = entry_price * (1 + stop_loss_bps / 10000)

        # Look at price action in the forward window
        hit_long_target = False
        hit_long_stop = False
        hit_short_target = False
        hit_short_stop = False

        for j in range(i + entry_bar_offset, min(i + entry_bar_offset + look_forward, n)):
            high = float(klines[j].high)
            low = float(klines[j].low)

            # Check if targets or stops were hit
            if high >= long_target:
                hit_long_target = True
            if low <= long_stop:
                hit_long_stop = True
            if low <= short_target:
                hit_short_target = True
            if high >= short_stop:
                hit_short_stop = True

        # Label as good entry if either:
        # 1. Long target hit without hitting long stop first
        # 2. Short target hit without hitting short stop first
        good_entry = (
            (hit_long_target and not hit_long_stop) or
            (hit_short_target and not hit_short_stop)
        )

        labels.append(good_entry)

    return labels

def prepare_training_data(
    klines: List[Kline],
    features: pd.DataFrame,
    look_forward: int = 10,
    entry_bar_offset: int = 6,
    profit_target_bps: float = 50.0,
    stop_loss_bps: float = 30.0
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Prepare feature matrix X and target vector y for training.
    
    Args:
        klines: List of chronologically ordered klines
        features: DataFrame of features aligned with klines
        look_forward: Number of bars to look ahead for profit target
        entry_bar_offset: Minimum number of bars before entry
        profit_target_bps: Profit target in basis points
        stop_loss_bps: Stop loss level in basis points
    
    Returns:
        X: Feature matrix
        y: Target labels
    """
    # Generate labels
    labels = label_trades(
        klines,
        look_forward=look_forward,
        entry_bar_offset=entry_bar_offset,
        profit_target_bps=profit_target_bps,
        stop_loss_bps=stop_loss_bps
    )

    # Convert to pandas Series
    y = pd.Series(labels, index=features.index)

    # Remove rows where we don't have enough forward data
    mask = ~pd.isna(y)
    X = features[mask].copy()
    y = y[mask]

    return X, y

def analyze_label_distribution(y: pd.Series) -> pd.Series:
    """
    Analyze the distribution of labels in the training data.
    
    Args:
        y: Series of binary labels
        
    Returns:
        Series with label statistics
    """
    total = len(y)
    positive = y.sum()
    negative = total - positive
    
    stats = pd.Series({
        'total_samples': total,
        'positive_samples': positive,
        'negative_samples': negative,
        'positive_ratio': positive / total if total > 0 else 0,
        'negative_ratio': negative / total if total > 0 else 0
    })
    
    return stats 