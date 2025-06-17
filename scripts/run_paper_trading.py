#!/usr/bin/env python3
"""
Script to run paper trading simulation.
"""

import argparse
import asyncio
import logging
from datetime import datetime, timedelta
from monitoring.metrics import start_metrics_server
from strategy.main_loop import StrategyLoop
import random
from decimal import Decimal
from src.data.memory_store import Kline, OrderBook, OrderBookLevel
import pandas as pd

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/paper_trading.log')
    ]
)
logger = logging.getLogger(__name__)

import os
import sys
import signal
from pathlib import Path
from prometheus_client import start_http_server

from ml.monitoring.performance_monitor import PerformanceMonitor
from feature_engineering.feature_monitor import FeatureMonitor
from risk_management.risk_manager import RiskManager, RiskLimits
from ml.inference.predictor import ModelPredictor

# --- New Imports for Process Management ---
import subprocess
import dotenv 
import time # Added for the sleep in _handle_signal
import socket
import redis
# --- End New Imports ---

# --- Define Paths for Executables ---
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
L1_FEEDER_PATH = WORKSPACE_ROOT / "connectors" / "redis_l1_feeder" / "build" / "feeder"
ML_SIGNAL_PRODUCER_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "scripts", "ml_signal_producer.py"
    )
)
EXEC_BRIDGE_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "cpp_exec", "build", "exec_bridge_main"
    )
)
ORDER_MANAGEMENT_SERVICE_SCRIPT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "scripts", "run_order_management.py"
    )
)
ORCHESTRATOR_CONFIG_PATH = WORKSPACE_ROOT / "orchestrator_config.json"
# --- End Define Paths ---

class PaperTradingRunner:
    def __init__(self, use_ml_model: bool = True, start_feeder: bool = True):
        self.output_dir = Path('paper_trading_results')
        self.output_dir.mkdir(exist_ok=True)
        
        self.use_ml_model = use_ml_model  # run ML signal producer
        self.start_feeder = start_feeder  # whether to spawn redis L1 feeder binary
        self.processes = [] # To keep track of started subprocesses

        logger.info(f"PaperTradingRunner initialized. Orchestrating external processes.")
        logger.info(f"ML Signal Producer will be run: {self.use_ml_model}")

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        
        self.is_running = True
        
    def _handle_signal(self, signum, frame):
        logger.info(f"Received signal {signum}. Shutting down subprocesses.")
        self.is_running = False
        # Reverse order of termination might be safer: exec_bridge, then ml_producer, then feeder
        for proc in reversed(self.processes):
            try:
                logger.info(f"Terminating process {proc.pid} ({proc.args[0] if isinstance(proc.args, list) else proc.args})")
                proc.terminate()
                proc.wait(timeout=5) 
            except subprocess.TimeoutExpired:
                logger.warning(f"Process {proc.pid} did not terminate gracefully, killing.")
                proc.kill()
            except Exception as e:
                logger.error(f"Error terminating process {proc.pid}: {e}")
        
        logger.info("All subprocesses signaled for termination.")
        
    async def run(self, duration_days: float = 1.0):
        try:
            # --- Load Environment Variables ---
            env_path = WORKSPACE_ROOT / ".env"
            if not env_path.exists():
                logger.error(f".env file not found at {env_path}. API keys cannot be loaded. Exiting.")
                return
            dotenv.load_dotenv(env_path)
            api_key = os.getenv("BACKPACK_API_KEY")
            api_secret = os.getenv("BACKPACK_API_SECRET")
            
            # ---- MANUAL .env PARSING FOR DIAGNOSIS ----
            api_secret_manual = None
            try:
                with open(env_path, 'r') as f:
                    for line in f:
                        if line.startswith("BACKPACK_API_SECRET="):
                            api_secret_manual = line.strip().split('=', 1)[1]
                            logger.info(f"[DEBUG run_paper_trading.py] Manually parsed API Secret: '{api_secret_manual}'")
                            break
            except Exception as e:
                logger.error(f"[DEBUG run_paper_trading.py] Error manually parsing .env for secret: {e}")
            api_secret = api_secret_manual or api_secret
            logger.info(f"[DEBUG run_paper_trading.py] API Secret selected for use: '{api_secret}'")
            # ---- END MANUAL .env PARSING ----
            
            trading_symbol = os.getenv("TRADING_SYMBOL", "SOL_USDC")

            if not api_key or not api_secret:
                logger.error("BACKPACK_API_KEY or BACKPACK_API_SECRET not found in .env or environment. Exiting.")
                return
            # --- End Load Environment Variables ---

            # --- Start Redis server process ---
            # Check if Redis is already running on the target port
            redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            try:
                sock = socket.create_connection((redis_host, redis_port), timeout=1)
                logger.info(f"Detected Redis running at {redis_host}:{redis_port}, skipping startup")
                sock.close()
            except Exception:
                # Not running, so start a new Redis server
                redis_exec = os.getenv("REDIS_SERVER_PATH", "redis-server")
                logger.info(f"Attempting to start Redis server: {redis_exec} on port {redis_port}")
                try:
                    redis_proc = subprocess.Popen(
                        [redis_exec, "--port", str(redis_port)],
                        cwd=WORKSPACE_ROOT,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    self.processes.append(redis_proc)
                    logger.info(f"Started Redis server (PID: {redis_proc.pid})")
                    await asyncio.sleep(1)  # give Redis time to initialize
                except Exception as e:
                    logger.error(f"Failed to start Redis server: {e}")

            # --- Prepare Environment for exec_bridge ---
            exec_bridge_env = os.environ.copy()
            exec_bridge_env["BACKPACK_API_KEY"] = api_key
            exec_bridge_env["BACKPACK_API_SECRET"] = api_secret
            exec_bridge_env["BACKPACK_API_SECRET_B64"] = api_secret
            exec_bridge_env["TRADING_SYMBOL"] = trading_symbol
            current_dyld_path = os.getenv("DYLD_LIBRARY_PATH", "")
            additional_paths = "/opt/homebrew/lib:/usr/local/lib"
            exec_bridge_env["DYLD_LIBRARY_PATH"] = f"{additional_paths}:{current_dyld_path}" if current_dyld_path else additional_paths
            
            # ---- ADDED DEBUG LOG ----
            logger.info(f"[DEBUG run_paper_trading.py] API Secret being passed to exec_bridge_main: '{api_secret}'")
            # ---- END DEBUG LOG ----
            
            logger.info("Starting external components...")

            # --- Start L1 Feeder (optional) ---
            if self.start_feeder:
                logger.info(f"Attempting to start L1 Feeder: {L1_FEEDER_PATH}")
                if not L1_FEEDER_PATH.exists():
                    logger.warning("L1 feeder binary not found; skipping as --skip-feeder flag not set but file missing")
                else:
                    logs_dir = WORKSPACE_ROOT / "logs"
                    logs_dir.mkdir(exist_ok=True)
                    l1_log_path = logs_dir / "l1_feeder.log"
                    l1_log_f = open(l1_log_path, "a", buffering=1)
                    l1_feeder_proc = subprocess.Popen(
                        [str(L1_FEEDER_PATH)],
                        cwd=WORKSPACE_ROOT,
                        env=exec_bridge_env,
                        stdout=l1_log_f, stderr=subprocess.STDOUT
                    )
                    self.processes.append(l1_feeder_proc)
                    self.l1_feeder_proc = l1_feeder_proc
                    self._l1_last_restart = datetime.now()
                    logger.info(f"Started L1 Feeder (PID: {l1_feeder_proc.pid})")

                    # Set up Redis subscription for heartbeat monitoring
                    try:
                        # Use health_check_interval & TCP keepalive so the connection never idles out (Redis default timeout=600 s)
                        self._l1_pubsub_client = redis.Redis(
                            host=redis_host,
                            port=redis_port,
                            decode_responses=True,
                            socket_keepalive=True,
                            health_check_interval=30  # send PING every 30 s if idle
                        )
                        self._l1_pubsub = self._l1_pubsub_client.pubsub(ignore_subscribe_messages=True)
                        self._l1_pubsub.subscribe("l1:quotes")
                        self._l1_last_quote = datetime.now()
                    except Exception as e:
                        logger.error(f"Failed to subscribe to l1:quotes for heartbeat monitoring: {e}")
            else:
                logger.info("--skip-feeder flag set; not launching L1 Feeder binary.")
            # --- End L1 Feeder ---

            await asyncio.sleep(2) # Allow L1 feeder to initialize

            # --- Start Order Management Service ---
            logger.info(f"Attempting to start Order Management Service: {ORDER_MANAGEMENT_SERVICE_SCRIPT_PATH}")
            oms_proc = subprocess.Popen(
                [sys.executable, str(ORDER_MANAGEMENT_SERVICE_SCRIPT_PATH)],
                cwd=WORKSPACE_ROOT,
                stdout=subprocess.PIPE, # Keep OMS quiet for now
                stderr=subprocess.PIPE  # Keep OMS quiet for now
            )
            self.processes.append(oms_proc)
            logger.info(f"Started Order Management Service (PID: {oms_proc.pid})")
            # --- End Start Order Management Service ---

            await asyncio.sleep(2) # Allow OMS to initialize

            # --- Start ML Signal Producer with supervision ---
            self.ml_producer_proc = None  # Track separately for restarts
            self._ml_last_start = datetime.min  # Timestamp of last start attempt

            def start_ml_producer():
                """Helper to (re)launch the ML producer and pipe logs to file."""
                # Ensure logs directory exists
                logs_dir = WORKSPACE_ROOT / "logs"
                logs_dir.mkdir(exist_ok=True)
                log_file_path = logs_dir / "ml_producer.log"
                ml_log_f = open(log_file_path, "a", buffering=1)  # line-buffered
                logger.info(f"Launching ML Signal Producer -> {ML_SIGNAL_PRODUCER_PATH}, logs: {log_file_path}")
                proc = subprocess.Popen([
                        sys.executable, str(ML_SIGNAL_PRODUCER_PATH)
                    ],
                    cwd=WORKSPACE_ROOT,
                    stdout=ml_log_f,
                    stderr=subprocess.STDOUT
                )
                self._ml_last_start = datetime.now()
                return proc

            if self.use_ml_model:
                self.ml_producer_proc = start_ml_producer()
                self.processes.append(self.ml_producer_proc)  # Still track for orderly shutdown
            # --- End ML Signal Producer supervision setup ---
            
            await asyncio.sleep(2) 

            # --- Start Execution Bridge ---
            logger.info(f"Attempting to start Execution Bridge: {EXEC_BRIDGE_PATH}")
            exec_bridge_proc = subprocess.Popen(
                [str(EXEC_BRIDGE_PATH)], 
                cwd=Path(EXEC_BRIDGE_PATH).parent,  # Run from build directory where the .dylib is located
                env=exec_bridge_env
                # stdout=subprocess.PIPE, stderr=subprocess.PIPE # Temporarily commented out for direct console output
            )
            self.processes.append(exec_bridge_proc)
            logger.info(f"Started Execution Bridge (PID: {exec_bridge_proc.pid})")
            # --- End Start Execution Bridge ---
            
            end_time = datetime.now() + timedelta(days=duration_days)
            logger.info(f"Paper trading orchestrator running until {end_time}. Monitoring subprocesses.")
            
            # Main loop: keep orchestrator alive and check subprocess health
            while self.is_running and datetime.now() < end_time:
                for i, proc in enumerate(list(self.processes)):
                    # For processes with piped stdout/stderr, you could optionally log their output here non-blockingly
                    # However, exec_bridge now prints directly to console.
                    if proc.poll() is not None: 
                        logger.error(f"Process {proc.pid} ({proc.args[0] if isinstance(proc.args, list) else proc.args}) terminated unexpectedly with code {proc.returncode}.")
                        # Log stdout and stderr from the crashed process if they were piped
                        if proc.stdout and proc.stderr: # Check if pipes exist
                            stdout, stderr = proc.communicate() # This is blocking, use after poll() is not None
                            if stdout:
                                logger.error(f"  Stdout from {proc.pid}:\n{stdout.decode(errors='replace')}")
                            if stderr:
                                logger.error(f"  Stderr from {proc.pid}:\n{stderr.decode(errors='replace')}")
                        self.is_running = False 
                        break

                # Supervise ML producer separately: restart if crashed (but keep orchestrator alive)
                if self.use_ml_model and self.ml_producer_proc and self.ml_producer_proc.poll() is not None:
                    exit_code = self.ml_producer_proc.returncode
                    logger.warning(f"ML Signal Producer exited with code {exit_code}; will attempt restart in 5s")
                    # Throttle restarts to avoid rapid crash loops
                    time_since_last = (datetime.now() - self._ml_last_start).total_seconds()
                    if time_since_last < 60:
                        await asyncio.sleep(60 - time_since_last)
                    # Remove old proc from list
                    if self.ml_producer_proc in self.processes:
                        self.processes.remove(self.ml_producer_proc)
                    self.ml_producer_proc = start_ml_producer()
                    self.processes.append(self.ml_producer_proc)

                if not self.is_running:
                    break

                # --- Heartbeat supervision for L1 feeder ---
                if hasattr(self, "_l1_pubsub"):
                    try:
                        msg = self._l1_pubsub.get_message(timeout=0.01)
                        if msg and msg["type"] == "message":
                            self._l1_last_quote = datetime.now()
                        # Periodic explicit ping every 5 minutes to make absolutely sure the connection stays open
                        if not hasattr(self, "_last_redis_ping"):
                            self._last_redis_ping = datetime.now()
                        if (datetime.now() - self._last_redis_ping).total_seconds() > 300:
                            try:
                                self._l1_pubsub_client.ping()
                                self._last_redis_ping = datetime.now()
                            except Exception as e:
                                logger.warning(f"Redis keep-alive ping failed: {e}")
                    except Exception as e:
                        logger.warning(f"Heartbeat redis get_message error: {e}")

                    # If no quote for >45s, restart feeder (throttled to 2 min between restarts)
                    if (datetime.now() - getattr(self, "_l1_last_quote", datetime.now())).total_seconds() > 45:
                        since_restart = (datetime.now() - getattr(self, "_l1_last_restart", datetime.min)).total_seconds()
                        if since_restart > 120:
                            logger.warning("No L1 quotes for 45s – restarting feeder")
                            if self.l1_feeder_proc and self.l1_feeder_proc.poll() is None:
                                self.l1_feeder_proc.terminate()
                                try:
                                    self.l1_feeder_proc.wait(timeout=5)
                                except Exception:
                                    self.l1_feeder_proc.kill()
                            # launch again
                            logs_dir = WORKSPACE_ROOT / "logs"
                            logs_dir.mkdir(exist_ok=True)
                            l1_log_path = logs_dir / "l1_feeder.log"
                            l1_log_f = open(l1_log_path, "a", buffering=1)
                            l1_feeder_proc = subprocess.Popen([str(L1_FEEDER_PATH)], cwd=WORKSPACE_ROOT, env=exec_bridge_env,
                                                              stdout=l1_log_f, stderr=subprocess.STDOUT)
                            self.l1_feeder_proc = l1_feeder_proc
                            self.processes.append(l1_feeder_proc)
                            self._l1_last_restart = datetime.now()
                            logger.info(f"Restarted L1 feeder (PID {l1_feeder_proc.pid})")

                await asyncio.sleep(5)  
                
            logger.info("Paper trading duration ended or shutdown initiated.")
            
        except Exception as e:
            logger.error(f"Error in paper trading orchestration: {e}", exc_info=True)
            raise 
        finally:
            logger.info("Initiating final shutdown of subprocesses...")
            self.is_running = False 
            self._handle_signal(signal.SIGTERM, None) 
            logger.info("Paper trading orchestrator shut down.")
            

def main():
    parser = argparse.ArgumentParser(description='Run paper trading simulation')
    parser.add_argument('--days', type=float, default=0.01, 
                        help='Duration in days to run paper trading')
    parser.add_argument('--use-ml', action='store_true', help='Use ML model for signal generation')
    parser.add_argument('--skip-feeder', action='store_true', help='Skip launching the L1 feeder binary')
    args = parser.parse_args()
    
    runner = PaperTradingRunner(use_ml_model=args.use_ml, start_feeder=not args.skip_feeder)
    
    try:
        asyncio.run(runner.run(duration_days=args.days))
    except KeyboardInterrupt:
        logger.info("Paper trading orchestrator interrupted by user.")
    except Exception as e:
        logger.error(f"Paper trading orchestrator failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Ensuring all subprocesses are terminated post main run.")
        if 'runner' in locals() and hasattr(runner, 'processes') and runner.processes:
            active_procs = [p for p in runner.processes if p.poll() is None]
            if active_procs:
                logger.info(f"Final termination for {len(active_procs)} remaining processes.")
                for proc in active_procs:
                    if proc.poll() is None: 
                        try:
                            proc.terminate()
                            proc.wait(timeout=2)
                        except:
                            try:
                                proc.kill()
                                proc.wait(timeout=1)
                            except:
                                logger.error(f"Failed to kill process {proc.pid} during final cleanup.")
                    logger.info(f"Process {proc.pid} status: {proc.poll()}")

if __name__ == '__main__':
    main()