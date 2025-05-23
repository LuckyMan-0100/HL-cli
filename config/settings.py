"""
Global settings module for the trading system.
"""
from pathlib import Path
from typing import NamedTuple
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class DatabaseConfig(NamedTuple):
    dsn: str = "postgresql://penrose@localhost:5432/trading_data"

class TradingConfig(NamedTuple):
    symbol: str = os.getenv('TRADING__SYMBOL', 'SOL_USDC_PERP')
    leverage: float = float(os.getenv('TRADING__LEVERAGE', '1.0'))
    kline_memory_rows: int = int(os.getenv('TRADING__KLINE_MEMORY_ROWS', '1000'))
    trade_memory_rows: int = int(os.getenv('TRADING__TRADE_MEMORY_ROWS', '1000'))
    orderbook_memory_rows: int = int(os.getenv('TRADING__ORDERBOOK_MEMORY_ROWS', '1000'))
    initial_capital: float = float(os.getenv('TRADING__INITIAL_CAPITAL', '100.0'))
    taker_fee_rate: float = float(os.getenv('TRADING__TAKER_FEE_RATE', '0.001'))

class MLConfig(NamedTuple):
    model_path: Path = Path("/tmp/models/l2_model.txt")

class PathConfig(NamedTuple):
    log_file: Path = Path(os.getenv('PATHS__LOG_FILE', 'logs/training.log'))
    cpp_exec_module_path: Path = Path(os.getenv('PATHS__CPP_EXEC_MODULE', 'cpp_exec/libexec_bridge.so'))

class Settings(NamedTuple):
    database: DatabaseConfig = DatabaseConfig()
    trading: TradingConfig = TradingConfig()
    ml: MLConfig = MLConfig()
    paths: PathConfig = PathConfig()

settings = Settings() 