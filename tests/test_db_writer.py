import pytest
import psycopg2
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any
import os
import json
from dotenv import load_dotenv

from data_ingestion.db_writer import DatabaseWriter
from data_ingestion.memory_store import OrderBook, Trade, Position

# Load test configuration
load_dotenv('.env.test')

@pytest.fixture
def db_config() -> Dict[str, str]:
    return {
        'dbname': os.getenv('TEST_DB_NAME', 'trading_test'),
        'host': os.getenv('TEST_DB_HOST', 'localhost'),
        'port': os.getenv('TEST_DB_PORT', '5432'),
        'user': os.getenv('TEST_DB_USER', 'postgres'),
        'password': os.getenv('TEST_DB_PASSWORD', '')
    }

@pytest.fixture
def db_writer(db_config):
    writer = DatabaseWriter(db_config)
    yield writer
    writer.close()

@pytest.fixture
def test_db(db_config):
    """Create test database and tables."""
    # Connect to default database
    conn = psycopg2.connect(
        dbname='postgres',
        host=db_config['host'],
        port=db_config['port'],
        user=db_config['user'],
        password=db_config['password']
    )
    conn.autocommit = True
    cur = conn.cursor()
    
    # Create test database
    cur.execute(f"DROP DATABASE IF EXISTS {db_config['dbname']}")
    cur.execute(f"CREATE DATABASE {db_config['dbname']}")
    
    # Close connection to default database
    cur.close()
    conn.close()
    
    # Connect to test database and create tables
    conn = psycopg2.connect(**db_config)
    with open('scripts/bootstrap_db.py', 'r') as f:
        script = f.read()
        
    # Extract table creation SQL
    import re
    tables = re.search(r'TABLES = {(.*?)}', script, re.DOTALL).group(1)
    tables_dict = eval('{' + tables + '}')
    
    cur = conn.cursor()
    for sql in tables_dict.values():
        cur.execute(sql)
    conn.commit()
    
    yield conn
    
    # Cleanup
    cur.close()
    conn.close()
    
    # Drop test database
    conn = psycopg2.connect(
        dbname='postgres',
        host=db_config['host'],
        port=db_config['port'],
        user=db_config['user'],
        password=db_config['password']
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {db_config['dbname']}")
    cur.close()
    conn.close()

def test_write_orderbook(db_writer, test_db):
    """Test writing orderbook data."""
    # Create test orderbook
    ob = OrderBook(
        timestamp=datetime.now(timezone.utc),
        symbol="BTC/USD",
        bids=[{"price": Decimal("50000"), "quantity": Decimal("1.0")}],
        asks=[{"price": Decimal("50100"), "quantity": Decimal("1.0")}]
    )
    
    # Write to database
    db_writer.write_orderbook(ob)
    
    # Verify
    cur = test_db.cursor()
    cur.execute("SELECT * FROM orderbook_snapshots")
    result = cur.fetchone()
    
    assert result is not None
    assert result[1] == "BTC/USD"
    assert result[2] == [Decimal("50000")]  # bid_prices
    assert result[3] == [Decimal("1.0")]    # bid_sizes
    assert result[4] == [Decimal("50100")]  # ask_prices
    assert result[5] == [Decimal("1.0")]    # ask_sizes

def test_write_trade(db_writer, test_db):
    """Test writing trade data."""
    # Create test trade
    trade = Trade(
        timestamp=datetime.now(timezone.utc),
        symbol="BTC/USD",
        side="BUY",
        price=Decimal("50000"),
        size=Decimal("1.0"),
        fee=Decimal("0.001"),
        total_value=Decimal("50000"),
        status="FILLED"
    )
    
    # Write to database
    db_writer.write_trade(trade)
    
    # Verify
    cur = test_db.cursor()
    cur.execute("SELECT * FROM trades")
    result = cur.fetchone()
    
    assert result is not None
    assert result[2] == "BTC/USD"
    assert result[3] == "BUY"
    assert result[4] == Decimal("50000")
    assert result[5] == Decimal("1.0")
    assert result[6] == Decimal("0.001")
    assert result[7] == Decimal("50000")
    assert result[8] == "FILLED"

def test_write_position(db_writer, test_db):
    """Test writing position data."""
    # Create test position
    position = Position(
        symbol="BTC/USD",
        size=Decimal("1.0"),
        entry_price=Decimal("50000"),
        current_price=Decimal("51000"),
        unrealized_pnl=Decimal("1000"),
        realized_pnl=Decimal("0"),
        status="OPEN",
        opened_at=datetime.now(timezone.utc)
    )
    
    # Write to database
    db_writer.write_position(position)
    
    # Verify
    cur = test_db.cursor()
    cur.execute("SELECT * FROM positions")
    result = cur.fetchone()
    
    assert result is not None
    assert result[1] == "BTC/USD"
    assert result[2] == Decimal("1.0")
    assert result[3] == Decimal("50000")
    assert result[4] == Decimal("51000")
    assert result[5] == Decimal("1000")
    assert result[6] == Decimal("0")
    assert result[7] == "OPEN"

def test_write_metric(db_writer, test_db):
    """Test writing metric data."""
    # Create test metric
    timestamp = datetime.now(timezone.utc)
    metric_name = "sharpe_ratio"
    metric_value = Decimal("2.5")
    metadata = {"window": "1d"}
    
    # Write to database
    db_writer.write_metric(timestamp, metric_name, metric_value, metadata)
    
    # Verify
    cur = test_db.cursor()
    cur.execute("SELECT * FROM metrics")
    result = cur.fetchone()
    
    assert result is not None
    assert result[1] == "sharpe_ratio"
    assert result[2] == Decimal("2.5")
    assert result[3] == {"window": "1d"}

def test_bulk_write(db_writer, test_db):
    """Test bulk writing of data."""
    # Create test data
    orderbooks = [
        OrderBook(
            timestamp=datetime.now(timezone.utc),
            symbol="BTC/USD",
            bids=[{"price": Decimal("50000"), "quantity": Decimal("1.0")}],
            asks=[{"price": Decimal("50100"), "quantity": Decimal("1.0")}]
        )
        for _ in range(100)
    ]
    
    # Write in bulk
    db_writer.bulk_write_orderbooks(orderbooks)
    
    # Verify
    cur = test_db.cursor()
    cur.execute("SELECT COUNT(*) FROM orderbook_snapshots")
    count = cur.fetchone()[0]
    assert count == 100

def test_error_handling(db_writer, test_db):
    """Test error handling in database writer."""
    # Test invalid data
    with pytest.raises(ValueError):
        db_writer.write_trade(None)
    
    # Test database connection error
    db_writer.close()
    with pytest.raises(Exception):
        db_writer.write_metric(
            datetime.now(timezone.utc),
            "test",
            Decimal("1.0"),
            {}
        )

def test_concurrent_writes(db_writer, test_db):
    """Test concurrent writing to database."""
    import threading
    import queue
    
    # Create a queue for results
    results = queue.Queue()
    
    def write_data():
        try:
            trade = Trade(
                timestamp=datetime.now(timezone.utc),
                symbol="BTC/USD",
                side="BUY",
                price=Decimal("50000"),
                size=Decimal("1.0"),
                fee=Decimal("0.001"),
                total_value=Decimal("50000"),
                status="FILLED"
            )
            db_writer.write_trade(trade)
            results.put(True)
        except Exception as e:
            results.put(e)
    
    # Start multiple threads
    threads = []
    for _ in range(10):
        t = threading.Thread(target=write_data)
        t.start()
        threads.append(t)
    
    # Wait for all threads to complete
    for t in threads:
        t.join()
    
    # Check results
    errors = []
    while not results.empty():
        result = results.get()
        if isinstance(result, Exception):
            errors.append(result)
    
    assert len(errors) == 0
    
    # Verify all writes succeeded
    cur = test_db.cursor()
    cur.execute("SELECT COUNT(*) FROM trades")
    count = cur.fetchone()[0]
    assert count == 10

if __name__ == '__main__':
    pytest.main([__file__]) 