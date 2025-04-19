#!/usr/bin/env python3
"""
Script to backfill historical kline (candlestick) data from exchange.
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
import pandas as pd
import psycopg2
from typing import List, Dict, Any
import time
from dotenv import load_dotenv
import requests
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
        base_url: str = "https://api.exchange.com"
    ):
        self.db_config = db_config
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.session = requests.Session()
        
    def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch klines from exchange API."""
        try:
            response = self.session.get(
                f"{self.base_url}/v1/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": int(start_time.timestamp() * 1000),
                    "endTime": int(end_time.timestamp() * 1000),
                    "limit": 1000
                },
                headers={
                    "X-API-Key": self.api_key
                }
            )
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return []
            
    def save_klines(self, klines: List[Dict[str, Any]], symbol: str) -> None:
        """Save klines to database."""
        if not klines:
            return
            
        try:
            conn = psycopg2.connect(**self.db_config)
            cur = conn.cursor()
            
            # Prepare data for bulk insert
            data = [(
                datetime.fromtimestamp(k["timestamp"] / 1000),
                symbol,
                float(k["open"]),
                float(k["high"]),
                float(k["low"]),
                float(k["close"]),
                float(k["volume"]),
                float(k["quote_volume"])
            ) for k in klines]
            
            # Bulk insert
            cur.executemany("""
                INSERT INTO klines (
                    timestamp,
                    symbol,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    quote_volume
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (timestamp, symbol) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    quote_volume = EXCLUDED.quote_volume
            """, data)
            
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
        """Backfill data for a single symbol."""
        current_start = start_date
        
        while current_start < end_date:
            current_end = min(current_start + chunk_size, end_date)
            
            klines = self.get_klines(symbol, interval, current_start, current_end)
            if klines:
                self.save_klines(klines, symbol)
            
            current_start = current_end
            time.sleep(1)  # Rate limiting
            
    def backfill_parallel(
        self,
        symbols: List[str],
        interval: str,
        start_date: datetime,
        end_date: datetime,
        max_workers: int = 4
    ) -> None:
        """Backfill data for multiple symbols in parallel."""
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    self.backfill_symbol,
                    symbol,
                    interval,
                    start_date,
                    end_date
                )
                for symbol in symbols
            ]
            
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Backfill failed: {e}")

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
    
    # Parse dates
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d') if args.end_date else datetime.now()
    
    # Initialize backfiller
    backfiller = KlineBackfiller(
        db_config=db_config,
        api_key=os.getenv('EXCHANGE_API_KEY', ''),
        api_secret=os.getenv('EXCHANGE_API_SECRET', ''),
        base_url=os.getenv('EXCHANGE_API_URL', '')
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