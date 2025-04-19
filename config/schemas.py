from pydantic import BaseModel, Field, SecretStr, AnyHttpUrl, HttpUrl
from typing import Union
from pydantic.networks import UrlConstraints
from pydantic_settings import BaseSettings
from pathlib import Path

# Custom WebSocket URL type
WebSocketUrl = UrlConstraints(allowed_schemes=['ws', 'wss'])

class PathConfig(BaseModel):
    """Path configuration."""
    log_file: Path = Path("trading_system.log")
    cpp_exec_module_path: Path = Path("cpp_exec/build/exec_bridge.so")

class TradingConfig(BaseModel):
    """Trading configuration."""
    symbol: str = "SOL_USDC_PERP"
    kline_memory_rows: int = 5000
    trade_memory_rows: int = 10000
    order_book_depth: int = 20
    tp_offset_pct: float = 0.0006
    sl_offset_pct: float = 0.0004

class MLConfig(BaseModel):
    """Machine learning configuration."""
    model_path: Path = Path("ml/models/boosting_model.joblib")
    prediction_threshold: float = 0.60

class SizingConfig(BaseModel):
    """Position sizing configuration."""
    initial_equity_usd: float = 100.0
    min_leverage: float = 10.0
    max_leverage: float = 100.0
    confidence_threshold: float = 0.55
    confidence_scale: float = 0.45

class RiskConfig(BaseModel):
    """Risk management configuration."""
    max_consecutive_losses: int = 3
    max_drawdown_pct: float = 0.002
    max_notional_usd: float = 1_000_000.0
    fee_bps: float = 1.5
    loss_penalty_lambda: float = 3.0

class StrategyLoopConfig(BaseModel):
    """Strategy loop configuration."""
    interval_seconds: int = 180
    model_reload_interval_seconds: int = 3600

class AppSettings(BaseSettings):
    """Application settings."""
    paths: PathConfig = PathConfig()
    trading: TradingConfig = TradingConfig()
    ml: MLConfig = MLConfig()
    sizing: SizingConfig = SizingConfig()
    risk: RiskConfig = RiskConfig()
    strategy_loop: StrategyLoopConfig = StrategyLoopConfig()

    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "trading_data"
    db_user: str = "penrose"
    db_password: str = ""
    db_url: str = "postgresql://penrose@localhost:5432/trading_data"

    # API credentials
    backpack_api_key: SecretStr = Field(default=SecretStr("YOUR_API_KEY_HERE"))
    backpack_api_secret: SecretStr = Field(default=SecretStr("YOUR_BASE64_ENCODED_PRIVATE_KEY_HERE"))

    # WebSocket URL
    ws_url: str = Field(default="wss://ws.backpack.exchange/", json_schema_extra={"format": "uri"})

    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        env_file_encoding = "utf-8"

# Example usage:
# from pathlib import Path
# settings = AppSettings(_env_file=Path(__file__).parent.parent / '.env')
# print(settings.backpack.api_key.get_secret_value())
# print(settings.database.dsn) 