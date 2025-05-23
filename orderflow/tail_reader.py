"""Efficient streaming reader for order book snapshots."""

import logging
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional
import json

logger = logging.getLogger(__name__)

class DepthTailReader:
    """Streams order book snapshots from Postgres with batching."""
    
    def __init__(self, dsn: str, table: str, batch_size: int = 50_000):
        self.dsn = dsn
        self.table = table
        self.batch_size = batch_size
        logger.info(
            "Initialized DepthTailReader (table=%s, batch_size=%d)",
            table, batch_size
        )

    def read_interval(
        self,
        start: datetime,
        end: datetime,
        columns: Optional[list[str]] = None
    ) -> pd.DataFrame:
        """Read order book snapshots and convert from JSONB to tidy format."""
        query = f"""
        SELECT timestamp, bids, asks
        FROM {self.table}
        WHERE timestamp BETWEEN %(start)s AND %(end)s
        AND jsonb_array_length(bids) > 0 
        AND jsonb_array_length(asks) > 0  -- Require both bids and asks
        ORDER BY timestamp
        """
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        
        logger.info(
            "Reading snapshots from %s to %s",
            start.isoformat(), end.isoformat()
        )
        
        try:
            # Read raw data in chunks and concatenate
            chunks = []
            rows_read = 0
            for chunk in pd.read_sql_query(
                query,
                self.dsn,
                params={"start": start_ms, "end": end_ms},
                chunksize=self.batch_size
            ):
                if len(chunk) == 0:
                    continue
                chunks.append(chunk)
                rows_read += len(chunk)
                logger.debug("Read chunk of %d rows (total: %d)", len(chunk), rows_read)
            
            if not chunks:
                logger.warning("No data found in the specified time range!")
                return pd.DataFrame(columns=['ts', 'side', 'price', 'qty', 'level'])
            
            df = pd.concat(chunks, ignore_index=True)
            logger.info("Read %d snapshots total", len(df))
            
            # Log sample data for debugging
            if len(df) > 0:
                sample_row = df.iloc[0]
                logger.info(f"Sample row - timestamp: {sample_row['timestamp']}")
                logger.info(f"Sample bids type: {type(sample_row['bids'])}")
                logger.info(f"Sample bids: {sample_row['bids']}")
                logger.info(f"Sample asks type: {type(sample_row['asks'])}")
                logger.info(f"Sample asks: {sample_row['asks']}")
            
            # Convert to tidy format
            records = []
            skipped_rows = 0
            for idx, row in df.iterrows():
                if idx % 1000 == 0:
                    logger.info(f"Processing row {idx}/{len(df)}")
                
                ts = pd.Timestamp(row['timestamp'], unit='ms')
                
                # Validate both bids and asks exist and are non-empty
                if not row['bids'] or not row['asks'] or len(row['bids']) == 0 or len(row['asks']) == 0:
                    skipped_rows += 1
                    logger.warning(f"Skipping row at {ts} - missing bids or asks")
                    continue
                
                # Process bids
                try:
                    bids = row['bids']
                    # Convert string or bytes to dict if needed
                    if isinstance(bids, (str, bytes)):
                        try:
                            bids = json.loads(bids)
                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse bids JSON at {ts}: {e}")
                            continue
                    
                    # Handle different possible data structures
                    if isinstance(bids, dict):
                        # If it's a dict with numeric keys
                        bids = [v for k, v in sorted(bids.items())]
                    
                    if isinstance(bids, list):
                        for level, bid in enumerate(bids, 1):
                            try:
                                # Handle different possible formats
                                if isinstance(bid, (list, tuple)) and len(bid) >= 2:
                                    price, qty = map(float, bid[:2])
                                elif isinstance(bid, dict):
                                    price = float(bid.get('price', bid.get('p', 0)))
                                    qty = float(bid.get('quantity', bid.get('qty', bid.get('q', 0))))
                                else:
                                    logger.warning(f"Unexpected bid format at {ts}: {bid}")
                                    continue
                                
                                if price <= 0 or qty <= 0:
                                    continue
                                    
                                records.append({
                                    'ts': ts,
                                    'side': 'bid',
                                    'price': price,
                                    'qty': qty,
                                    'level': level
                                })
                            except (ValueError, TypeError) as e:
                                logger.warning(f"Invalid bid values at {ts}, level {level}: {e}")
                                continue
                    else:
                        logger.warning(f"Unexpected bids structure at {ts}: {type(bids)}")
                        continue  # Skip this row entirely if bids structure is invalid
                except Exception as e:
                    logger.warning(f"Error processing bids at {ts}: {e}")
                    continue
                
                # Process asks
                try:
                    asks = row['asks']
                    # Convert string or bytes to dict if needed
                    if isinstance(asks, (str, bytes)):
                        try:
                            asks = json.loads(asks)
                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse asks JSON at {ts}: {e}")
                            continue
                    
                    # Handle different possible data structures
                    if isinstance(asks, dict):
                        # If it's a dict with numeric keys
                        asks = [v for k, v in sorted(asks.items())]
                    
                    if isinstance(asks, list):
                        for level, ask in enumerate(asks, 1):
                            try:
                                # Handle different possible formats
                                if isinstance(ask, (list, tuple)) and len(ask) >= 2:
                                    price, qty = map(float, ask[:2])
                                elif isinstance(ask, dict):
                                    price = float(ask.get('price', ask.get('p', 0)))
                                    qty = float(ask.get('quantity', ask.get('qty', ask.get('q', 0))))
                                else:
                                    logger.warning(f"Unexpected ask format at {ts}: {ask}")
                                    continue
                                
                                if price <= 0 or qty <= 0:
                                    continue
                                    
                                records.append({
                                    'ts': ts,
                                    'side': 'ask',
                                    'price': price,
                                    'qty': qty,
                                    'level': level
                                })
                            except (ValueError, TypeError) as e:
                                logger.warning(f"Invalid ask values at {ts}, level {level}: {e}")
                                continue
                    else:
                        logger.warning(f"Unexpected asks structure at {ts}: {type(asks)}")
                        continue  # Skip this row entirely if asks structure is invalid
                except Exception as e:
                    logger.warning(f"Error processing asks at {ts}: {e}")
                    continue
            
            if skipped_rows > 0:
                logger.warning(f"Skipped {skipped_rows} rows with missing or invalid order books")
            
            if not records:
                logger.warning("No valid records after processing JSONB data!")
                return pd.DataFrame(columns=['ts', 'side', 'price', 'qty', 'level'])
            
            result = pd.DataFrame.from_records(records)
            
            # Add basic data quality checks
            invalid_prices = (result['price'] <= 0).sum()
            invalid_qtys = (result['qty'] <= 0).sum()
            if invalid_prices > 0 or invalid_qtys > 0:
                logger.warning(f"Found {invalid_prices} invalid prices and {invalid_qtys} invalid quantities")
            
            # Check for missing sides
            bid_count = (result['side'] == 'bid').sum()
            ask_count = (result['side'] == 'ask').sum()
            if bid_count == 0 or ask_count == 0:
                logger.warning(f"Imbalanced order book: {bid_count} bids, {ask_count} asks")
            
            # Group by timestamp and ensure each timestamp has both sides
            side_counts = result.groupby('ts')['side'].nunique()
            incomplete_obs = (side_counts < 2).sum()
            if incomplete_obs > 0:
                logger.warning(f"Found {incomplete_obs} timestamps with missing bid or ask side")
                # Filter out incomplete observations
                complete_ts = side_counts[side_counts == 2].index
                result = result[result['ts'].isin(complete_ts)]
            
            logger.info(
                "Converted to tidy format: %d rows, %d unique timestamps",
                len(result),
                result['ts'].nunique()
            )
            
            # Log sample of processed data
            if len(result) > 0:
                logger.info("Sample of processed data:")
                logger.info(result.head().to_string())
            
            return result
            
        except Exception as e:
            logger.error("Failed to read order book data: %s", e)
            raise