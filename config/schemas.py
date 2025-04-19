from pydantic import BaseModel, Field, BaseSettings, SecretStr, FilePath, AnyHttpUrl


class BackpackSettings(BaseModel):
    api_key: SecretStr = Field(..., env="BACKPACK_API_KEY")
    api_secret: SecretStr = Field(..., env="BACKPACK_API_SECRET")

class DatabaseSettings(BaseModel):
    host: str = Field(..., env="DB_HOST")
    port: int = Field(..., env="DB_PORT")
    name: str = Field(..., env="DB_NAME")
    user: str = Field(..., env="DB_USER")
    password: SecretStr = Field(..., env="DB_PASSWORD")

    @property
    def dsn(self) -> str:
        # DSN for psycopg2
        return f"postgresql://{self.user}:{self.password.get_secret_value()}@{self.host}:{self.port}/{self.name}"

class TradingSettings(BaseModel):
    symbol: str = Field(..., env="SYMBOL")
    kline_memory_rows: int = Field(..., env="KLINE_MEMORY_ROWS")
    order_book_depth: int = Field(..., env="ORDER_BOOK_DEPTH")

class MLSettings(BaseModel):
    model_path: FilePath = Field(..., env="MODEL_PATH")
    prediction_threshold: float = Field(..., env="PREDICTION_THRESHOLD")
    # Optional RL Agent Path
    # rl_agent_path: Optional[FilePath] = Field(None, env="RL_AGENT_PATH")

class SizingSettings(BaseModel):
    initial_equity_usd: float = Field(..., env="INITIAL_EQUITY_USD")
    min_leverage: float = Field(..., env="MIN_LEVERAGE")
    max_leverage: float = Field(..., env="MAX_LEVERAGE")
    confidence_threshold: float = Field(..., env="CONFIDENCE_THRESHOLD")
    confidence_scale: float = Field(..., env="CONFIDENCE_SCALE")

class BracketSettings(BaseModel):
    tp_offset_pct: float = Field(..., env="TP_OFFSET_PCT")
    sl_offset_pct: float = Field(..., env="SL_OFFSET_PCT")

class RiskSettings(BaseModel):
    max_consecutive_losses: int = Field(..., env="MAX_CONSECUTIVE_LOSSES")
    max_drawdown_pct: float = Field(..., env="MAX_DRAWDOWN_PCT")
    max_notional_usd: float = Field(..., env="MAX_NOTIONAL_USD")
    fee_bps: float = Field(..., env="FEE_BPS") # Placeholder
    loss_penalty_lambda: float = Field(..., env="LOSS_PENALTY_LAMBDA")

class StrategyLoopSettings(BaseModel):
    interval_seconds: int = Field(..., env="STRATEGY_INTERVAL_SECONDS")
    model_reload_interval_seconds: int = Field(..., env="MODEL_RELOAD_INTERVAL_SECONDS")

class PathSettings(BaseModel):
    log_file: FilePath = Field(..., env="LOG_FILE")
    cpp_exec_module_path: FilePath = Field(..., env="CPP_EXEC_MODULE_PATH")

# Settings for optional S3/AWS integration
# class AWSSettings(BaseModel):
#     s3_bucket_name: str = Field(..., env="S3_BUCKET_NAME")
#     aws_access_key_id: Optional[SecretStr] = Field(None, env="AWS_ACCESS_KEY_ID")
#     aws_secret_access_key: Optional[SecretStr] = Field(None, env="AWS_SECRET_ACCESS_KEY")
#     aws_region: Optional[str] = Field(None, env="AWS_REGION")


class AppSettings(BaseSettings):
    backpack: BackpackSettings
    database: DatabaseSettings
    trading: TradingSettings
    ml: MLSettings
    sizing: SizingSettings
    bracket: BracketSettings
    risk: RiskSettings
    strategy_loop: StrategyLoopSettings
    paths: PathSettings
    # aws: Optional[AWSSettings] = None
    ws_url: AnyHttpUrl = Field(..., env="WS_URL")

    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'
        # Allow nested models to be populated from env vars
        env_nested_delimiter = '__'
        # Make paths relative to project root if not absolute
        # (Requires knowing the project root, often set at instantiation)

# Example usage:
# from pathlib import Path
# settings = AppSettings(_env_file=Path(__file__).parent.parent / '.env')
# print(settings.backpack.api_key.get_secret_value())
# print(settings.database.dsn) 