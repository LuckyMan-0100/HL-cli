#!/usr/bin/env python3
"""
scripts/gather_ohlcv.py
-----------------------
Fetches historical OHLCV for the configured symbol & timeframe via CCXT and
stores the result as a Parquet file (`data/ohlcv.parquet`).

Environment
-----------
EXCHANGE_ID=backpack       # any exchange supported by ccxt
TRADING_SYMBOL=SOL_USDC_PERP
TIMEFRAME=1m
LOOKBACK_DAYS=30
"""

import os
import pathlib
from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd


def main() -> None:
    exch_id = os.getenv("EXCHANGE_ID", "backpack")
    symbol = os.getenv("TRADING_SYMBOL", "SOL_USDC_PERP")
    timeframe = os.getenv("TIMEFRAME", "1m")
    lookback_days = int(os.getenv("LOOKBACK_DAYS", "30"))

    exchange_class = getattr(ccxt, exch_id)
    exchange = exchange_class({"enableRateLimit": True})

    end_ts = exchange.milliseconds()
    since = int(
        (datetime.now(timezone.utc) - timedelta(days=lookback_days)).timestamp() * 1_000
    )

    all_rows = []
    while since < end_ts:
        print(f"Fetching {symbol} {timeframe} since {since}")
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        if not ohlcv:
            break
        since = ohlcv[-1][0] + 1  # move cursor
        all_rows.extend(ohlcv)

    df = pd.DataFrame(
        all_rows,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("datetime", inplace=True)

    pathlib.Path("data").mkdir(exist_ok=True)
    df.to_parquet("data/ohlcv.parquet")
    print(f"Saved {len(df)} rows to data/ohlcv.parquet")


if __name__ == "__main__":
    main()