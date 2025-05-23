"""
l2_tail_reader.py
-----------------
Stream batches from the *tail* of the `orderbook_snapshots` Postgres table in
near-real-time.  Each batch is returned as a pandas.DataFrame with columns:
    ts | side | price | qty | level
"""

from __future__ import annotations

import time
from typing import Iterator, Optional

import pandas as pd
import psycopg2
import psycopg2.extras


class L2TailReader:
    """Incremental reader that polls new rows and yields DataFrame batches."""

    def __init__(
        self,
        dsn: str,
        batch_size: int = 5_000,
        polling_interval: float = 0.2,
        start_ts: Optional[int] = None,
    ):
        self._dsn = dsn
        self._batch_size = batch_size
        self._poll = polling_interval
        self._offset_ts = start_ts

        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = True
        self._cur = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # ------------------------------------------------------------------ #
    # internal helpers                                                   #
    # ------------------------------------------------------------------ #
    def _fetch(self) -> pd.DataFrame:
        if self._offset_ts is None:
            sql = (
                "SELECT ts, side, price, qty, level "
                "FROM orderbook_snapshots "
                "ORDER BY ts ASC "
                "LIMIT %s"
            )
            self._cur.execute(sql, (self._batch_size,))
        else:
            sql = (
                "SELECT ts, side, price, qty, level "
                "FROM orderbook_snapshots "
                "WHERE ts > %s "
                "ORDER BY ts ASC "
                "LIMIT %s"
            )
            self._cur.execute(sql, (self._offset_ts, self._batch_size))

        rows = self._cur.fetchall()
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["ts", "side", "price", "qty", "level"])
        self._offset_ts = df["ts"].iloc[-1]
        return df

    # ------------------------------------------------------------------ #
    # public streaming interface                                         #
    # ------------------------------------------------------------------ #
    def stream(self) -> Iterator[pd.DataFrame]:
        """Yield DataFrame batches forever (blocks when no new data)."""
        while True:
            batch = self._fetch()
            if not batch.empty:
                yield batch
            else:
                time.sleep(self._poll)