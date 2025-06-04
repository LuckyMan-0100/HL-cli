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
from data_ingestion.memory_store import Kline, OrderBook, OrderBookLevel
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
# --- End New Imports ---

# --- Define Paths for Executables ---
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
L1_FEEDER_PATH = WORKSPACE_ROOT / "redis_l1_feeder" / "build" / "feeder"
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
ORCHESTRATOR_CONFIG_PATH = WORKSPACE_ROOT / "orchestrator_config.json"
# --- End Define Paths ---

class PaperTradingRunner:
    def __init__(self, use_ml_model: bool = True):
        self.output_dir = Path('paper_trading_results')
        self.output_dir.mkdir(exist_ok=True)
        
        self.use_ml_model = use_ml_model # This controls if ml_signal_producer is run
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
            # api_secret_b64 = os.getenv("BACKPACK_API_SECRET_B64") # Original line
            
            # ---- MANUAL .env PARSING FOR DIAGNOSIS ----
            api_secret_b64_manual = None
            try:
                with open(env_path, 'r') as f:
                    for line in f:
                        if line.startswith("BACKPACK_API_SECRET_B64="):
                            api_secret_b64_manual = line.strip().split('=', 1)[1]
                            logger.info(f"[DEBUG run_paper_trading.py] Manually parsed API Secret: '{api_secret_b64_manual}'")
                            break
            except Exception as e:
                logger.error(f"[DEBUG run_paper_trading.py] Error manually parsing .env for secret: {e}")
            
            # Use the manually parsed secret if available, otherwise fall back to getenv (which was problematic)
            api_secret_b64 = api_secret_b64_manual if api_secret_b64_manual else os.getenv("BACKPACK_API_SECRET_B64")
            logger.info(f"[DEBUG run_paper_trading.py] API Secret selected for use: '{api_secret_b64}'")
            # ---- END MANUAL .env PARSING ----
            
            trading_symbol = os.getenv("TRADING_SYMBOL", "SOL_USDC")

            if not api_key or not api_secret_b64:
                logger.error("BACKPACK_API_KEY or BACKPACK_API_SECRET_B64 not found in .env or environment. Exiting.")
                return
            # --- End Load Environment Variables ---

            # --- Prepare Environment for exec_bridge ---
            exec_bridge_env = os.environ.copy()
            exec_bridge_env["BACKPACK_API_KEY"] = api_key
            exec_bridge_env["BACKPACK_API_SECRET_B64"] = api_secret_b64
            exec_bridge_env["TRADING_SYMBOL"] = trading_symbol
            current_dyld_path = os.getenv("DYLD_LIBRARY_PATH", "")
            additional_paths = "/opt/homebrew/lib:/usr/local/lib"
            exec_bridge_env["DYLD_LIBRARY_PATH"] = f"{additional_paths}:{current_dyld_path}" if current_dyld_path else additional_paths
            
            # ---- ADDED DEBUG LOG ----
            logger.info(f"[DEBUG run_paper_trading.py] API Secret being passed to exec_bridge_main: '{api_secret_b64}'")
            # ---- END DEBUG LOG ----
            
            logger.info("Starting L1 Feeder, ML Signal Producer (if enabled), and Execution Bridge...")

            # --- Start L1 Feeder ---
            logger.info(f"Attempting to start L1 Feeder: {L1_FEEDER_PATH}")
            l1_feeder_proc = subprocess.Popen(
                [str(L1_FEEDER_PATH)],
                cwd=WORKSPACE_ROOT,
                env=exec_bridge_env, # Feeder might need DYLD_LIBRARY_PATH for its own dependencies
                stdout=subprocess.PIPE, stderr=subprocess.PIPE # Keep L1 feeder quiet for now
            )
            self.processes.append(l1_feeder_proc)
            logger.info(f"Started L1 Feeder (PID: {l1_feeder_proc.pid})")
            # --- End Start L1 Feeder ---

            await asyncio.sleep(2) 

            # --- Start ML Signal Producer ---
            if self.use_ml_model: 
                logger.info(f"Attempting to start ML Signal Producer: {ML_SIGNAL_PRODUCER_PATH}")
                ml_producer_proc = subprocess.Popen(
                    [sys.executable, str(ML_SIGNAL_PRODUCER_PATH)], 
                    cwd=WORKSPACE_ROOT,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE # Keep ML producer quiet for now
                )
                self.processes.append(ml_producer_proc)
                logger.info(f"Started ML Signal Producer (PID: {ml_producer_proc.pid})")
            # --- End Start ML Signal Producer ---
            
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
                for i, proc in enumerate(self.processes):
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
                if not self.is_running:
                    break
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
    parser = argparse.ArgumentParser(description='Run paper trading test with C++ exec_bridge')
    parser.add_argument('--days', type=float, default=0.01, 
                        help='Duration in days to run paper trading')
    parser.add_argument('--use-ml', action=argparse.BooleanOptionalAction, default=True, 
                        help='Enable/Disable ML signal producer. Default: enabled.')
    args = parser.parse_args()
    
    runner = PaperTradingRunner(use_ml_model=args.use_ml)
    
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