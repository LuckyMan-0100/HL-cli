#!/usr/bin/env python3
"""
L2 only model training pipeline - Enhanced Version
Objective

Train LightGBM models (direction and edge) leveraging L2 order book and
order flow features, aligned with the roadmap:
- Rich L2 imbalance, liquidity shear, multi-horizon OFI
- Latency-aware microprice moves
- Sample weighting by fill probability
- (Optional) Metalabeling (handled here via separate edge model)
- Feature penalties/weights
- Purged Walk-Forward CV
- Kelly-like position sizing helper
- Lightweight runtime footprint target (< 80 µs path budget)

Writes features to /tmp/features.parquet and saves trained models locally.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import joblib
import lightgbm as lgb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from lightgbm import Booster
# from sklearn.model_selection import TimeSeriesSplit # Replaced by PurgedKFold
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score, mean_squared_error

# Assume these local modules exist and are performant
from settings import settings  # type: ignore
from utils.purged_cv import PurgedKFold  # walk‑forward, leakage‑free splitter
from orderflow.tail_reader import DepthTailReader # streaming L2 reader
from orderflow.fill_prob import estimate_fill_probability # heuristic from roadmap

logger = logging.getLogger("l2_trainer")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s"
)

# Constants
FEATURE_FILE = Path("/tmp/features.parquet")
MODEL_DIR_PATH = Path("./trained_models")
MODEL_DIR_PATH.mkdir(exist_ok=True) # Ensure model directory exists

# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _calculate_tick_size(prices: pd.Series, min_count: int = 100) -> float:
    """Estimate tick size from a series of prices."""
    unique_prices = prices.dropna().unique()
    if len(unique_prices) < 2:
        return 0.0001 # Default small value if not enough unique prices
    
    price_diffs = np.diff(np.sort(unique_prices))
    non_zero_diffs = price_diffs[price_diffs > 1e-9] # Avoid floating point noise
    
    if len(non_zero_diffs) < min_count:
         # Fallback if few non-zero diffs: use min non-zero diff
         return non_zero_diffs.min() if len(non_zero_diffs) > 0 else 0.0001

    # Use median of smallest diffs as a robust estimator
    # Could also use mode or other heuristics
    tick_size = np.median(non_zero_diffs) 
    
    # Basic sanity check - avoid excessively large tick sizes
    if tick_size > 0.01 * prices.mean(): 
        return non_zero_diffs.min() if len(non_zero_diffs) > 0 else 0.0001
        
    return tick_size if tick_size > 1e-9 else 0.0001


def build_l2_features(depth: pd.DataFrame, *, latency_ticks: int = 2) -> pd.DataFrame:
    """Given a tidy depth DataFrame, create micro‑structure features only.

    Parameters
    ----------
    depth : pd.DataFrame
        Expected columns: [`ts`, `side`, `price`, `qty`, `level`]
        Must be sorted by `ts`.
    latency_ticks : int
        Exchange to strategy roundtrip expressed in snapshot steps.
        Used for calculating price/microprice derivatives.
    """
    logger.info("Pivoting L2 data...")
    # Pivot L2 snapshot into wide form (level columns)
    book = depth.pivot_table(
        index="ts", columns=["side", "level"], values=["price", "qty"]
    )
    book.sort_index(inplace=True)
    # L2 is sparse; ffill is essential for continuous features but introduces staleness risk
    book = book.fillna(method="ffill")
    # Drop initial rows that couldn't be filled
    book = book.dropna(axis=0, how='any') 
    
    if book.empty:
        logger.warning("Book is empty after pivoting and ffill/dropna. Cannot build features.")
        return pd.DataFrame()

    df = pd.DataFrame(index=book.index)
    logger.info(f"Building features for {len(df)} timestamps...")

    # Cache L1 prices and quantities
    try:
        bid_p1 = book["price", "bid", 1]
        ask_p1 = book["price", "ask", 1]
        bid_q1 = book["qty", "bid", 1]
        ask_q1 = book["qty", "ask", 1]
        mid_p = (bid_p1 + ask_p1) / 2.0
    except KeyError as e:
        logger.error(f"Missing required L1 columns after pivot: {e}")
        logger.error(f"Available columns: {book.columns.tolist()}")
        return pd.DataFrame() # Return empty if essential L1 data is missing
    except IndexError as e:
        logger.error(f"Indexing error accessing L1 columns, likely empty book passed: {e}")
        return pd.DataFrame()

    # Robust Tick Size Estimation
    tick_size = _calculate_tick_size(pd.concat([bid_p1, ask_p1]))
    logger.info(f"Estimated tick size: {tick_size}")

    # ------------------------------------------------------------------
    # 1. Enhanced depth imbalance L1–L5 with exponential decay
    #    Using standard (B-A)/(B+A) per level before weighting
    # ------------------------------------------------------------------
    decay_weights = np.exp(-np.arange(5) * 0.5)  # Exponential decay weights
    weighted_imb = pd.Series(0.0, index=df.index)
    total_volume_l1_l5 = pd.Series(0.0, index=df.index)

    for lvl in range(1, 6):
        try:
            bid_q = book["qty", "bid", lvl]
            ask_q = book["qty", "ask", lvl]
        except KeyError:
            # Handle cases where level 5 might not always exist
            logger.warning(f"Level {lvl} quantity data not found, skipping for imbalance.")
            continue 
            
        total_q = bid_q + ask_q
        total_volume_l1_l5 += total_q
        level_imb = (bid_q - ask_q) / total_q.replace(0, np.nan) # Avoid division by zero
        df[f"imb_l{lvl}"] = level_imb
        # Add weighted contribution, filling NaNs from division by zero or missing levels
        weighted_imb += level_imb.fillna(0) * decay_weights[lvl - 1]

    # Normalize weighted imbalance by sum of weights used (handles missing levels)
    # sum_of_weights_used = sum(decay_weights[lvl-1] for lvl in range(1, 6) if f"imb_l{lvl}" in df.columns)
    # df["weighted_imb"] = weighted_imb / sum_of_weights_used if sum_of_weights_used > 0 else 0
    df["weighted_imb"] = weighted_imb # Keep raw weighted sum for now, scale later if needed

    # ------------------------------------------------------------------
    # 2. Price impact, liquidity measures, and Liquidity Shear
    # ------------------------------------------------------------------
    df["spread_bps"] = (ask_p1 - bid_p1) / mid_p * 10000
    
    for lvl in range(1, 6):
        try:
            bid_p = book["price", "bid", lvl]
            ask_p = book["price", "ask", lvl]
            bid_q = book["qty", "bid", lvl]
            ask_q = book["qty", "ask", lvl]
        except KeyError:
            logger.warning(f"Level {lvl} price/qty data not found, skipping for impact/concentration.")
            continue

        # Price impact to trade through level (relative to BBO)
        df[f"bid_impact_{lvl}"] = (bid_p1 - bid_p) / bid_p1
        df[f"ask_impact_{lvl}"] = (ask_p - ask_p1) / ask_p1

        # Liquidity concentration - cumulative sum calculation
        # Using try-except blocks for robustness if levels are missing
        bid_qty_levels = [book.get(("qty", "bid", i), pd.Series(0.0, index=df.index)) for i in range(1, lvl + 1)]
        ask_qty_levels = [book.get(("qty", "ask", i), pd.Series(0.0, index=df.index)) for i in range(1, lvl + 1)]
        
        bid_qty_sum_upto_lvl = pd.concat(bid_qty_levels, axis=1).sum(axis=1)
        ask_qty_sum_upto_lvl = pd.concat(ask_qty_levels, axis=1).sum(axis=1)

        # Avoid division by zero if sum is zero
        df[f"bid_concentration_{lvl}"] = (bid_q / bid_qty_sum_upto_lvl.replace(0, np.nan)).fillna(0)
        df[f"ask_concentration_{lvl}"] = (ask_q / ask_qty_sum_upto_lvl.replace(0, np.nan)).fillna(0)
    
    # Liquidity Shear (Roadmap Point) - Change in L1 Qty vs Change in Mid Price
    mid_p_diff = mid_p.diff().replace(0, np.nan) # Avoid division by zero
    bid_q1_diff = bid_q1.diff()
    ask_q1_diff = ask_q1.diff()
    df['qty_shear'] = (bid_q1_diff - ask_q1_diff) / mid_p_diff
    # Simple flow ratio (alternative shear measure)
    df['bbo_flow_ratio'] = (bid_q1_diff - ask_q1_diff) / (bid_q1_diff.abs() + ask_q1_diff.abs()).replace(0, np.nan)

    # ------------------------------------------------------------------
    # 3. Multi-horizon order‑flow imbalance (OFI) using L1 quantities
    # ------------------------------------------------------------------
    # Volume normalization factor (rolling mean of L1 volume)
    vol_norm = (bid_q1 + ask_q1).rolling(100, min_periods=20).mean().replace(0, np.nan)

    # Short-term OFI
    for lag in (1, 3, 5, 10): # Adjusted lags slightly
        # Calculate changes based on previous price ticks
        prev_bid_p = bid_p1.shift(lag)
        prev_ask_p = ask_p1.shift(lag)
        
        delta_bid = bid_q1.copy()
        delta_ask = ask_q1.copy()
        
        # Zero change if price is unchanged
        delta_bid[bid_p1 == prev_bid_p] = 0 
        # Use previous quantity if price decreased (aggressing order)
        delta_bid[bid_p1 < prev_bid_p] = -bid_q1.shift(lag) 
        # No change if price increased (passive order) - delta_bid already holds current qty implicitly
        
        delta_ask[ask_p1 == prev_ask_p] = 0
        delta_ask[ask_p1 > prev_ask_p] = -ask_q1.shift(lag)

        # Original simple diff method (kept for comparison if needed)
        # delta_bid_simple = bid_q1.diff(lag)
        # delta_ask_simple = ask_q1.diff(lag)

        raw_ofi = (delta_bid - delta_ask) / vol_norm # Normalize by rolling volume
        df[f"ofi_{lag}"] = raw_ofi.clip(-5, 5) # Clip extreme values (adjust range as needed)
        df[f"ofi_{lag}_ma"] = df[f"ofi_{lag}"].ewm(span=max(5, lag*2)).mean() # Smoothed OFI
        df[f"ofi_{lag}_std"] = df[f"ofi_{lag}"].rolling(max(10, lag*3)).std() # OFI volatility

    # Longer-term OFI (resampled sums of shortest OFI) - Requires consistent snapshot frequency
    base_ofi_col = "ofi_1" 
    if base_ofi_col in df.columns:
        for seconds in (1, 3, 5, 10):
            # Assuming ~20 snapshots per second (50ms) - ADJUST IF NEEDED
            snapshots_per_second = 20 
            samples = int(seconds * snapshots_per_second)
            if samples > 1:
                df[f"ofi_{seconds}s_sum"] = df[base_ofi_col].rolling(samples, min_periods=samples // 2).sum()
                df[f"ofi_{seconds}s_std"] = df[base_ofi_col].rolling(samples, min_periods=samples // 2).std()
    else:
        logger.warning(f"{base_ofi_col} not found, cannot calculate longer-term OFI sums.")

    # ------------------------------------------------------------------
    # 4. Enhanced micro‑price features with latency awareness
    # ------------------------------------------------------------------
    # Volume-weighted micro-price (Standard)
    total_q1 = bid_q1 + ask_q1
    vwap_weights_bid = (bid_q1 / total_q1).replace([np.inf, -np.inf, np.nan], 0.5)
    vwap_weights_ask = (ask_q1 / total_q1).replace([np.inf, -np.inf, np.nan], 0.5)
    # Ensure weights sum to 1 (handle zero total_q1 case)
    vwap_weights_bid[(vwap_weights_bid + vwap_weights_ask) == 0] = 0.5
    vwap_weights_ask[(vwap_weights_bid + vwap_weights_ask) == 0] = 0.5


    mp = bid_p1 * vwap_weights_bid + ask_p1 * vwap_weights_ask
    df["microprice"] = mp
    # Latency-aware slope and acceleration (Roadmap Point)
    df["mp_slope"] = mp.diff(latency_ticks)
    df["mp_accel"] = df["mp_slope"].diff()

    # Optional: Flow-weighted micro-price (More experimental)
    # flow_indicator = df.get("ofi_1_ma", pd.Series(0.0, index=df.index)).clip(-1, 1) # Use smoothed OFI
    # flow_weights_bid = (1 + flow_indicator) / 2.0
    # flow_weights_ask = (1 - flow_indicator) / 2.0
    # flow_mp = bid_p1 * flow_weights_bid + ask_p1 * flow_weights_ask
    # df["flow_mp_slope"] = flow_mp.diff(latency_ticks)

    # ------------------------------------------------------------------
    # 5. Spread, Tick Metrics, and Volume Features
    # ------------------------------------------------------------------
    spread = ask_p1 - bid_p1
    # Normalize spread by price level (relative spread)
    df["rel_spread"] = (spread / mid_p).replace([np.inf, -np.inf], np.nan)
    df["rel_spread_ma"] = df["rel_spread"].rolling(50, min_periods=10).mean()
    df["rel_spread_std"] = df["rel_spread"].rolling(50, min_periods=10).std()

    # Tick size relative metrics (if tick_size is meaningful)
    if tick_size > 1e-9:
        df["spread_ticks"] = spread / tick_size
        df["mp_slope_ticks"] = df["mp_slope"] / tick_size
    
    # Volume features
    df['total_volume_l1'] = bid_q1 + ask_q1
    df['total_volume_l5'] = total_volume_l1_l5 # Calculated during imbalance
    df['total_volume_l1_ma'] = df['total_volume_l1'].rolling(100, min_periods=20).mean()
    df['volume_volatility'] = df['total_volume_l1'].rolling(100, min_periods=20).std()


    # ------------------------------------------------------------------
    # 6. Fill‑probability context and Queue Position
    # ------------------------------------------------------------------
    # Fill prob estimated externally, passed later for weighting/features
    
    # Queue position metrics relative to rolling depth averages
    for lvl in range(1, 3): # Focus on L1/L2 queue depth
        try:
            bid_q = book["qty", "bid", lvl]
            ask_q = book["qty", "ask", lvl]
        except KeyError:
            logger.warning(f"Level {lvl} quantity data not found, skipping for queue position.")
            continue
            
        bid_depth_ma = bid_q.rolling(100, min_periods=20).mean().replace(0, np.nan)
        ask_depth_ma = ask_q.rolling(100, min_periods=20).mean().replace(0, np.nan)

        df[f"bid_depth_ratio_{lvl}"] = (bid_q / bid_depth_ma).fillna(1.0) # Ratio to average
        df[f"ask_depth_ratio_{lvl}"] = (ask_q / ask_depth_ma).fillna(1.0) # Ratio to average

        # Queue position: Vol at level / (Vol at level + Vol at level+1)
        # Represents fraction of total liquidity between level N and N+1 that sits at level N
        try:
            bid_q_next = book["qty", "bid", lvl + 1]
            ask_q_next = book["qty", "ask", lvl + 1]
            
            bid_total_local = bid_q + bid_q_next
            ask_total_local = ask_q + ask_q_next
            
            df[f"bid_queue_frac_{lvl}"] = (bid_q / bid_total_local.replace(0, np.nan)).fillna(0.5)
            df[f"ask_queue_frac_{lvl}"] = (ask_q / ask_total_local.replace(0, np.nan)).fillna(0.5)
        except KeyError:
            logger.warning(f"Level {lvl+1} qty data not found, cannot calculate queue fraction for level {lvl}.")
            df[f"bid_queue_frac_{lvl}"] = 0.5 # Default value
            df[f"ask_queue_frac_{lvl}"] = 0.5 # Default value


    # ------------------------------------------------------------------
    # Final Cleanup - Replace inf/-inf, but handle NaNs in preprocessing
    logger.info("Cleaning final features...")
    df = df.replace([np.inf, -np.inf], np.nan) # Replace inf with NaN for imputer
    
    logger.info(f"Built {df.shape[1]} raw features.")
    return df


# ---------------------------------------------------------------------------
# Preprocessing, Labeling, and Dataset Preparation
# ---------------------------------------------------------------------------

def target_forward_return(mid: pd.Series, *, horizon: int = 10) -> pd.Series:
    """Signed forward return relative to current mid-price over horizon snapshots."""
    # Shift mid-price *back* by `horizon` steps to get future price aligned with current time
    future_mid = mid.shift(-horizon)
    ret = (future_mid - mid) / mid
    return ret.replace([np.inf, -np.inf], np.nan) # Handle potential division by zero

def calculate_vectorized_edge(
    bid_p1: pd.Series,
    ask_p1: pd.Series,
    bid_q1: pd.Series,
    ask_q1: pd.Series,
    volatility: pd.Series # Should be pre-calculated (e.g., rolling std of returns)
) -> pd.Series:
    """
    Vectorized calculation of trading edge based on L1 state and volatility.
    Uses the aggressive logic from the original 'calculate_edge'.
    """
    mid = (bid_p1 + ask_p1) / 2.0
    spread = ask_p1 - bid_p1

    # Reduced cost estimates (as per original logic)
    impact_cost = 0.1 * spread
    fee_cost = spread * 0.1 # Simplified fee component
    total_cost = impact_cost + fee_cost

    # Calculate returns aggressively based on L1 imbalance
    # Note: This assumes imbalance directly predicts immediate favorable move * 1.5
    expected_return = pd.Series(0.0, index=mid.index)
    
    # Calculate volume imbalance
    total_vol = bid_q1 + ask_q1
    bid_ratio = bid_q1 / total_vol
    ask_ratio = ask_q1 / total_vol
    
    # Identify significant imbalances (>60% on one side)
    long_signal = bid_ratio > 0.6
    short_signal = ask_ratio > 0.6
    
    # Calculate expected return based on imbalance strength
    # Scale by how extreme the imbalance is
    expected_return.loc[long_signal] = (ask_p1[long_signal] - mid[long_signal]) * (bid_ratio[long_signal] * 2)
    expected_return.loc[short_signal] = (mid[short_signal] - bid_p1[short_signal]) * (ask_ratio[short_signal] * 2)

    # Calculate edge, normalized by volatility
    # Add small constant to volatility to avoid division by zero
    edge = (expected_return - total_cost) / (volatility + 1e-6)
    
    # Use less aggressive clipping
    return edge.clip(-5, 5).fillna(0.0)


def preprocess_features(df: pd.DataFrame) -> pd.DataFrame:
    """Preprocess features: Impute NaNs, Scale, Remove high correlation, Winsorize."""
    logger.info(f"Preprocessing {df.shape[1]} features...")
    processed = df.copy()

    # 1. Impute missing values (before scaling and correlation check)
    # Use median imputation as it's robust to outliers
    imputer = SimpleImputer(strategy='median')
    processed_imputed = imputer.fit_transform(processed)
    processed = pd.DataFrame(processed_imputed, columns=processed.columns, index=processed.index)
    nan_counts = processed.isna().sum().sum()
    if nan_counts > 0:
         logger.warning(f"Found {nan_counts} NaNs after imputation. Check input data or imputer strategy.")
         processed = processed.fillna(0) # Fallback fill

    # 2. Remove highly correlated features (threshold 0.95)
    corr_matrix = processed.corr().abs()
    upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
    to_drop = [column for column in upper.columns if any(upper[column] > 0.95)]
    processed = processed.drop(columns=to_drop)
    logger.info(f"Dropped {len(to_drop)} highly correlated features: {to_drop}")

    if processed.empty:
        logger.error("All features dropped due to high correlation or data issues.")
        return processed # Return empty dataframe

    # 3. Standardize remaining features
    scaler = StandardScaler()
    scaled_features = scaler.fit_transform(processed)
    processed = pd.DataFrame(scaled_features, columns=processed.columns, index=processed.index)

    # 4. Handle outliers using winsorization (clip at 0.1% and 99.9%)
    for col in processed.columns:
        lower = processed[col].quantile(0.001)
        upper = processed[col].quantile(0.999)
        processed[col] = processed[col].clip(lower, upper)
    
    logger.info(f"Preprocessing complete. Final features: {processed.shape[1]}")
    return processed


def prepare_dataset(
    reader: DepthTailReader,
    start: datetime,
    end: datetime,
    horizon: int = 10, # Prediction horizon in snapshots
    latency_ticks: int = 2, # Latency assumption for derivatives
) -> Tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """Load depth, build features & labels, preprocess, align, and return ML-ready data."""
    logger.info(f"Preparing dataset from {start.isoformat()} to {end.isoformat()}")

    depth = reader.read_interval(start, end)  # Read tidy df
    if depth.empty:
        logger.error("No depth data read from reader for the specified interval.")
        return pd.DataFrame(), pd.Series(), pd.Series(), pd.Series()
        
    logger.info(f"Read {len(depth)} depth rows. Building features...")
    # Ensure data is sorted by timestamp before feature engineering
    depth = depth.sort_values(by='ts')

    # --- Calculate Labels and Edge Inputs First ---
    # Extract L1 book data needed for labels and edge
    l1_book = depth.loc[depth['level'] == 1].pivot(index='ts', columns='side', values=['price', 'qty'])
    l1_book.columns = ['_'.join(col).strip() for col in l1_book.columns.values] # Flatten MultiIndex
    l1_book = l1_book.sort_index()
    l1_book = l1_book.fillna(method='ffill').dropna() # Fill initial NaNs

    # Check for required columns after pivot
    required_cols = ['price_bid', 'price_ask', 'qty_bid', 'qty_ask']
    if not all(col in l1_book.columns for col in required_cols):
        logger.error(f"Missing one or more required L1 columns after pivot: {required_cols}. Available: {l1_book.columns}")
        return pd.DataFrame(), pd.Series(), pd.Series(), pd.Series()

    mid = (l1_book['price_bid'] + l1_book['price_ask']) / 2.0

    # Primary label: direction classification (binary)
    fwd_ret = target_forward_return(mid, horizon=horizon)
    y = (fwd_ret > 0).astype(int) # Binary label: 1 if future return > 0, else 0

    # Calculate volatility for edge normalization (use rolling std of returns)
    volatility = fwd_ret.rolling(100, min_periods=20).std().fillna(method='ffill').fillna(1e-6) # Fill NaNs, avoid zero

    # Calculate edge using the vectorized function
    edge = calculate_vectorized_edge(
        bid_p1=l1_book['price_bid'],
        ask_p1=l1_book['price_ask'],
        bid_q1=l1_book['qty_bid'],
        ask_q1=l1_book['qty_ask'],
        volatility=volatility
    )

    # --- Build Features ---
    X_raw = build_l2_features(depth, latency_ticks=latency_ticks)
    if X_raw.empty:
         logger.error("Feature engineering returned an empty DataFrame.")
         return pd.DataFrame(), pd.Series(), pd.Series(), pd.Series()

    # --- Estimate Fill Probability (Roadmap Point 3) ---
    # Needs L1 data aligned with feature index
    common_index = X_raw.index.intersection(l1_book.index)
    l1_book_aligned = l1_book.loc[common_index]
    
    fill_prob = estimate_fill_probability(
        bid_price=l1_book_aligned['price_bid'],
        ask_price=l1_book_aligned['price_ask'],
        bid_qty=l1_book_aligned['qty_bid'],
        ask_qty=l1_book_aligned['qty_ask'],
    )
    # Add fill_prob as a feature OR use only for weighting later
    # X_raw['fill_prob_feat'] = fill_prob

    # --- Preprocess Features ---
    X_processed = preprocess_features(X_raw)
    
    # --- Align all dataframes/series to the final processed features index ---
    final_index = X_processed.index.intersection(y.index).intersection(edge.index).intersection(fill_prob.index)
    
    X = X_processed.loc[final_index]
    y = y.loc[final_index]
    edge = edge.loc[final_index]
    fill_prob = fill_prob.loc[final_index] # Use this for sample weighting

    # Log dataset statistics
    logger.info(f"Built {X.shape[1]} final features: {list(X.columns)}")
    logger.info("\nLabel Distribution:")
    logger.info(y.value_counts(normalize=True))

    logger.info("\nEdge Distribution (quantiles):")
    logger.info(edge.quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]))

    logger.info("\nFill Probability Distribution (quantiles):")
    logger.info(fill_prob.quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]))

    # Save features for inspection/notebooks
    try:
        logger.info(f"Saving final features ({len(X)} samples) to {FEATURE_FILE}...")
        X.assign(label=y, edge=edge, fill_prob=fill_prob).to_parquet(FEATURE_FILE)
        logger.info("Features saved successfully.")
    except Exception as e:
        logger.error(f"Failed to save features to {FEATURE_FILE}: {e}")


    # Final Data Quality Checks
    logger.info("\nFinal Data Quality Checks:")
    logger.info(f"Total samples: {len(X)}")
    logger.info(f"Feature NaNs: {X.isna().any().sum()} features with NaNs")
    logger.info(f"Sample NaNs: {X.isna().any(axis=1).sum()} samples with NaNs")
    if X.isna().any().any():
        logger.warning("NaNs detected in final feature set X! Check preprocessing steps.")
        # Optional: Force fill remaining NaNs, but investigate cause
        # X = X.fillna(0) 
        
    valid_rows = ~(y.isna() | edge.isna() | fill_prob.isna())
    if not valid_rows.all():
        logger.warning(f"{(~valid_rows).sum()} rows dropped due to NaN labels/edge/fill_prob.")
        X = X.loc[valid_rows]
        y = y.loc[valid_rows]
        edge = edge.loc[valid_rows]
        fill_prob = fill_prob.loc[valid_rows]

    initial_len = len(X_raw)
    final_len = len(X)
    logger.info(
        f"\nFinal dataset: {final_len} samples ({100 * final_len / initial_len:.1f}% of raw features)"
    )
    
    if final_len == 0:
        logger.error("Dataset preparation resulted in zero valid samples.")

    return X, y, edge, fill_prob


# ---------------------------------------------------------------------------
# Model training – LightGBM using PurgedKFold CV
# ---------------------------------------------------------------------------

def validate_feature_importance(
    feature_importance_df: pd.DataFrame, # Expects df with 'feature' and 'importance' cols
    model_name: str = "Model",
    predictions: Optional[np.ndarray] = None,
    y_true: Optional[np.ndarray] = None,
    threshold: float = 0.01 # Importance percentage threshold
) -> bool:
    """Validate feature importance and optionally prediction stats."""
    
    if feature_importance_df.empty or 'importance' not in feature_importance_df.columns:
        logger.error(f"Cannot validate importance for {model_name}: Invalid importance dataframe.")
        return False

    total_importance = feature_importance_df['importance'].sum()
    
    # Normalize to percentages
    if total_importance > 0:
        feature_importance_df['importance_pct'] = (feature_importance_df['importance'] / total_importance) * 100
    else:
         feature_importance_df['importance_pct'] = 0.0

    # Sort features by importance (descending)
    sorted_importance = feature_importance_df.sort_values(by='importance_pct', ascending=False)

    is_valid = True
    warnings = []

    # 1. Check for model collapse (zero total importance)
    if total_importance == 0:
        logger.error(f"CRITICAL: {model_name} - Total feature importance is zero. Model may have failed to train.")
        is_valid = False

    # 2. Check for high feature concentration
    if is_valid: # Only check if not collapsed
        top_5_features = sorted_importance.head(5)
        top_5_concentration = top_5_features['importance_pct'].sum()
        if top_5_concentration > 95:
            warn_msg = (f"WARNING: {model_name} - High feature concentration: "
                        f"{top_5_concentration:.1f}% importance in top 5 features. Risk of overfitting.")
            warnings.append(warn_msg)
            logger.warning(warn_msg)
            if top_5_concentration > 99.5:
                logger.error(f"CRITICAL: {model_name} - Extreme concentration ({top_5_concentration:.1f}%). Likely overfit.")
                is_valid = False # Consider this critical

        # 3. Check for unused features (below threshold)
        unused_count = (sorted_importance['importance_pct'] < threshold).sum()
        total_features = len(sorted_importance)
        unused_percentage = (unused_count / total_features) * 100 if total_features > 0 else 0

        if unused_percentage > 75: # More tolerant threshold
             warn_msg = (f"WARNING: {model_name} - High percentage of unused features: "
                         f"{unused_percentage:.1f}% have < {threshold:.2f}% importance.")
             warnings.append(warn_msg)
             logger.warning(warn_msg)
             if unused_percentage > 90:
                 logger.error(f"CRITICAL: {model_name} - {unused_percentage:.1f}% features unused. Check feature set / regularization.")
                 # is_valid = False # May not be critical, but worth investigating

    # 4. Prediction statistics monitoring (if provided)
    if predictions is not None and y_true is not None and len(predictions) > 0 and len(y_true) == len(predictions):
        pred_mean, pred_std = np.mean(predictions), np.std(predictions)
        true_mean, true_std = np.mean(y_true), np.std(y_true)
        
        if pred_std < 1e-5: # Check for near-zero prediction variance
            logger.error(f"CRITICAL: {model_name} - Near-zero prediction variance ({pred_std:.6f}). Model might be predicting constant value.")
            is_valid = False
        else: # Only compare ratios if std is not zero
            if abs(pred_mean - true_mean) > 0.5 * true_std: # Check if means differ by > 0.5 std dev
                 warn_msg = (f"WARNING: {model_name} - Prediction mean ({pred_mean:.4f}) differs significantly "
                             f"from true mean ({true_mean:.4f}).")
                 warnings.append(warn_msg)
                 logger.warning(warn_msg)
            
            if true_std > 1e-6 and abs(pred_std - true_std) / true_std > 0.5: # Check if std dev differs by > 50%
                 warn_msg = (f"WARNING: {model_name} - Prediction std dev ({pred_std:.4f}) differs significantly "
                             f"from true std dev ({true_std:.4f}).")
                 warnings.append(warn_msg)
                 logger.warning(warn_msg)

    # 5. Log top 10 features
    logger.info(f"\nTop 10 Features for {model_name}:")
    for _, row in sorted_importance.head(10).iterrows():
        logger.info(f"- {row['feature']}: {row['importance_pct']:.2f}%")

    if not is_valid:
        logger.error(f"{model_name} failed validation checks.")
    elif warnings:
         logger.warning(f"{model_name} passed validation with warnings.")
    else:
        logger.info(f"{model_name} passed validation checks.")

    return is_valid

def plot_feature_importance(importance_df: pd.DataFrame, model_name: str, top_n: int = 20):
    """Plots the top N feature importances."""
    if importance_df.empty:
        logger.warning(f"Cannot plot importance for {model_name}: Importance dataframe is empty.")
        return
        
    try:
        fig, ax = plt.subplots(figsize=(10, max(6, top_n // 2)))
        sorted_importance = importance_df.sort_values(by='importance', ascending=False).head(top_n)
        sns.barplot(x='importance', y='feature', data=sorted_importance, ax=ax)
        ax.set_title(f'{model_name} - Top {top_n} Feature Importances')
        ax.set_xlabel('Importance Score (Gain or Split)')
        ax.set_ylabel('Feature')
        plt.tight_layout()
        plot_path = MODEL_DIR_PATH / f"{model_name.lower().replace(' ', '_')}_feature_importance.png"
        plt.savefig(plot_path)
        logger.info(f"Saved feature importance plot to {plot_path}")
        plt.close(fig)
    except Exception as e:
        logger.error(f"Failed to plot feature importance for {model_name}: {e}")

def get_feature_weights(feature_names: List[str]) -> List[float]:
    """Assign weights/penalties based on feature name patterns (Roadmap Point 5)."""
    weights = []
    for f in feature_names:
        if 'ofi_' in f: weight = 1.5       # Boost Order Flow Imbalance
        elif 'imb_' in f: weight = 1.3     # Boost Imbalance features
        elif 'shear' in f: weight = 1.2    # Boost Liquidity Shear
        elif 'spread' in f: weight = 1.1   # Slightly boost spread features
        elif 'mp_slope' in f: weight = 1.1 # Slightly boost microprice slope
        # elif 'slow_indicator' in f: weight = 0.8 # Example penalty
        else: weight = 1.0                  # Default weight
        weights.append(weight)
    return weights


def train_model(
    X: pd.DataFrame,
    y: pd.Series,       # Direction target (binary 0/1)
    edge: pd.Series,    # Edge target (regression)
    fill_prob: pd.Series, # Sample weights (Roadmap Point 3)
    *,
    n_splits: int = 5,
) -> Tuple[Optional[lgb.Booster], Optional[lgb.Booster]]:
    """Train direction and edge prediction models using PurgedKFold CV."""
    
    if X.empty or y.empty or edge.empty or fill_prob.empty:
        logger.error("Cannot train models with empty dataframes.")
        return None, None

    feature_names = list(X.columns)
    feature_weights = get_feature_weights(feature_names) # Roadmap Point 5
    logger.info(f"Generated {len(feature_weights)} feature weights.")

    # --- Base LightGBM Parameters ---
    # Using params optimized for speed and reduced overfitting
    base_params = {
        'boosting_type': 'gbdt',
        'learning_rate': 0.02, # Slightly faster LR
        'num_leaves': 31,      # Standard value (<= 2^max_depth)
        'max_depth': 5,        # Limit depth to prevent overfitting
        'feature_fraction': 0.7, # Subsample features (regularization)
        'bagging_fraction': 0.7, # Subsample data (regularization)
        'bagging_freq': 5,
        'min_data_in_leaf': 100, # Regularization - higher value
        'lambda_l1': 0.1,       # L1 regularization
        'lambda_l2': 0.1,       # L2 regularization
        'verbose': -1,
        'n_jobs': -1,           # Use all available cores
        'seed': 42,
    }

    dir_params = {**base_params, 'objective': 'binary', 'metric': 'auc', 'feature_weight': feature_weights}
    edge_params = {**base_params, 'objective': 'regression_l1', 'metric': 'mae', 'feature_weight': feature_weights} # Use MAE/L1

    # Initialize cross-validation (Roadmap Point 6)
    # PurgedKFold expects number of samples as purge window
    purge_samples = 200  # Purge 200 samples between train/test splits

    try:
        cv = PurgedKFold(
            n_splits=n_splits,
            purge_window=purge_samples
        )
    except Exception as e:
        logger.error(f"Failed to initialize PurgedKFold: {e}")
        return None, None

    oof_dir_preds = pd.Series(index=X.index, dtype=float)
    oof_edge_preds = pd.Series(index=X.index, dtype=float)
    
    best_dir_score = -np.inf # Maximize AUC
    best_edge_score = np.inf # Minimize MAE
    best_dir_model: Optional[lgb.Booster] = None
    best_edge_model: Optional[lgb.Booster] = None
    
    dir_models = []
    edge_models = []

    logger.info(f"Starting PurgedKFold CV with {n_splits} splits and {purge_samples} sample purge window...")
    try:
        for fold, (train_idx, val_idx) in enumerate(cv.split(X)):
            X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
            y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]
            edge_train, edge_val = edge.iloc[train_idx], edge.iloc[val_idx]
            fp_train, fp_val = fill_prob.iloc[train_idx], fill_prob.iloc[val_idx]

            logger.info(f"Fold {fold + 1}/{n_splits}: "
                        f"Train={len(X_train)}, Val={len(X_val)}")

            # --- Train Direction Model ---
            dtrain = lgb.Dataset(X_train, label=y_train, weight=fp_train, feature_name=feature_names)
            dval = lgb.Dataset(X_val, label=y_val, weight=fp_val, reference=dtrain)
            
            dir_model = lgb.train(
                dir_params,
                dtrain,
                valid_sets=[dtrain, dval],
                num_boost_round=500, # Reduced rounds
                callbacks=[
                    lgb.early_stopping(stopping_rounds=30, verbose=False), # More aggressive early stopping
                    lgb.log_evaluation(period=0) # Suppress logs per iteration
                ]
            )
            dir_models.append(dir_model)
            
            val_preds_dir = dir_model.predict(X_val, num_iteration=dir_model.best_iteration)
            oof_dir_preds.iloc[val_idx] = val_preds_dir
            dir_score = roc_auc_score(y_val, val_preds_dir, sample_weight=fp_val)
            
            if dir_score > best_dir_score:
                best_dir_score = dir_score
                best_dir_model = dir_model

            # --- Train Edge Model ---
            etrain = lgb.Dataset(X_train, label=edge_train, weight=fp_train, feature_name=feature_names)
            eval_data = lgb.Dataset(X_val, label=edge_val, weight=fp_val, reference=etrain)
            
            edge_model = lgb.train(
                edge_params,
                etrain,
                valid_sets=[etrain, eval_data],
                num_boost_round=500,
                callbacks=[
                    lgb.early_stopping(stopping_rounds=30, verbose=False),
                    lgb.log_evaluation(period=0)
                ]
            )
            edge_models.append(edge_model)
            
            val_preds_edge = edge_model.predict(X_val, num_iteration=edge_model.best_iteration)
            oof_edge_preds.iloc[val_idx] = val_preds_edge
            # Use weighted MAE for scoring
            edge_score = np.average(np.abs(val_preds_edge - edge_val), weights=fp_val) 
            
            if edge_score < best_edge_score:
                best_edge_score = edge_score
                best_edge_model = edge_model
            
            logger.info(f"Fold {fold + 1}: Direction AUC = {dir_score:.4f}, Edge MAE = {edge_score:.4f}")

    except Exception as e:
        logger.error(f"Error during cross-validation: {e}")
        return None, None

    # --- Final Validation and Model Selection ---
    logger.info("\nCV Results:")
    final_dir_auc = roc_auc_score(y.loc[oof_dir_preds.dropna().index], oof_dir_preds.dropna(), sample_weight=fill_prob.loc[oof_dir_preds.dropna().index])
    final_edge_mae = np.average(np.abs(edge.loc[oof_edge_preds.dropna().index] - oof_edge_preds.dropna()), weights=fill_prob.loc[oof_edge_preds.dropna().index])
    
    logger.info(f"OOF Direction AUC: {final_dir_auc:.4f}")
    logger.info(f"OOF Edge MAE: {final_edge_mae:.4f}")
    logger.info(f"(Best Fold Direction AUC: {best_dir_score:.4f})")
    logger.info(f"(Best Fold Edge MAE: {best_edge_score:.4f})")

    # Validate and Plot Feature Importance for the *best* models found
    if best_dir_model:
        dir_importance = pd.DataFrame({
            'feature': best_dir_model.feature_name(),
            'importance': best_dir_model.feature_importance(importance_type='gain') # Use gain
        })
        validate_feature_importance(dir_importance, "Best Direction Model", predictions=oof_dir_preds.dropna().values, y_true=y.loc[oof_dir_preds.dropna().index].values)
        plot_feature_importance(dir_importance, "Best_Direction_Model")
        
    if best_edge_model:
        edge_importance = pd.DataFrame({
            'feature': best_edge_model.feature_name(),
            'importance': best_edge_model.feature_importance(importance_type='gain')
        })
        validate_feature_importance(edge_importance, "Best Edge Model", predictions=oof_edge_preds.dropna().values, y_true=edge.loc[oof_edge_preds.dropna().index].values)
        plot_feature_importance(edge_importance, "Best_Edge_Model")

    # Optional: Retrain on full data using best iteration count? Or return best fold model?
    # Returning best fold model is often safer against forward-looking bias.
    logger.info("Returning best models identified during CV.")
    return best_dir_model, best_edge_model


# ---------------------------------------------------------------------------
# Position sizing helper (Roadmap Point 7 - Kelly like)
# ---------------------------------------------------------------------------

def position_size(
    predicted_edge: float, # Model's predicted edge (e.g., regression output)
    predicted_vol: float, # Model's predicted volatility or use historical
    *,
    kelly_fraction: float = 0.5, # Kelly fraction (0.0 to 1.0+)
    max_leverage: float = 2.0 # Max position size as fraction of capital/max risk
) -> float:
    """Kelly‑style sizing based on predicted edge and volatility, with caps.

    Parameters
    ----------
    predicted_edge : float
        Expected edge (return - cost) from edge model prediction.
        Units should be consistent with predicted_vol (e.g., basis points or %).
    predicted_vol : float
        Expected volatility (std dev) over holding period.
        Units should be consistent with predicted_edge. Volatility squared needed for Kelly.
    kelly_fraction : float
        Fraction of Kelly criterion to use (e.g., 0.5 for half Kelly). Controls aggressiveness.
    max_leverage : float
        Maximum allowed position size / leverage.
    """
    if predicted_vol <= 1e-9: # Avoid division by zero or tiny volatility
        return 0.0
    
    # Kelly formula: f* = edge / variance (where variance = vol^2)
    # Use predicted_edge directly (assuming it's post-cost)
    kelly_size = predicted_edge / (predicted_vol**2)
    
    target_size = kelly_fraction * kelly_size
    
    # Clip size to max allowed leverage/position size
    final_size = float(np.clip(target_size, -max_leverage, max_leverage))
    
    return final_size


# ---------------------------------------------------------------------------
# CLI entry‑point
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Starting L2 Model Training Pipeline...")
    
    try:
        reader = DepthTailReader(
            dsn=settings.database.dsn,
            table="orderbook_snapshots", # Make sure table name is correct
            batch_size=100_000, # Increased batch size
        )
    except AttributeError:
        logger.error("Failed to load database DSN from settings. Ensure settings.database.dsn is configured.")
        return
    except Exception as e:
        logger.error(f"Failed to initialize DepthTailReader: {e}")
        return

    # Define training period (e.g., last 7 days for recent patterns)
    end = datetime.utcnow()
    start = end - timedelta(days=7)
    
    logger.info(f"Training window: {start.isoformat()} to {end.isoformat()}")

    # --- Prepare Dataset ---
    X, y, edge, fill_prob = prepare_dataset(
        reader, start, end, horizon=10, latency_ticks=2
    )

    if X.empty or y.empty or edge.empty:
       logger.error("Dataset preparation failed or returned empty data. Exiting.")
       return
       
    logger.info(f"Dataset ready – {len(X)} samples, {X.shape[1]} features")

    # --- Train Models ---
    dir_model, edge_model = train_model(X, y, edge, fill_prob, n_splits=5)

    # --- Save Models ---
    if dir_model:
        dir_model_path = MODEL_DIR_PATH / "direction_model.joblib"
        joblib.dump(dir_model, dir_model_path)
        logger.info(f"Saved Direction model to {dir_model_path}")
    else:
        logger.warning("Direction model training failed. No model saved.")

    if edge_model:
        edge_model_path = MODEL_DIR_PATH / "edge_model.joblib"
        joblib.dump(edge_model, edge_model_path)
        logger.info(f"Saved Edge model to {edge_model_path}")
    else:
        logger.warning("Edge model training failed. No model saved.")

    logger.info("L2 Model Training Pipeline Finished.")


if __name__ == "__main__":
    # Basic setup for running as script
    # Consider adding argparse for command-line configuration (dates, horizon, etc.)
    main()