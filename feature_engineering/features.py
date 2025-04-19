import numpy as np, pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD
from typing import Dict, Any, Tuple

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