"""
Data ingestion module settings and configuration.
"""
from typing import NamedTuple
import os
from pathlib import Path
from pydantic import SecretStr
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class DatabaseConfig(NamedTuple):
    host: str = os.getenv('DB_HOST', 'localhost')
    port: int = int(os.getenv('DB_PORT', '5432'))
    name: str = os.getenv('DB_NAME', 'trading_data')
    user: str = os.getenv('DB_USER', 'penrose')
    password: str = os.getenv('DB_PASSWORD', '')
    dsn: str = os.getenv('DB_URL', 'postgresql://penrose@localhost:5432/trading_data')

class WebSocketConfig(NamedTuple):
    url: str = os.getenv('WS_URL', 'wss://ws.backpack.exchange')

class TradingConfig(NamedTuple):
    symbol: str = os.getenv('TRADING__SYMBOL', 'SOL_USDC_PERP')
    trade_memory_rows: int = int(os.getenv('TRADING__TRADE_MEMORY_ROWS', '10000'))

class APIConfig(NamedTuple):
    backpack_api_key: SecretStr = SecretStr(os.getenv('BACKPACK_API_KEY', ''))
    backpack_api_secret: SecretStr = SecretStr(os.getenv('BACKPACK_API_SECRET', ''))

class Settings(NamedTuple):
    database: DatabaseConfig = DatabaseConfig()
    ws: WebSocketConfig = WebSocketConfig()
    trading: TradingConfig = TradingConfig()
    api: APIConfig = APIConfig()

settings = Settings() 