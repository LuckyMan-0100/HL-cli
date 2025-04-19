#!/usr/bin/env python3
"""Start the data ingestion process."""

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from config.settings import settings
from data_ingestion.ws_client import BackpackWebSocketClient

logger = logging.getLogger(__name__)

class GracefulExit(SystemExit):
    pass

def handle_signal(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}. Initiating shutdown...")
    raise GracefulExit()

async def run_client():
    """Run the WebSocket client."""
    client = BackpackWebSocketClient(
        symbol=settings.trading.symbol,
        kline_intervals={"1m"},
        write_to_db=True
    )

    try:
        await client.run()
    except GracefulExit:
        logger.info("Graceful shutdown initiated...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await client.close()
        logger.info("WebSocket client shutdown complete.")

def main():
    """Main entry point."""
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
        asyncio.run(run_client())
    except GracefulExit:
        sys.exit(0)
    except Exception as e:
        logger.error(f"Failed to start client: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main() 