"""
feature_engineering/labeller.py
-------------------------------
Creates binary labels:

label = 1 (“good to enter”) if the forward `look_ahead`‑minute return exceeds
`ret_thresh` **and** the realised intraperiod ATR multiple is below
`vol_thresh`; else 0.

Outputs `data/dataset.parquet` which contains features + label.
"""

import os
import pathlib

import pandas as pd


def label_df(
    df: pd.DataFrame,
    look_ahead: int = 5,
    ret_thresh: float = 0.002,  # 0.2 %
    vol_thresh: float = 1.5,
) -> pd.DataFrame:
    forward_close = df["close"].shift(-look_ahead)
    future_ret = (forward_close - df["close"]) / df["close"]

    # Volatility proxy: future average true range % of close
    future_atr = df["ATRr_14"].shift(-look_ahead)  # ATR% column added by pandas_ta

    label = (future_ret > ret_thresh) & (future_atr < vol_thresh)
    df_out = df.copy()
    df_out["label"] = label.astype(int)
    return df_out.dropna()


def main() -> None:
    feat_path = pathlib.Path("data/features.parquet")
    if not feat_path.exists():
        raise FileNotFoundError(
            "data/features.parquet missing. Run feature_engineering.calculator first."
        )

    df = pd.read_parquet(feat_path)
    dataset = label_df(df)

    out_path = pathlib.Path("data/dataset.parquet")
    dataset.to_parquet(out_path)
    print(f"Wrote labelled dataset with {len(dataset)} rows ➜ {out_path}")


if __name__ == "__main__":
    main()