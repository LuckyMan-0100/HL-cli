#!/usr/bin/env python3
"""
CLI to generate ML signals from kline data using the machine-learning model.
"""
import argparse
from pathlib import Path
import pandas as pd

# Ensure the ML module path is discoverable
import sys
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from machine_learning.model import run_ml_model


def main():
    parser = argparse.ArgumentParser(description="Generate ML signals from kline data.")
    parser.add_argument(
        "kline_file",
        type=Path,
        help="Path to kline CSV or Parquet file to process"
    )
    args = parser.parse_args()

    # Load data based on file extension
    file_path = args.kline_file
    if file_path.suffix == ".csv":
        df = pd.read_csv(str(file_path), parse_dates=[0], index_col=0)
    elif file_path.suffix in [".parquet", ".pq"]:
        df = pd.read_parquet(str(file_path))
    else:
        parser.error("Unsupported file format - use .csv or .parquet/.pq")

    # Run ML model
    results, feature_importance = run_ml_model(df)

    # Print summary results
    print("ML Signal Results:")
    for window, sharpe, mean_bps, std_bps in zip(
        results.get("window", []),
        results.get("sharpe", []),
        results.get("edge_mean_bps", []),
        results.get("edge_std_bps", [])
    ):
        print(f"Window: {window}, Sharpe: {sharpe}, Edge Mean (bps): {mean_bps}, Edge Std (bps): {std_bps}")

    # Optionally save feature importance to CSV
    output_fi = Path("feature_importance.csv")
    feature_importance.to_csv(output_fi)
    print(f"Feature importance saved to {output_fi}")


if __name__ == "__main__":
    main() 