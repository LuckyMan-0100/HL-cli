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

import pandas as pd
import pandas_ta as ta


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


if __name__ == "__main__":
    main()