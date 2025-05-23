"""
feature_stream.py
-----------------
* Consumes the real-time L2 tail via `L2TailReader`
* Computes micro-structure features (imbalance, depth ratios, etc.)
* Appends the features to `/tmp/features.parquet` for the ML stack
"""

from pathlib import Path

import pandas as pd

from settings import settings
from feature_engineering.l2_tail_reader import L2TailReader
from feature_engineering.micro_features import build_micro_features  # ← your existing util

PARQUET_PATH = Path("/tmp/features.parquet").expanduser()


def main() -> None:
    reader = L2TailReader(settings.database.dsn, batch_size=2_000)

    for batch in reader.stream():
        feats: pd.DataFrame = build_micro_features(batch)

        if PARQUET_PATH.exists():
            feats.to_parquet(PARQUET_PATH, append=True, index=False)
        else:
            feats.to_parquet(PARQUET_PATH, index=False)


if __name__ == "__main__":
    main()