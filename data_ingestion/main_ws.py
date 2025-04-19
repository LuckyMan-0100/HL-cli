import asyncio
import logging
import signal
from typing import Set
import sys

from config.settings import settings
from .ws_client import BackpackWebSocketClient

logger = logging.getLogger(__name__)

class GracefulExit(SystemExit):
    pass

def handle_signal(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}. Initiating shutdown...")
    raise GracefulExit()

async def run_client(
    symbol: str = settings.trading.symbol,
    kline_intervals: Set[str] = {"1m"},
    write_to_db: bool = True
):
    """Run the WebSocket client with the specified configuration."""
    client = BackpackWebSocketClient(
        symbol=symbol,
        kline_intervals=kline_intervals,
        write_to_db=write_to_db
    )

    try:
        await client.run()
    except GracefulExit:
        logger.info("Graceful shutdown initiated...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        client.close()
        logger.info("WebSocket client shutdown complete.")

def main():
    """Main entry point for the WebSocket client."""
    # Set up signal handlers
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(settings.paths.log_file),
            logging.StreamHandler()
        ]
    )

    logger.info(f"Starting WebSocket client for {settings.trading.symbol}")
    
    try:
        # Run the client
        asyncio.run(run_client())
    except GracefulExit:
        sys.exit(0)
    except Exception as e:
        logger.error(f"Failed to start client: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main() 