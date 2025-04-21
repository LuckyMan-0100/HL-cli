import os
import time
import logging
from typing import Iterator

import pandas as pd
import psycopg2
from psycopg2 import OperationalError
from psycopg2.extras import DictCursor
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from .env file
load_dotenv()

class TailCursor:
    """Continuously tails a PostgreSQL table based on a timestamp column,
       yielding new rows in pandas DataFrame batches.
    """

    DEFAULT_POLL_INTERVAL = 0.250  # Default poll interval 250 ms
    DEFAULT_BATCH_SIZE = 1000      # Max rows per batch
    CONNECT_RETRY_DELAY = 5        # Seconds to wait before retrying DB connection

    def __init__(self, 
                 table_name: str, 
                 timestamp_col: str = 'timestamp', 
                 batch_size: int = DEFAULT_BATCH_SIZE,
                 poll_interval_secs: float = DEFAULT_POLL_INTERVAL):
        """Initializes the TailCursor.

        Args:
            table_name: The name of the table to tail.
            timestamp_col: The name of the timestamp column (must be comparable, e.g., BIGINT epoch ms).
            batch_size: The maximum number of rows to yield in each batch.
            poll_interval_secs: The interval in seconds to wait between polling the table.
        """
        if not table_name or not timestamp_col:
            raise ValueError("Table name and timestamp column must be provided.")
            
        self.table_name = table_name
        self.timestamp_col = timestamp_col
        self.batch_size = max(1, batch_size)
        self.poll_interval = max(0.01, poll_interval_secs) # Minimum poll interval 10ms
        self.last_seen_ts = 0 # Start from the beginning of time (effectively)
        self._conn = None
        self._cursor = None
        
        # Construct connection string from environment variables
        self._conn_string = self._build_conn_string()
        logging.info(f"Initialized TailCursor for table '{self.table_name}' with timestamp column '{self.timestamp_col}'.")

    def _build_conn_string(self) -> str:
        """Builds the psycopg2 connection string from environment variables."""
        host = os.getenv('PG_HOST', 'localhost')
        port = os.getenv('PG_PORT', '5432')
        dbname = os.getenv('PG_DBNAME', 'tradingdb') # Match .env.example
        user = os.getenv('PG_USER', 'user')           # Match .env.example
        password = os.getenv('PG_PASSWORD', 'password') # Match .env.example
        
        if not all([host, port, dbname, user, password]):
             logging.warning("One or more PostgreSQL connection environment variables (PG_HOST, PG_PORT, PG_DBNAME, PG_USER, PG_PASSWORD) are not set.")
             # Depending on policy, could raise an error here

        return f"dbname='{dbname}' user='{user}' host='{host}' port='{port}' password='{password}'"

    def _connect(self):
        """Establishes or re-establishes the database connection."""
        if self._conn and not self._conn.closed:
            try:
                # Quick check if connection is alive
                with self._conn.cursor() as cur:
                     cur.execute("SELECT 1")
                return # Connection is good
            except OperationalError:
                 logging.warning("Connection check failed, attempting to reconnect.")
                 self._close()
            except Exception as e:
                 logging.error(f"Unexpected error checking connection state: {e}")
                 self._close()
        
        logging.info(f"Attempting to connect to PostgreSQL: {self._conn_string.replace(os.getenv('PG_PASSWORD', ''), '****')}")
        while True:
            try:
                self._conn = psycopg2.connect(self._conn_string)
                self._conn.autocommit = True # Important for long-running cursors
                self._cursor = self._conn.cursor(cursor_factory=DictCursor)
                logging.info("PostgreSQL connection established successfully.")
                # Optionally, fetch the latest timestamp if restarting
                # self._fetch_latest_timestamp()
                return
            except OperationalError as e:
                logging.error(f"Failed to connect to PostgreSQL: {e}. Retrying in {self.CONNECT_RETRY_DELAY} seconds...")
                self._close() # Ensure resources are released before retry
                time.sleep(self.CONNECT_RETRY_DELAY)
            except Exception as e:
                 logging.error(f"Unexpected error during connection: {e}. Retrying in {self.CONNECT_RETRY_DELAY} seconds...")
                 self._close()
                 time.sleep(self.CONNECT_RETRY_DELAY)

    def _fetch_latest_timestamp(self):
        """(Optional) Fetches the latest timestamp from the table to avoid reading all history."""
        if not self._cursor:
             return
        try:
            query = f"SELECT MAX({self.timestamp_col}) FROM {self.table_name};"
            self._cursor.execute(query)
            result = self._cursor.fetchone()
            if result and result[0] is not None:
                self.last_seen_ts = result[0]
                logging.info(f"Fetched latest timestamp: {self.last_seen_ts}")
        except Exception as e:
            logging.error(f"Failed to fetch latest timestamp: {e}")
            # Decide how to handle: start from 0 or raise error?
            self.last_seen_ts = 0 # Default to starting from beginning on error


    def _close(self):
        """Closes the cursor and connection if they exist."""
        if self._cursor:
            try:
                self._cursor.close()
            except Exception as e:
                logging.warning(f"Error closing cursor: {e}")
            finally:
                 self._cursor = None
        if self._conn:
            try:
                self._conn.close()
            except Exception as e:
                logging.warning(f"Error closing connection: {e}")
            finally:
                 self._conn = None
        logging.info("PostgreSQL connection closed.")

    def __iter__(self) -> Iterator[pd.DataFrame]:
        """Returns the iterator object itself."""
        return self

    def __next__(self) -> pd.DataFrame:
        """Fetches the next batch of rows from the table.

        Returns:
            A pandas DataFrame containing the new rows.
            
        Raises:
            StopIteration: If the iteration needs to stop (e.g., external signal).
                       In practice, this tailer runs indefinitely unless interrupted.
        """
        while True: # Loop indefinitely until data is found or stopped
            self._connect() # Ensure connection is active
            if not self._cursor:
                 # Connection failed repeatedly in _connect, pause before retrying __next__
                 logging.error("Cursor not available after connection attempt. Pausing.")
                 time.sleep(self.CONNECT_RETRY_DELAY)
                 continue
                 
            try:
                # Construct query safely using psycopg2 parameter substitution
                query = f"""
                    SELECT * 
                    FROM {self.table_name} 
                    WHERE {self.timestamp_col} > %s
                    ORDER BY {self.timestamp_col} ASC
                    LIMIT %s;
                """
                params = (self.last_seen_ts, self.batch_size)
                
                # logging.debug(f"Executing query: {query} with params {params}") # Verbose
                self._cursor.execute(query, params)
                rows = self._cursor.fetchall()
                # logging.debug(f"Fetched {len(rows)} rows.") # Verbose

                if rows:
                    # Convert to DataFrame
                    df = pd.DataFrame([dict(row) for row in rows])
                    
                    # Update the last seen timestamp to the max timestamp in this batch
                    self.last_seen_ts = df[self.timestamp_col].max()
                    # logging.info(f"Processed batch up to timestamp: {self.last_seen_ts}") # Optional info log
                    return df
                else:
                    # No new rows, wait before polling again
                    time.sleep(self.poll_interval)

            except OperationalError as e:
                logging.error(f"Database operational error: {e}. Attempting reconnect...")
                self._close()
                time.sleep(self.CONNECT_RETRY_DELAY) # Wait before next iteration's connect attempt
            except Exception as e:
                logging.error(f"Error during fetch: {e}. Attempting reconnect...")
                self._close()
                time.sleep(self.CONNECT_RETRY_DELAY)

    def close(self):
        """Manually closes the database connection."""
        self._close()

# Example Usage (can be run directly for testing)
if __name__ == '__main__':
    logging.info("Starting TailCursor example...")
    
    # Ensure you have a PostgreSQL instance running and the .env file configured
    # Example .env content:
    # PG_HOST=localhost
    # PG_PORT=5432
    # PG_DBNAME=tradingdb
    # PG_USER=user
    # PG_PASSWORD=password
    
    # Assumes a table 'orderbook_snapshots' exists with a 'timestamp' column (BIGINT epoch ms)
    # Example SQL to create table and insert data:
    # CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    #     id SERIAL PRIMARY KEY,
    #     symbol VARCHAR(50) NOT NULL,
    #     timestamp BIGINT NOT NULL, -- Epoch milliseconds
    #     last_update_id BIGINT,
    #     bids JSONB,
    #     asks JSONB,
    #     received_at TIMESTAMPTZ DEFAULT NOW()
    # );
    # CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_timestamp ON orderbook_snapshots(timestamp);
    # 
    # -- Example Insert (run this periodically in another terminal using psql)
    # INSERT INTO orderbook_snapshots (symbol, timestamp, last_update_id, bids, asks) VALUES 
    # ('SOL_USDC_PERP', extract(epoch from now()) * 1000, 12345, '[{"price": 100.1, "quantity": 10}]', '[{"price": 100.2, "quantity": 5}]');

    try:
        tailer = TailCursor(table_name='orderbook_snapshots', 
                              timestamp_col='timestamp', 
                              batch_size=500, 
                              poll_interval_secs=0.5)
        
        processed_count = 0
        start_time = time.time()
        
        for batch_df in tailer:
            if not batch_df.empty:
                logging.info(f"Received batch of {len(batch_df)} rows. Max timestamp: {batch_df['timestamp'].max()}")
                # print(batch_df.head())
                processed_count += len(batch_df)
            else:
                 logging.info("Received empty batch (no new data).")
                 
            # Optional: Add a condition to break the loop for testing
            # if processed_count >= 100:
            #     logging.info("Processed 100 rows, stopping example.")
            #     break
            # if time.time() - start_time > 60: # Run for 60 seconds
            #      logging.info("Example run finished after 60 seconds.")
            #      break

    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received, shutting down...")
    except Exception as e:
        logging.error(f"An error occurred in the main loop: {e}")
    finally:
        if 'tailer' in locals() and tailer:
            tailer.close()
        logging.info("TailCursor example finished.") 