"""
Redis publisher for L1 (bookTicker) data from Backpack WebSocket stream.
"""

import asyncio
import json
import logging
import os
import random
from typing import Dict, Optional
import redis.asyncio as redis
import websockets
from datetime import datetime

logger = logging.getLogger(__name__)

class RedisPublisher:
    """Publishes L1 quote data to Redis from Backpack WebSocket stream."""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6969,
        db: int = 0,
        max_reconnect_attempts: int = 5,
        reconnect_delay: float = 1.0,
        channel: str = "l1:quotes",
        test_channel: str = "l1:test",
        symbol: str = os.getenv("TRADING_SYMBOL", "WIF_USDC_PERP"),
        ws_url: str = "wss://ws.backpack.exchange"
    ):
        # Allow environment overrides (REDIS_HOST / REDIS_PORT) for easy config
        self.host = os.getenv("REDIS_HOST", host)
        self.port = int(os.getenv("REDIS_PORT", port))
        self.db = db
        self.channel = channel
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.channel = channel
        self.test_channel = test_channel
        self.symbol = symbol
        self.ws_url = ws_url
        self.redis: Optional[redis.Redis] = None
        self._stop = False
        
    async def connect(self) -> bool:
        """Connect to Redis."""
        try:
            self.redis = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                decode_responses=True
            )
            await self.redis.ping()
            logger.info(f"Connected to Redis at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            return False
            
    async def publish(self, quote: Dict) -> None:
        """Publish quote data to Redis channel."""
        if not self.redis:
            logger.error("Not connected to Redis")
            return
            
        try:
            await self.redis.publish(self.channel, json.dumps(quote))
            logger.debug(f"Published quote: {quote}")
        except Exception as e:
            logger.error(f"Failed to publish quote: {e}")

    def _transform_bookticker(self, msg: Dict) -> Dict:
        """
        Transform a Backpack `bookTicker` message into our internal JSON schema,
        mirroring the field names and data-types defined in the Backpack docs:
        https://docs.backpack.exchange/#bookticker-stream

        Notes
        -----
        * Prices / quantities are kept **as strings** to avoid precision loss.
        * Both timestamps are preserved **in microseconds** (64-bit int).
        * Works with wrapped messages (`{"stream": ..., "data": {...}}`)
          and with raw payloads.
        """
        # Detect the Backpack / Binance-style envelope
        payload: Dict = msg.get("data", msg)

        return {
            "symbol": payload["s"],
            "bidPrice": payload["b"],
            "bidQty": payload["B"],
            "askPrice": payload["a"],
            "askQty": payload["A"],
            "eventTime": payload["E"],     # microseconds since Unix epoch
            "engineTime": payload["T"],    # microseconds since Unix epoch
            "timestamp": payload["T"],     # alias for backward compatibility
            "updateId": payload["u"]
        }

    async def stream_bookticker(self) -> None:
        """Stream and publish real bookTicker data from Backpack."""
        if not await self.connect():
            return

        logger.info(f"Starting bookTicker stream for {self.symbol}")
        
        subscribe_msg = {
            "method": "SUBSCRIBE",
            "params": [
                f"bookTicker.{self.symbol}"
            ]
        }

        while not self._stop:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    # Subscribe to the bookTicker stream
                    await ws.send(json.dumps(subscribe_msg))
                    logger.info(f"Subscribed to bookTicker.{self.symbol}")

                    while not self._stop:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        
                        # Skip non-bookTicker messages
                        if not isinstance(data, dict) or "stream" not in data or not data["stream"].startswith("bookTicker."):
                            logger.debug(f"Skipping non-bookTicker message: {data}")
                            continue
                            
                        # Transform and publish
                        quote = self._transform_bookticker(data)
                        await self.publish(quote)

            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed, reconnecting...")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error in bookTicker stream: {e}")
                await asyncio.sleep(1)

    async def stream_test_data(self, base_price: float = 100.0) -> None:
        """Stream and publish synthetic test data."""
        if not await self.connect():
            logger.error("Failed to connect to Redis")
            return

        logger.info(f"Starting synthetic test data stream for {self.symbol} on channels {self.channel} and {self.test_channel}")
        
        update_id = 1
        current_price = base_price

        while not self._stop:
            try:
                # Generate synthetic price movement
                price_change = random.uniform(-0.1, 0.1)
                current_price += price_change
                
                # Add small spread
                spread = random.uniform(0.01, 0.05)
                bid_price = current_price - spread/2
                ask_price = current_price + spread/2
                
                # Generate quantities with some randomness
                base_qty = random.uniform(10, 100)
                bid_qty = base_qty * random.uniform(0.9, 1.1)
                ask_qty = base_qty * random.uniform(0.9, 1.1)
                
                # Current timestamp in microseconds
                now_us = int(datetime.now().timestamp() * 1_000_000)
                
                quote = {
                    "symbol": self.symbol,
                    "bidPrice": f"{bid_price:.4f}",
                    "bidQty": f"{bid_qty:.4f}",
                    "askPrice": f"{ask_price:.4f}",
                    "askQty": f"{ask_qty:.4f}",
                    "eventTime": now_us,
                    "engineTime": now_us,
                    "timestamp": now_us,
                    "updateId": update_id
                }
                
                # Publish to both channels
                quote_json = json.dumps(quote)
                logger.debug(f"Publishing test quote: {quote}")
                await self.redis.publish(self.test_channel, quote_json)
                await self.redis.publish(self.channel, quote_json)
                logger.debug(f"Successfully published test quote {update_id}")
                
                update_id += 1
                await asyncio.sleep(1)  # Publish once per second

            except Exception as e:
                logger.error(f"Error publishing test data: {e}")
                await asyncio.sleep(1)
                
    def stop(self) -> None:
        """Stop the publisher."""
        self._stop = True
        
    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
            self.redis = None

async def main():
    """Run the publisher with test data."""
    publisher = RedisPublisher()
    try:
        await publisher.stream_test_data()
    except KeyboardInterrupt:
        publisher.stop()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    asyncio.run(main()) 