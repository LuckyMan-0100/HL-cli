import pytest
import psycopg2
import pandas as pd
import time
import os
import threading
import logging
from queue import Queue, Empty
from dotenv import load_dotenv

# Make sure TailCursor is importable (adjust path as needed)
from data_ingestion.pg_tail import TailCursor 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Load environment variables for DB connection
load_dotenv()

# Database connection parameters from environment variables
DB_PARAMS = {
    "host": os.getenv('PG_HOST', 'localhost'),
    "port": os.getenv('PG_PORT', '5432'),
    "dbname": os.getenv('PG_DBNAME', 'tradingdb'),
    "user": os.getenv('PG_USER', 'user'),
    "password": os.getenv('PG_PASSWORD', 'password')
}
TEST_TABLE = "test_orderbook_snapshots_tail"

@pytest.fixture(scope="module")
def db_connection():
    """Pytest fixture to set up and tear down the test database table."""
    conn = None
    try:
        log.info(f"Connecting to database for test setup: { {k:v for k,v in DB_PARAMS.items() if k != 'password'} }")
        conn = psycopg2.connect(**DB_PARAMS)
        conn.autocommit = True
        with conn.cursor() as cur:
            log.info(f"Dropping test table {TEST_TABLE} if exists...")
            cur.execute(f"DROP TABLE IF EXISTS {TEST_TABLE};")
            log.info(f"Creating test table {TEST_TABLE}...")
            cur.execute(f"""
                CREATE TABLE {TEST_TABLE} (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(50) NOT NULL,
                    timestamp BIGINT NOT NULL, -- Epoch milliseconds
                    last_update_id BIGINT,
                    bids JSONB,
                    asks JSONB,
                    received_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TEST_TABLE}_timestamp ON {TEST_TABLE}(timestamp);")
            log.info("Test table created.")
        yield conn
    except OperationalError as e:
         pytest.fail(f"Database connection failed: {e}. Ensure PostgreSQL is running and .env is configured correctly.")
    except Exception as e:
         pytest.fail(f"Error during DB setup: {e}")
    finally:
        if conn:
            try:
                with conn.cursor() as cur:
                    log.info(f"Dropping test table {TEST_TABLE}...")
                    cur.execute(f"DROP TABLE IF EXISTS {TEST_TABLE};")
                conn.close()
                log.info("Test database connection closed and table dropped.")
            except Exception as e:
                 log.error(f"Error during DB cleanup: {e}")

def insert_mock_data(conn, stop_event: threading.Event, insert_rate_hz=20, duration_secs=5):
    """Inserts mock data into the test table at a specified rate."""
    log.info(f"Starting mock data insertion thread (Rate: {insert_rate_hz} Hz, Duration: {duration_secs}s)")
    start_time = time.time()
    insert_count = 0
    symbol = "MOCK_TAIL_TEST"
    interval = 1.0 / insert_rate_hz

    while not stop_event.is_set() and (time.time() - start_time) < duration_secs:
        loop_start = time.time()
        try:
            with conn.cursor() as cur:
                ts = int(time.time() * 1000) # Millisecond timestamp
                bid_price = 100.0 + (insert_count % 10) * 0.01
                ask_price = bid_price + 0.01
                bids_json = f'[{{"price": {bid_price:.2f}, "quantity": 1.5}}]'
                asks_json = f'[{{"price": {ask_price:.2f}, "quantity": 2.5}}]'
                cur.execute(
                    f"INSERT INTO {TEST_TABLE} (symbol, timestamp, bids, asks) VALUES (%s, %s, %s::jsonb, %s::jsonb)",
                    (symbol, ts, bids_json, asks_json)
                )
                insert_count += 1
            # Sleep accurately to maintain rate
            elapsed = time.time() - loop_start
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                 time.sleep(sleep_time) # Use precise sleep
                 
        except OperationalError as e:
             log.error(f"Inserter: Database error: {e}. Stopping insertion.")
             break
        except Exception as e:
            log.error(f"Inserter: Error inserting mock data: {e}")
            time.sleep(0.1) # Avoid busy-looping on error
            
    log.info(f"Mock data insertion thread finished. Inserted {insert_count} rows.")

def run_tail_cursor(tailer: TailCursor, output_queue: Queue, stop_event: threading.Event):
    """Runs the TailCursor and puts results into a queue."""
    log.info("Starting TailCursor consumer thread.")
    try:
        for df_batch in tailer:
            if stop_event.is_set():
                log.info("TailCursor consumer received stop signal.")
                break
            if not df_batch.empty:
                 # log.debug(f"TailCursor consumer got batch of size {len(df_batch)}")
                 output_queue.put(df_batch)
            # else:
                 # log.debug("TailCursor consumer got empty batch")
            # TailCursor handles its own sleep
    except Exception as e:
        log.error(f"Error in TailCursor consumer thread: {e}", exc_info=True)
    finally:
        log.info("TailCursor consumer thread finished.")
        tailer.close()

@pytest.mark.integration # Mark as integration test
def test_tail_cursor_throughput(db_connection):
    """Tests if TailCursor retrieves data at the required rate."""
    if db_connection is None:
        pytest.skip("DB connection not available, skipping test.")

    insert_rate = 20 # Insert slightly faster than required read rate
    test_duration = 5 # Run test for 5 seconds
    min_expected_rows_per_sec = 10
    poll_interval = 0.1 # Poll faster than insert interval is reasonable
    batch_size = 50 # Smaller batch size for faster yielding in test

    stop_event = threading.Event()
    results_queue = Queue()

    # Start inserter thread
    inserter_thread = threading.Thread(
        target=insert_mock_data, 
        args=(db_connection, stop_event, insert_rate, test_duration), 
        daemon=True
    )
    inserter_thread.start()

    # Initialize and start TailCursor thread
    tailer = TailCursor(table_name=TEST_TABLE, 
                          timestamp_col='timestamp', 
                          batch_size=batch_size, 
                          poll_interval_secs=poll_interval)
                          
    consumer_thread = threading.Thread(
         target=run_tail_cursor, 
         args=(tailer, results_queue, stop_event),
         daemon=True
    )
    consumer_thread.start()

    # Let threads run for the test duration
    log.info(f"Running test for {test_duration} seconds...")
    time.sleep(test_duration)

    # Signal threads to stop
    log.info("Stopping threads...")
    stop_event.set()

    # Wait for threads to finish
    inserter_thread.join(timeout=2)
    consumer_thread.join(timeout=tailer.poll_interval * 5) # Wait a bit longer for consumer
    
    if inserter_thread.is_alive():
         log.warning("Inserter thread did not exit cleanly.")
    if consumer_thread.is_alive():
         log.warning("Consumer thread did not exit cleanly.")

    # Process results
    total_rows_read = 0
    while not results_queue.empty():
        try:
            df = results_queue.get_nowait()
            total_rows_read += len(df)
        except Empty:
            break
        except Exception as e:
             log.error(f"Error getting results from queue: {e}")

    log.info(f"Total rows read by TailCursor: {total_rows_read}")

    # Assertions
    assert total_rows_read > 0, "TailCursor did not read any rows."
    
    avg_rows_per_sec = total_rows_read / test_duration
    log.info(f"Average rows read per second: {avg_rows_per_sec:.2f}")
    
    assert avg_rows_per_sec >= min_expected_rows_per_sec, \
        f"Throughput too low. Expected >= {min_expected_rows_per_sec} rows/sec, Got {avg_rows_per_sec:.2f}" 