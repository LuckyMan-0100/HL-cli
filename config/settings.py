import os
from pathlib import Path
from dotenv import load_dotenv
from functools import lru_cache
from .schemas import AppSettings
import logging

# Determine project root based on this file's location
# Assumes config/ is one level down from the project root
PROJECT_ROOT = Path(__file__).parent.parent

# Load .env file from project root
dotenv_path = PROJECT_ROOT / '.env'
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)
    logging.info(f"Loaded environment variables from: {dotenv_path}")
else:
    logging.warning(f".env file not found at {dotenv_path}. Using environment variables only.")

@lru_cache()
def get_settings() -> AppSettings:
    """Loads and returns the application settings, cached for performance."""
    try:
        # Pass the explicit path to _env_file, though load_dotenv should have handled it
        # Pydantic-settings prioritizes actual env vars over the .env file
        settings = AppSettings(_env_file=dotenv_path if dotenv_path.exists() else None)

        # Resolve relative paths relative to the project root
        if not settings.ml.model_path.is_absolute():
            settings.ml.model_path = PROJECT_ROOT / settings.ml.model_path
        if not settings.paths.log_file.is_absolute():
            settings.paths.log_file = PROJECT_ROOT / settings.paths.log_file
        if not settings.paths.cpp_exec_module_path.is_absolute():
             settings.paths.cpp_exec_module_path = PROJECT_ROOT / settings.paths.cpp_exec_module_path

        # Create log directory if it doesn't exist
        log_dir = settings.paths.log_file.parent
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create model directory if it doesn't exist
        model_dir = settings.ml.model_path.parent
        model_dir.mkdir(parents=True, exist_ok=True)

        return settings
    except Exception as e:
        logging.error(f"Error loading settings: {e}", exc_info=True)
        # Provide more specific error messages based on validation errors if possible
        # from pydantic import ValidationError
        # if isinstance(e, ValidationError):
        #     logging.error(f"Configuration errors: {e.errors()}")
        raise ValueError(f"Could not load or validate settings. Check .env file and environment variables. Error: {e}")

# Initialize settings on import
settings = get_settings()

# Basic logging setup (can be configured further)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(settings.paths.log_file),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)
logger.info("Application settings loaded successfully.")
logger.info(f"Trading Symbol: {settings.trading.symbol}")
logger.info(f"ML Model Path: {settings.ml.model_path}")

# You can access settings throughout your application by importing this instance:
# from config.settings import settings 