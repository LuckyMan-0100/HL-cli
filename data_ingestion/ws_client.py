"""Backpack WS client – maintains in‑RAM order‑book, trades, 1‑min candles."""
import asyncio
import json
import logging
import websockets
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Any, Set
from decimal import Decimal
import asyncpg
import base64
import time
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from .settings import settings
from .models import OrderBook, OrderBookLevel, Kline, Trade
from .memory_store import OrderBookMemoryStore, KlineMemoryStore

logger = logging.getLogger(__name__)

class BackpackWebSocketClient:
    """WebSocket client for Backpack Exchange."""
    def __init__(self, symbol: str, kline_intervals: Set[str] = {"1m"}, write_to_db: bool = True):
        self.symbol = symbol
        self.kline_intervals = kline_intervals
        self.write_to_db = write_to_db
        self.ws_url = settings.ws.url
        
        # Initialize memory stores
        self.orderbook_store = OrderBookMemoryStore()
        self.kline_store = KlineMemoryStore()
        self.trade_buffer = deque(maxlen=settings.trading.trade_memory_rows)
        
        # State tracking
        self.last_sequence_id = 0
        self.orderbook_initialized = False
        self.connected = False
        self.subscribed_channels = set()
        
        # Database connection
        self.db_pool = None
        
        # API credentials
        self.api_key = settings.api.backpack_api_key.get_secret_value()
        self.api_secret = settings.api.backpack_api_secret.get_secret_value()
        
        # Load ED25519 private key
        try:
            private_key_bytes = base64.b64decode(self.api_secret)
            self.private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        except Exception as e:
            logger.error(f"Failed to load ED25519 private key: {e}")
            raise

    def _generate_signature(self, timestamp: int, window: int = 5000) -> str:
        """Generate ED25519 signature for authentication."""
        message = f"{timestamp}{window}"
        try:
            # Sign the message using ED25519
            signature = self.private_key.sign(message.encode())
            # Return base64 encoded signature
            return base64.b64encode(signature).decode()
        except Exception as e:
            logger.error(f"Failed to generate signature: {e}")
            raise

    async def _authenticate(self, ws):
        """Authenticate WebSocket connection."""
        try:
            timestamp = int(time.time() * 1000)
            window = 5000  # 5 seconds validity
            signature = self._generate_signature(timestamp, window)
            
            auth_payload = {
                "op": "auth",
                "key": self.api_key,
                "timestamp": timestamp,
                "window": window,
                "signature": signature
            }
            
            await ws.send(json.dumps(auth_payload))
            logger.info("Authentication request sent")
            
            # Wait for auth response
            response = await ws.recv()
            auth_response = json.loads(response)
            
            if auth_response.get("type") == "error":
                logger.error(f"Authentication failed: {auth_response.get('message')}")
                raise Exception("Authentication failed")
                
            if auth_response.get("type") == "authenticated":
                logger.info("Successfully authenticated")
                return True
                
            logger.error(f"Unexpected authentication response: {auth_response}")
            return False
            
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            raise

    async def _init_db_connection(self):
        """Initialize database connection."""
        try:
            self.db_pool = await asyncpg.create_pool(
                host=settings.db.host,
                port=settings.db.port,
                database=settings.db.name,
                user=settings.db.user,
                password=settings.db.password
            )
            logger.info("Database connection pool established")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    async def _connect_websocket(self):
        """Connect to WebSocket with retries."""
        while True:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    logger.info(f"Connected to WebSocket at {self.ws_url}")
                    self.connected = True
                    return ws
            except Exception as e:
                logger.error(f"Failed to connect to WebSocket: {e}")
                await asyncio.sleep(5)

    async def _subscribe_channels(self, ws):
        """Subscribe to required channels."""
        try:
            # Subscribe to orderbook
            await ws.send(json.dumps({
                "type": "subscribe",
                "channel": "orderbook",
                "symbol": self.symbol
            }))
            self.subscribed_channels.add("orderbook")
            logger.info(f"Subscribed to orderbook for {self.symbol}")

            # Subscribe to trades
            await ws.send(json.dumps({
                "type": "subscribe",
                "channel": "trades",
                "symbol": self.symbol
            }))
            self.subscribed_channels.add("trades")
            logger.info(f"Subscribed to trades for {self.symbol}")

            # Subscribe to klines for each interval
            for interval in self.kline_intervals:
                await ws.send(json.dumps({
                    "type": "subscribe",
                    "channel": f"kline_{interval}",
                    "symbol": self.symbol
                }))
                self.subscribed_channels.add(f"kline_{interval}")
                logger.info(f"Subscribed to {interval} klines for {self.symbol}")

            # Request initial order book snapshot
            await ws.send(json.dumps({
                "type": "request",
                "channel": "orderbook",
                "symbol": self.symbol
            }))

        except Exception as e:
            logger.error(f"Failed to subscribe to channels: {e}")
            raise

    async def _handle_orderbook(self, data: dict):
        """Process orderbook updates."""
        try:
            # Verify sequence continuity
            if not self.orderbook_initialized:
                if data.get("type") != "snapshot":
                    logger.warning("Waiting for initial orderbook snapshot")
                    return
                self.orderbook_initialized = True
                self.last_sequence_id = data["lastUpdateId"]
            else:
                if data.get("type") == "snapshot":
                    # Reset state for new snapshot
                    self.orderbook_initialized = True
                    self.last_sequence_id = data["lastUpdateId"]
                elif data["lastUpdateId"] <= self.last_sequence_id:
                    logger.warning(f"Skipping old orderbook update {data['lastUpdateId']}")
                    return
                elif data["lastUpdateId"] > self.last_sequence_id + 1:
                    logger.error(f"Gap in orderbook sequence, requesting new snapshot")
                    self.orderbook_initialized = False
                    return

            # Convert raw data to OrderBook model
            bids = {Decimal(str(price)): Decimal(str(qty)) for price, qty in data["bids"]}
            asks = {Decimal(str(price)): Decimal(str(qty)) for price, qty in data["asks"]}
            
            orderbook = OrderBook(
                symbol=self.symbol,
                timestamp=datetime.fromtimestamp(data["timestamp"] / 1000, tz=timezone.utc),
                bids=bids,
                asks=asks,
                last_update_id=data["lastUpdateId"]
            )
            
            # Update memory store
            self.orderbook_store.update(orderbook)
            
            # Write to database if enabled
            if self.write_to_db:
                await self._write_orderbook_to_db(orderbook)
                
        except Exception as e:
            logger.error(f"Error processing orderbook: {e}")

    async def _handle_trade(self, data: dict):
        """Process trade updates."""
        try:
            trade = Trade(
                symbol=self.symbol,
                price=Decimal(str(data["price"])),
                quantity=Decimal(str(data["quantity"])),
                timestamp=datetime.fromtimestamp(data["timestamp"] / 1000, tz=timezone.utc),
                side=data["side"],
                trade_id=str(data["tradeId"]),
                is_liquidation=data.get("liquidation", False)
            )
            
            # Update trade buffer
            self.trade_buffer.append(trade)
            
            # Write to database if enabled
            if self.write_to_db:
                await self._write_trade_to_db(trade)
                
        except Exception as e:
            logger.error(f"Error processing trade: {e}")

    async def _handle_kline(self, data: dict):
        """Process kline updates."""
        try:
            kline = Kline(
                symbol=self.symbol,
                timestamp=datetime.fromtimestamp(data["timestamp"] / 1000, tz=timezone.utc),
                interval=data["interval"],
                open=Decimal(str(data["open"])),
                high=Decimal(str(data["high"])),
                low=Decimal(str(data["low"])),
                close=Decimal(str(data["close"])),
                volume=Decimal(str(data["volume"])),
                trade_count=data["tradeCount"],
                closed=data["closed"]
            )
            
            # Update memory store
            self.kline_store.update(kline)
            
            # Write to database if enabled
            if self.write_to_db:
                await self._write_kline_to_db(kline)
                
        except Exception as e:
            logger.error(f"Error processing kline: {e}")

    async def _write_orderbook_to_db(self, orderbook: OrderBook):
        """Write orderbook snapshot to database."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO orderbook_snapshots (
                        symbol, timestamp, last_update_id, bids, asks, created_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6
                    )
                """, 
                    orderbook.symbol,
                    orderbook.timestamp,
                    orderbook.last_update_id,
                    json.dumps({str(k): str(v) for k, v in orderbook.bids.items()}),
                    json.dumps({str(k): str(v) for k, v in orderbook.asks.items()}),
                    datetime.now(timezone.utc)
                )
        except Exception as e:
            logger.error(f"Failed to write orderbook to database: {e}")

    async def _write_kline_to_db(self, kline: Kline):
        """Write kline to database."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO klines (
                        symbol, timestamp, interval, open, high, low, close,
                        volume, trade_count, closed, created_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
                    )
                """,
                    kline.symbol,
                    kline.timestamp,
                    kline.interval,
                    str(kline.open),
                    str(kline.high),
                    str(kline.low),
                    str(kline.close),
                    str(kline.volume),
                    kline.trade_count,
                    kline.closed,
                    datetime.now(timezone.utc)
                )
        except Exception as e:
            logger.error(f"Failed to write kline to database: {e}")

    async def _write_trade_to_db(self, trade: Trade):
        """Write trade to database."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO trades (
                        symbol, timestamp, price, quantity, side,
                        trade_id, is_liquidation, created_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8
                    )
                """,
                    trade.symbol,
                    trade.timestamp,
                    str(trade.price),
                    str(trade.quantity),
                    trade.side,
                    trade.trade_id,
                    trade.is_liquidation,
                    datetime.now(timezone.utc)
                )
        except Exception as e:
            logger.error(f"Failed to write trade to database: {e}")

    async def run(self):
        """Run the WebSocket client."""
        try:
            if self.write_to_db:
                await self._init_db_connection()
            
            logger.info(f"Starting WebSocket client for {self.symbol}")
            
            while True:
                try:
                    ws = await self._connect_websocket()
                    
                    # Authenticate first
                    await self._authenticate(ws)
                    
                    # Then subscribe to channels
                    await self._subscribe_channels(ws)
                    
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            channel = data.get("channel")
                            
                            if channel == "orderbook":
                                await self._handle_orderbook(data)
                            elif channel and channel.startswith("kline_"):
                                await self._handle_kline(data)
                            elif channel == "trades":
                                await self._handle_trade(data)
                                
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to decode message: {e}")
                        except Exception as e:
                            logger.error(f"Error processing message: {e}")
                            
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("WebSocket connection closed, reconnecting...")
                    self.connected = False
                    self.orderbook_initialized = False  # Reset orderbook state
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"WebSocket error: {e}")
                    self.connected = False
                    self.orderbook_initialized = False  # Reset orderbook state
                    await asyncio.sleep(5)
                    
        except Exception as e:
            logger.error(f"Fatal error in WebSocket client: {e}")
            raise

    def close(self):
        """Close the WebSocket client."""
        self.connected = False