#!/usr/bin/env python3
"""
Script to run Redis publisher with real L1 data from Backpack.
"""

import asyncio
import logging
import signal
from data_ingestion.redis_publisher import RedisPublisher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Run the Redis publisher with real market data."""
    publisher = RedisPublisher()
    
    def handle_signal(signum, frame):
        logger.info(f"Received signal {signum}")
        publisher.stop()
        
    # Setup signal handlers
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    try:
        await publisher.stream_bookticker()  # Use real data instead of test data
    except Exception as e:
        logger.error(f"Error in publisher: {e}")
    finally:
        await publisher.close()

if __name__ == "__main__":
    asyncio.run(main()) 