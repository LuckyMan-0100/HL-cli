"""
Run a Redis publisher with test L1 data.
"""

import asyncio
import argparse
import logging
import signal
from data_ingestion.redis_publisher import RedisPublisher

logger = logging.getLogger(__name__)

async def publish_test_data(redis_host: str, redis_port: int, symbol: str, base_price: float = 100.0):
    """Run the publisher with test data."""
    publisher = RedisPublisher(host=redis_host, port=redis_port, symbol=symbol)
    
    def handle_signal(signum, frame):
        logger.info("Stopping publisher...")
        publisher.stop()
        
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    try:
        await publisher.stream_test_data(base_price)
    except Exception as e:
        logger.error(f"Error running publisher: {e}")
    finally:
        await publisher.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Redis publisher with test data")
    parser.add_argument("--redis_host", default="localhost", help="Redis host")
    parser.add_argument("--redis_port", type=int, default=6970, help="Redis port")
    parser.add_argument("--symbol", default="SOL_USDC_PERP", help="Trading symbol")
    parser.add_argument("--base_price", type=float, default=100.0, help="Base price for test data")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    asyncio.run(publish_test_data(
        redis_host=args.redis_host,
        redis_port=args.redis_port,
        symbol=args.symbol,
        base_price=args.base_price
    )) 