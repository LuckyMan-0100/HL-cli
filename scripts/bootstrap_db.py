#!/usr/bin/env python3
"""
Database bootstrapping script.
Creates necessary tables and indexes for the trading system.
"""

import os
import sys
import argparse
import logging
from typing import List
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# SQL statements for table creation
TABLES = {
    'orderbook_snapshots': """
        CREATE TABLE IF NOT EXISTS orderbook_snapshots (
            timestamp TIMESTAMP NOT NULL,
            symbol VARCHAR(20) NOT NULL,
            bid_prices DECIMAL[] NOT NULL,
            bid_sizes DECIMAL[] NOT NULL,
            ask_prices DECIMAL[] NOT NULL,
            ask_sizes DECIMAL[] NOT NULL,
            PRIMARY KEY (timestamp, symbol)
        );
        CREATE INDEX IF NOT EXISTS idx_orderbook_timestamp ON orderbook_snapshots (timestamp);
        CREATE INDEX IF NOT EXISTS idx_orderbook_symbol ON orderbook_snapshots (symbol);
    """,
    
    'trades': """
        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP NOT NULL,
            symbol VARCHAR(20) NOT NULL,
            side VARCHAR(4) NOT NULL,
            price DECIMAL NOT NULL,
            size DECIMAL NOT NULL,
            fee DECIMAL NOT NULL,
            total_value DECIMAL NOT NULL,
            status VARCHAR(10) NOT NULL,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades (timestamp);
        CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades (symbol);
    """,
    
    'positions': """
        CREATE TABLE IF NOT EXISTS positions (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            size DECIMAL NOT NULL,
            entry_price DECIMAL NOT NULL,
            current_price DECIMAL NOT NULL,
            unrealized_pnl DECIMAL NOT NULL,
            realized_pnl DECIMAL NOT NULL,
            status VARCHAR(10) NOT NULL,
            opened_at TIMESTAMP NOT NULL,
            closed_at TIMESTAMP,
            UNIQUE (symbol, status)
        );
        CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions (symbol);
        CREATE INDEX IF NOT EXISTS idx_positions_status ON positions (status);
    """,
    
    'metrics': """
        CREATE TABLE IF NOT EXISTS metrics (
            timestamp TIMESTAMP NOT NULL,
            metric_name VARCHAR(50) NOT NULL,
            metric_value DECIMAL NOT NULL,
            metadata JSONB,
            PRIMARY KEY (timestamp, metric_name)
        );
        CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics (timestamp);
        CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics (metric_name);
    """
}

def create_database(dbname: str, host: str, port: str, user: str, password: str) -> None:
    """Create database if it doesn't exist."""
    try:
        # Connect to default database to create new one
        conn = psycopg2.connect(
            dbname='postgres',
            host=host,
            port=port,
            user=user,
            password=password
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        
        # Check if database exists
        cur.execute(f"SELECT 1 FROM pg_database WHERE datname = '{dbname}'")
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE {dbname}')
            logger.info(f"Created database: {dbname}")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        logger.error(f"Error creating database: {e}")
        sys.exit(1)

def create_tables(conn: psycopg2.extensions.connection) -> None:
    """Create necessary tables and indexes."""
    try:
        with conn.cursor() as cur:
            for table_name, sql in TABLES.items():
                cur.execute(sql)
                logger.info(f"Created/verified table: {table_name}")
        conn.commit()
        
    except Exception as e:
        logger.error(f"Error creating tables: {e}")
        conn.rollback()
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Bootstrap trading database')
    parser.add_argument('--env-file', type=str, default='.env',
                      help='Path to .env file')
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
    
    # Create database
    create_database(**db_config)
    
    try:
        # Connect to the new database
        conn = psycopg2.connect(**db_config)
        
        # Create tables
        create_tables(conn)
        
        logger.info("Database bootstrap completed successfully")
        
    except Exception as e:
        logger.error(f"Error connecting to database: {e}")
        sys.exit(1)
        
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    main() 