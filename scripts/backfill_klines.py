#!/usr/bin/env python3
"""
Script to backfill historical kline (candlestick) data from exchange.
Includes Redis caching for improved performance and reduced API calls.
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta, timezone
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from typing import List, Dict, Any, Optional
import time
from dotenv import load_dotenv
import requests
import redis
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class KlineBackfiller:
    def __init__(
        self,
        db_config: Dict[str, str],
        api_key: str,
        api_secret: str,
        base_url: str = "https://api.backpack.exchange",
        redis_url: str = "redis://localhost:6970/0"
    ):
        self.db_config = db_config
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.session = requests.Session()
        
        # Initialize Redis connection
        try:
            self.redis = redis.from_url(redis_url)
            self.redis.ping()  # Test connection
            logger.info("Successfully connected to Redis")
        except redis.ConnectionError as e:
            logger.warning(f"Could not connect to Redis: {e}. Continuing without caching.")
            self.redis = None
    
    def _get_cache_key(self, symbol: str, interval: str, start_time: int, end_time: int) -> str:
        """Generate a cache key for kline data."""
        return f"klines:{symbol}:{interval}:{start_time}:{end_time}"
    
    def _get_from_cache(self, symbol: str, interval: str, start_time: int, end_time: int) -> Optional[List[Dict[str, Any]]]:
        """Try to get kline data from Redis cache."""
        if not self.redis:
            return None
            
        cache_key = self._get_cache_key(symbol, interval, start_time, end_time)
        cached_data = self.redis.get(cache_key)
        
        if cached_data:
            try:
                return json.loads(cached_data)
            except json.JSONDecodeError:
                return None
        return None
    
    def _store_in_cache(self, symbol: str, interval: str, start_time: int, end_time: int, data: List[Dict[str, Any]]) -> None:
        """Store kline data in Redis cache with expiration."""
        if not self.redis:
            return
            
        cache_key = self._get_cache_key(symbol, interval, start_time, end_time)
        try:
            # Cache for 1 hour for recent data, 1 day for older data
            expiry = 3600 if time.time() - end_time < 86400 else 86400
            self.redis.setex(cache_key, expiry, json.dumps(data))
        except (redis.RedisError, json.JSONEncodeError) as e:
            logger.warning(f"Failed to cache data: {e}")
    
    def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        price_type: str = "Index"
    ) -> List[Dict[str, Any]]:
        """
        Fetch klines from Backpack Exchange API with caching.
        
        Args:
            symbol: Market symbol (e.g., SOL_USDC)
            interval: Kline interval (1m, 3m, 5m, 15m, 30m, 1h, etc.)
            start_time: Start time
            end_time: End time
            price_type: Price type (Last, Index, Mark)
            
        Returns:
            List of kline dictionaries
        """
        try:
            # Ensure timezone-aware timestamps and convert to seconds
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            
            # Convert datetime to Unix timestamp in seconds (not milliseconds)
            start_ts = int(start_time.timestamp())
            end_ts = int(end_time.timestamp())
            
            # Try to get from cache first
            cached_data = self._get_from_cache(symbol, interval, start_ts, end_ts)
            if cached_data:
                logger.debug(f"Cache hit for {symbol} {interval} {start_time} to {end_time}")
                return cached_data
            
            # If not in cache, fetch from API
            response = self.session.get(
                f"{self.base_url}/api/v1/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": start_ts,  # API expects seconds
                    "endTime": end_ts,      # API expects seconds
                    "priceType": price_type
                },
                headers={
                    "X-API-Key": self.api_key,
                    "Accept": "application/json"
                }
            )
            
            if response.status_code == 429:  # Rate limit hit
                retry_after = int(response.headers.get('Retry-After', 5))
                logger.warning(f"Rate limit hit, waiting {retry_after} seconds")
                time.sleep(retry_after)
                return self.get_klines(symbol, interval, start_time, end_time, price_type)
            
            response.raise_for_status()
            data = response.json()
            
            # Store in cache if successful
            if data:
                self._store_in_cache(symbol, interval, start_ts, end_ts, data)
                logger.debug(f"Fetched and cached {len(data)} klines for {symbol}")
            
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            if hasattr(e.response, 'text'):
                logger.error(f"Response text: {e.response.text}")
            return []
    
    def save_klines(self, klines: List[Dict[str, Any]], symbol: str, interval: str) -> None:
        """Save klines to database using batch processing."""
        if not klines:
            return
            
        try:
            conn = psycopg2.connect(**self.db_config)
            cur = conn.cursor()
            
            # Prepare data for bulk insert
            data = [(
                symbol,
                interval,
                int(datetime.fromisoformat(k["start"].replace('Z', '+00:00')).timestamp() * 1000),
                float(k["open"]),
                float(k["high"]),
                float(k["low"]),
                float(k["close"]),
                float(k["volume"]),
                int(k["trades"]),
                True  # closed
            ) for k in klines]
            
            # Use execute_values for efficient batch insert
            execute_values(
                cur,
                """
                INSERT INTO klines (
                    symbol,
                    interval,
                    timestamp,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    trade_count,
                    closed
                ) VALUES %s
                ON CONFLICT (symbol, interval, timestamp) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    trade_count = EXCLUDED.trade_count,
                    closed = EXCLUDED.closed
                """,
                data,
                page_size=1000
            )
            
            conn.commit()
            logger.info(f"Saved {len(klines)} klines for {symbol}")
            
        except Exception as e:
            logger.error(f"Database error: {e}")
            if 'conn' in locals():
                conn.rollback()
        finally:
            if 'cur' in locals():
                cur.close()
            if 'conn' in locals():
                conn.close()
    
    def backfill_symbol(
        self,
        symbol: str,
        interval: str,
        start_date: datetime,
        end_date: datetime,
        chunk_size: timedelta = timedelta(days=1)
    ) -> None:
        """Backfill data for a single symbol with automatic chunk size adjustment."""
        current_start = start_date
        consecutive_errors = 0
        max_consecutive_errors = 3
        
        while current_start < end_date and consecutive_errors < max_consecutive_errors:
            current_end = min(current_start + chunk_size, end_date)
            
            try:
                klines = self.get_klines(symbol, interval, current_start, current_end)
                if klines:
                    self.save_klines(klines, symbol, interval)
                    consecutive_errors = 0  # Reset error counter on success
                    
                    # If we got less than expected data, reduce chunk size
                    if len(klines) < 100:  # Arbitrary threshold
                        chunk_size = max(chunk_size / 2, timedelta(hours=1))
                        logger.info(f"Reducing chunk size to {chunk_size}")
                else:
                    consecutive_errors += 1
                    logger.warning(f"No data received for {symbol} from {current_start} to {current_end}")
                
                current_start = current_end
                time.sleep(0.5)  # Basic rate limiting
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Error processing chunk: {e}")
                chunk_size = max(chunk_size / 2, timedelta(hours=1))
                time.sleep(1)  # Wait longer after error
        
        if consecutive_errors >= max_consecutive_errors:
            logger.error(f"Stopped backfilling {symbol} after {max_consecutive_errors} consecutive errors")
    
    def backfill_parallel(
        self,
        symbols: List[str],
        interval: str,
        start_date: datetime,
        end_date: datetime,
        max_workers: int = 4
    ) -> None:
        """Backfill data for multiple symbols in parallel with improved error handling."""
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for symbol in symbols:
                future = executor.submit(
                    self.backfill_symbol,
                    symbol,
                    interval,
                    start_date,
                    end_date
                )
                futures.append((symbol, future))
            
            # Monitor futures as they complete
            for symbol, future in futures:
                try:
                    future.result()
                    logger.info(f"Successfully completed backfill for {symbol}")
                except Exception as e:
                    logger.error(f"Backfill failed for {symbol}: {e}")

def main():
    parser = argparse.ArgumentParser(description='Backfill historical kline data')
    parser.add_argument('--symbols', type=str, required=True,
                      help='Comma-separated list of symbols')
    parser.add_argument('--interval', type=str, default='1m',
                      help='Kline interval (e.g. 1m, 5m, 1h)')
    parser.add_argument('--start-date', type=str, required=True,
                      help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str,
                      help='End date (YYYY-MM-DD), defaults to now')
    parser.add_argument('--env-file', type=str, default='.env',
                      help='Path to .env file')
    parser.add_argument('--max-workers', type=int, default=4,
                      help='Maximum number of parallel workers')
    parser.add_argument('--redis-url', type=str, default='redis://localhost:6970/0',
                      help='Redis URL for caching')
    args = parser.parse_args()
    
    # Load environment variables
    load_dotenv(args.env_file)
    
    # Get database configuration
    db_config = {
        'dbname': os.getenv('DB_NAME', 'trading'),
        'host': os.getenv('DB_HOST', 'localhost'),
        'port': os.getenv('DB_PORT', '5432'),
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', '')
    }
    
    # Parse and validate dates
    now = datetime.now(timezone.utc)
    
    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        if start_date > now:
            logger.warning(f"Start date {args.start_date} is in the future. Using 30 days ago instead.")
            start_date = now - timedelta(days=30)
        
        if args.end_date:
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            if end_date > now:
                logger.warning(f"End date {args.end_date} is in the future. Using current time instead.")
                end_date = now
        else:
            end_date = now
            
        if start_date >= end_date:
            logger.error("Start date must be before end date")
            sys.exit(1)
            
        # Limit the date range to 90 days to avoid excessive API calls
        max_days = 90
        if (end_date - start_date).days > max_days:
            logger.warning(f"Date range exceeds {max_days} days. Limiting to last {max_days} days from end date.")
            start_date = end_date - timedelta(days=max_days)
        
        logger.info(f"Fetching data from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        
    except ValueError as e:
        logger.error(f"Invalid date format: {e}")
        sys.exit(1)
    
    # Initialize backfiller
    backfiller = KlineBackfiller(
        db_config=db_config,
        api_key=os.getenv('BACKPACK_API_KEY', ''),
        api_secret=os.getenv('BACKPACK_API_SECRET', ''),
        base_url=os.getenv('BACKPACK_API_URL', 'https://api.backpack.exchange'),
        redis_url=args.redis_url
    )
    
    # Start backfill
    symbols = [s.strip() for s in args.symbols.split(',')]
    backfiller.backfill_parallel(
        symbols=symbols,
        interval=args.interval,
        start_date=start_date,
        end_date=end_date,
        max_workers=args.max_workers
    )
    
    logger.info("Backfill completed")

if __name__ == '__main__':
    main() 