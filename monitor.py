import os
import time
import json
import logging
import datetime
import pandas as pd
import redis
import psycopg2
from psycopg2.extras import DictCursor
from dotenv import load_dotenv
from typing import Dict, Any

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/monitor.log')
    ]
)

# Load environment variables
load_dotenv()

class TradingMonitor:
    def __init__(self):
        # Initialize connections
        self.redis = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379))
        )
        
        self.pg_conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            port=int(os.getenv('DB_PORT', 5432)),
            dbname=os.getenv('DB_NAME', 'trading_data'),
            user=os.getenv('DB_USER', 'penrose'),
            password=os.getenv('DB_PASSWORD', '')
        )
        
        # Risk parameters
        self.max_drawdown = float(os.getenv('RISK__MAX_DRAWDOWN_PCT', 0.002))
        self.max_notional = float(os.getenv('RISK__MAX_NOTIONAL_USD', 1000000.0))
        self.max_consecutive_losses = int(os.getenv('RISK__MAX_CONSECUTIVE_LOSSES', 3))
        self.initial_equity = float(os.getenv('SIZING__INITIAL_EQUITY_USD', 100.0))
        
        # State tracking
        self.last_equity = self.initial_equity
        self.consecutive_losses = 0
        self.peak_equity = self.initial_equity
        self.current_positions: Dict[str, Any] = {}
        
    def check_system_health(self) -> bool:
        """Check if all system components are running and responsive"""
        try:
            # Check Redis connection
            redis_ok = self.redis.ping()
            
            # Check PostgreSQL connection
            with self.pg_conn.cursor() as cur:
                cur.execute("SELECT 1")
                pg_ok = cur.fetchone()[0] == 1
            
            # Check data service (via Redis L1 data freshness)
            l1_data = self.redis.get('l1:quotes:last_update')
            if l1_data:
                last_update = float(l1_data)
                data_fresh = (time.time() - last_update) < 5  # Data should be < 5s old
            else:
                data_fresh = False
            
            return all([redis_ok, pg_ok, data_fresh])
            
        except Exception as e:
            logging.error(f"Health check failed: {e}")
            return False
    
    def get_current_positions(self) -> Dict[str, Any]:
        """Get current positions from the execution bridge"""
        try:
            positions_json = self.redis.get('positions:current')
            if positions_json:
                return json.loads(positions_json)
            return {}
        except Exception as e:
            logging.error(f"Error getting positions: {e}")
            return {}
    
    def calculate_risk_metrics(self) -> Dict[str, float]:
        """Calculate current risk metrics"""
        try:
            positions = self.get_current_positions()
            
            # Calculate total notional exposure
            total_notional = sum(
                abs(float(pos['size']) * float(pos['entry_price']))
                for pos in positions.values()
            )
            
            # Calculate current equity
            current_equity = float(self.redis.get('account:equity') or self.last_equity)
            self.last_equity = current_equity
            
            # Update peak equity and calculate drawdown
            self.peak_equity = max(self.peak_equity, current_equity)
            current_drawdown = (self.peak_equity - current_equity) / self.peak_equity
            
            # Calculate profit/loss
            pnl_24h = current_equity - self.initial_equity
            pnl_pct_24h = pnl_24h / self.initial_equity
            
            return {
                'total_notional': total_notional,
                'current_equity': current_equity,
                'peak_equity': self.peak_equity,
                'current_drawdown': current_drawdown,
                'pnl_24h': pnl_24h,
                'pnl_pct_24h': pnl_pct_24h
            }
            
        except Exception as e:
            logging.error(f"Error calculating risk metrics: {e}")
            return {}
    
    def check_risk_limits(self, metrics: Dict[str, float]) -> bool:
        """Check if any risk limits are breached"""
        if not metrics:
            return False
            
        breaches = []
        
        # Check notional exposure
        if metrics['total_notional'] > self.max_notional:
            breaches.append(f"Notional exposure (${metrics['total_notional']:,.2f}) exceeds limit (${self.max_notional:,.2f})")
        
        # Check drawdown
        if metrics['current_drawdown'] > self.max_drawdown:
            breaches.append(f"Current drawdown ({metrics['current_drawdown']:.2%}) exceeds limit ({self.max_drawdown:.2%})")
        
        # Check consecutive losses
        if metrics['pnl_24h'] < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                breaches.append(f"Hit {self.consecutive_losses} consecutive losses (max: {self.max_consecutive_losses})")
        else:
            self.consecutive_losses = 0
        
        if breaches:
            logging.WARNING("RISK LIMITS BREACHED:\n" + "\n".join(breaches))
            return False
        
        return True
    
    def display_status(self, metrics: Dict[str, float]):
        """Display current system status and metrics"""
        now = datetime.datetime.now()
        
        print("\033[2J\033[H")  # Clear screen
        print(f"=== Trading System Monitor === ({now:%Y-%m-%d %H:%M:%S})")
        print("\nSystem Health:")
        print(f"{'✓' if self.check_system_health() else '✗'} System Components")
        
        print("\nRisk Metrics:")
        print(f"Current Equity: ${metrics['current_equity']:,.2f}")
        print(f"Peak Equity:   ${metrics['peak_equity']:,.2f}")
        print(f"Drawdown:      {metrics['current_drawdown']:.2%}")
        print(f"24h PnL:       ${metrics['pnl_24h']:,.2f} ({metrics['pnl_pct_24h']:.2%})")
        print(f"Notional:      ${metrics['total_notional']:,.2f}")
        
        positions = self.get_current_positions()
        print("\nActive Positions:")
        for symbol, pos in positions.items():
            print(f"{symbol}: {pos['size']} @ {pos['entry_price']} (PnL: ${pos.get('unrealized_pnl', 0):,.2f})")
        
        print("\nRisk Limits:")
        print(f"Max Drawdown:  {self.max_drawdown:.2%}")
        print(f"Max Notional:  ${self.max_notional:,.2f}")
        print(f"Max Cons. Loss: {self.max_consecutive_losses}")
        
    def run(self):
        """Main monitoring loop"""
        try:
            while True:
                metrics = self.calculate_risk_metrics()
                if metrics:
                    self.display_status(metrics)
                    if not self.check_risk_limits(metrics):
                        logging.WARNING("Risk limits breached! Consider intervention.")
                time.sleep(1)  # Update every second
                
        except KeyboardInterrupt:
            logging.info("Monitoring stopped by user.")
        except Exception as e:
            logging.error(f"Monitoring error: {e}")
        finally:
            self.redis.close()
            self.pg_conn.close()

if __name__ == "__main__":
    monitor = TradingMonitor()
    monitor.run() 