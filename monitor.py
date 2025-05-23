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
from typing import Dict, Any, Optional
import psutil
import numpy as np
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class SystemMonitor:
    def __init__(self,
                 redis_url: str = "redis://localhost:6379",
                 pg_conn_str: Optional[str] = None,
                 feature_path: str = "/tmp/features.parquet",
                 alert_latency_threshold_us: int = 150):
        """
        Initialize system monitor.
        
        Args:
            redis_url: Redis connection URL
            pg_conn_str: PostgreSQL connection string (optional)
            feature_path: Path to feature parquet file
            alert_latency_threshold_us: Latency threshold for alerts (microseconds)
        """
        self.redis = redis.from_url(redis_url)
        self.pg_conn = psycopg2.connect(pg_conn_str) if pg_conn_str else None
        self.feature_path = Path(feature_path)
        self.alert_threshold = alert_latency_threshold_us
        
        # Monitoring state
        self.last_l1_ts = 0
        self.last_feature_ts = 0
        self.last_feature_count = 0
        
    def check_l1_latency(self) -> Dict:
        """Check L1 data latency and throughput."""
        try:
            # Subscribe to L1 quotes temporarily
            pubsub = self.redis.pubsub()
            pubsub.subscribe('l1:quotes')
            
            # Wait for message
            message = pubsub.get_message(timeout=1.0)
            if message and message['type'] == 'message':
                data = pd.read_json(message['data'])
                now = pd.Timestamp.utcnow().timestamp() * 1000
                ts = data['ts']
                
                latency = now - ts
                throughput = (ts - self.last_l1_ts) if self.last_l1_ts > 0 else 0
                self.last_l1_ts = ts
                
                return {
                    'l1_latency_us': latency * 1000,  # ms to µs
                    'l1_throughput_hz': 1000 / throughput if throughput > 0 else 0
                }
                
        except Exception as e:
            logger.error(f"Error checking L1 latency: {e}")
            
        return {'l1_latency_us': np.nan, 'l1_throughput_hz': 0}
    
    def check_feature_generation(self) -> Dict:
        """Check feature generation status."""
        try:
            if not self.feature_path.exists():
                return {
                    'feature_latency_ms': np.nan,
                    'features_per_sec': 0,
                    'feature_count': 0
                }
            
            # Read latest features
            df = pd.read_parquet(self.feature_path)
            if df.empty:
                return {
                    'feature_latency_ms': np.nan,
                    'features_per_sec': 0,
                    'feature_count': 0
                }
            
            now = pd.Timestamp.utcnow().timestamp() * 1000
            latest_ts = df['ts'].max()
            count = len(df)
            
            # Calculate metrics
            latency = now - latest_ts
            throughput = (count - self.last_feature_count) if self.last_feature_count > 0 else 0
            
            self.last_feature_ts = latest_ts
            self.last_feature_count = count
            
            return {
                'feature_latency_ms': latency,
                'features_per_sec': throughput,
                'feature_count': count
            }
            
        except Exception as e:
            logger.error(f"Error checking feature generation: {e}")
            return {
                'feature_latency_ms': np.nan,
                'features_per_sec': 0,
                'feature_count': 0
            }
    
    def check_system_resources(self) -> Dict:
        """Check system resource usage."""
        try:
            # Monitor this process
            process = psutil.Process()
            metrics = {
                'cpu_percent': process.cpu_percent(),
                'memory_mb': process.memory_info().rss / 1024 / 1024,
                'disk_usage_percent': psutil.disk_usage('/').percent,
                'open_files': len(process.open_files()),
                'threads': len(process.threads())
            }
            # Track external trading processes by name/keyword
            monitored = {'exec_bridge': 0, 'ml_signal_producer': 0, 'feeder': 0}
            for proc in psutil.process_iter(['name', 'cmdline', 'memory_info']):
                cmdline = ' '.join(proc.info.get('cmdline') or [])
                name = proc.info.get('name', '')
                rss_info = proc.info.get('memory_info')
                rss = rss_info.rss if rss_info else 0
                for key in monitored:
                    if key in cmdline or key in name:
                        monitored[key] += rss
            # Add external process memory metrics
            for key, rss in monitored.items():
                metrics[f'{key}_memory_mb'] = rss / 1024 / 1024
            return metrics
            
        except Exception as e:
            logger.error(f"Error checking system resources: {e}")
            return {
                'cpu_percent': np.nan,
                'memory_mb': np.nan,
                'disk_usage_percent': np.nan,
                'open_files': np.nan,
                'threads': np.nan
            }
    
    def run(self, interval: float = 1.0):
        """Main monitoring loop."""
        logger.info("Starting system monitor...")
        
        while True:
            try:
                # Collect metrics
                metrics = {}
                metrics.update(self.check_l1_latency())
                metrics.update(self.check_feature_generation())
                metrics.update(self.check_system_resources())
                
                # Log metrics
                logger.info("System metrics:")
                for k, v in metrics.items():
                    logger.info(f"  {k}: {v}")
                
                # Check for alerts
                if metrics['l1_latency_us'] > self.alert_threshold:
                    logger.warning(
                        f"High L1 latency: {metrics['l1_latency_us']:.2f} µs > "
                        f"{self.alert_threshold} µs threshold"
                    )
                
                if metrics['feature_latency_ms'] > 1000:  # 1 second
                    logger.warning(
                        f"High feature latency: {metrics['feature_latency_ms']:.2f} ms"
                    )
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                
            time.sleep(interval)

if __name__ == "__main__":
    # Get config from environment
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    pg_conn = os.getenv("DB_CONNECTION_STRING")
    
    monitor = SystemMonitor(
        redis_url=redis_url,
        pg_conn_str=pg_conn
    )
    monitor.run() 