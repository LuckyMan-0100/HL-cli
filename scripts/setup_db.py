#!/usr/bin/env python3
"""
Database setup script for ML training system.
Creates necessary tables and indexes using TimescaleDB.
"""

import os
import sys
import logging
from pathlib import Path
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def setup_database(dsn: str = "postgresql://penrose@localhost:5432/trading_data"):
    """
    Set up the database schema for ML training.
    
    Args:
        dsn: Database connection string
    """
    logger.info("Starting database setup...")
    
    try:
        # Connect to database
        conn = psycopg2.connect(dsn)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        
        # Read SQL setup script
        script_dir = Path(__file__).parent
        sql_file = script_dir / "setup_db.sql"
        
        if not sql_file.exists():
            raise FileNotFoundError(f"SQL setup file not found: {sql_file}")
        
        with sql_file.open() as f:
            sql_setup = f.read()
            
        # Execute setup script
        with conn.cursor() as cur:
            logger.info("Executing setup script...")
            cur.execute(sql_setup)
            
        logger.info("Database setup completed successfully!")
        
    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during setup: {e}")
        sys.exit(1)
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    setup_database() 