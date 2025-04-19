#!/usr/bin/env python3
"""
CLI tool for monitoring the trading system.
Provides real-time metrics, position tracking, and system health checks.
"""

import os
import sys
import argparse
import logging
import time
from datetime import datetime, timedelta
import json
import curses
import psycopg2
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
import pandas as pd
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SystemMonitor:
    def __init__(self, db_config: Dict[str, str]):
        self.db_config = db_config
        self.conn = None
        self.connect_db()
        
    def connect_db(self) -> None:
        """Establish database connection."""
        try:
            self.conn = psycopg2.connect(**self.db_config)
            logger.info("Connected to database")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            sys.exit(1)
            
    def get_active_positions(self) -> List[Dict[str, Any]]:
        """Get currently active positions."""
        try:
            query = """
                SELECT symbol, size, entry_price, current_price,
                       unrealized_pnl, realized_pnl, opened_at
                FROM positions
                WHERE status = 'OPEN'
                ORDER BY unrealized_pnl DESC
            """
            return pd.read_sql(query, self.conn).to_dict('records')
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []
            
    def get_recent_trades(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent trades."""
        try:
            query = f"""
                SELECT timestamp, symbol, side, price, size,
                       fee, total_value, status
                FROM trades
                ORDER BY timestamp DESC
                LIMIT {limit}
            """
            return pd.read_sql(query, self.conn).to_dict('records')
        except Exception as e:
            logger.error(f"Failed to get trades: {e}")
            return []
            
    def get_system_metrics(self) -> Dict[str, float]:
        """Get system performance metrics."""
        try:
            # Get trading metrics
            query = """
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN total_value > 0 THEN 1 ELSE 0 END)::float / 
                        NULLIF(COUNT(*), 0) as win_rate,
                    SUM(total_value) as total_pnl,
                    AVG(total_value) as avg_trade_pnl
                FROM trades
                WHERE timestamp >= NOW() - INTERVAL '24 hours'
            """
            metrics = pd.read_sql(query, self.conn).to_dict('records')[0]
            
            # Get risk metrics
            query = """
                SELECT
                    metric_name,
                    metric_value
                FROM metrics
                WHERE timestamp >= NOW() - INTERVAL '1 hour'
                ORDER BY timestamp DESC
                LIMIT 1
            """
            risk_metrics = pd.read_sql(query, self.conn)
            for _, row in risk_metrics.iterrows():
                metrics[row['metric_name']] = row['metric_value']
                
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to get metrics: {e}")
            return {}
            
    def get_system_health(self) -> Dict[str, str]:
        """Check system health status."""
        health = {
            'database': 'OK',
            'data_feed': 'OK',
            'trading_engine': 'OK',
            'risk_manager': 'OK'
        }
        
        try:
            # Check database connectivity
            if not self.conn or self.conn.closed:
                health['database'] = 'ERROR'
                self.connect_db()
            
            # Check data feed freshness
            query = """
                SELECT MAX(timestamp) as last_update
                FROM orderbook_snapshots
            """
            last_update = pd.read_sql(query, self.conn)['last_update'].iloc[0]
            if datetime.now() - last_update > timedelta(minutes=5):
                health['data_feed'] = 'STALE'
            
            # Check trading engine activity
            query = """
                SELECT MAX(timestamp) as last_trade
                FROM trades
            """
            last_trade = pd.read_sql(query, self.conn)['last_trade'].iloc[0]
            if datetime.now() - last_trade > timedelta(hours=1):
                health['trading_engine'] = 'INACTIVE'
            
            # Check risk manager alerts
            query = """
                SELECT COUNT(*) as alert_count
                FROM metrics
                WHERE metric_name LIKE 'risk_alert%'
                AND timestamp >= NOW() - INTERVAL '1 hour'
            """
            alert_count = pd.read_sql(query, self.conn)['alert_count'].iloc[0]
            if alert_count > 0:
                health['risk_manager'] = f'ALERTS({alert_count})'
                
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            health = {k: 'ERROR' for k in health.keys()}
            
        return health
        
    def render_dashboard(self, stdscr: 'curses.window') -> None:
        """Render monitoring dashboard using curses."""
        try:
            while True:
                stdscr.clear()
                height, width = stdscr.getmaxyx()
                
                # Get data
                positions = self.get_active_positions()
                trades = self.get_recent_trades()
                metrics = self.get_system_metrics()
                health = self.get_system_health()
                
                # Render header
                header = f" Trading System Monitor | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                stdscr.addstr(0, (width - len(header)) // 2, header, curses.A_BOLD)
                
                # Render system health
                row = 2
                stdscr.addstr(row, 2, "System Health:", curses.A_BOLD)
                for component, status in health.items():
                    row += 1
                    color = curses.A_NORMAL
                    if status != 'OK':
                        color = curses.A_BOLD
                    stdscr.addstr(row, 4, f"{component}: {status}", color)
                
                # Render metrics
                row += 2
                stdscr.addstr(row, 2, "Performance Metrics:", curses.A_BOLD)
                for metric, value in metrics.items():
                    row += 1
                    stdscr.addstr(row, 4, f"{metric}: {value:.2f}")
                
                # Render active positions
                row += 2
                stdscr.addstr(row, 2, "Active Positions:", curses.A_BOLD)
                for pos in positions:
                    row += 1
                    if row >= height - 3:
                        break
                    position_str = (
                        f"{pos['symbol']}: {pos['size']:.3f} @ {pos['entry_price']:.2f} "
                        f"(PnL: {pos['unrealized_pnl']:.2f})"
                    )
                    stdscr.addstr(row, 4, position_str)
                
                # Render recent trades
                row += 2
                if row < height - 3:
                    stdscr.addstr(row, 2, "Recent Trades:", curses.A_BOLD)
                    for trade in trades:
                        row += 1
                        if row >= height - 1:
                            break
                        trade_str = (
                            f"{trade['timestamp'].strftime('%H:%M:%S')} "
                            f"{trade['symbol']} {trade['side']} "
                            f"{trade['size']:.3f} @ {trade['price']:.2f}"
                        )
                        stdscr.addstr(row, 4, trade_str)
                
                # Render footer
                footer = " Press 'q' to quit "
                stdscr.addstr(height-1, (width - len(footer)) // 2, footer, curses.A_BOLD)
                
                # Refresh and handle input
                stdscr.refresh()
                try:
                    key = stdscr.getkey()
                    if key.lower() == 'q':
                        break
                except curses.error:
                    pass
                
                time.sleep(1)
                
        except KeyboardInterrupt:
            pass
        finally:
            if self.conn:
                self.conn.close()

def main():
    parser = argparse.ArgumentParser(description='Trading system monitoring CLI')
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
    
    # Initialize monitor
    monitor = SystemMonitor(db_config)
    
    # Start curses application
    curses.wrapper(monitor.render_dashboard)

if __name__ == '__main__':
    main() 