import asyncio
import json
import logging
from typing import Dict, Optional, Set
import websockets
from datetime import datetime
from decimal import Decimal
import time

from config.settings import settings
from .models import Trade, OrderBook, Kline
from .db_writer import PostgresWriter
from .memory_store import KlineMemoryStore, OrderBookMemoryStore, TradeBuffer

logger = logging.getLogger(__name__)

class BackpackWebSocketClient:
    """WebSocket client for Backpack Exchange."""

    def __init__(
        self,
        symbol: str = settings.trading.symbol,
        kline_intervals: Set[str] = {"1m"},  # Default to 1-minute klines
        write_to_db: bool = True
    ):
        self.symbol = symbol
        self.ws_url = str(settings.ws_url)
        self.kline_intervals = kline_intervals
        self.write_to_db = write_to_db

        # Initialize stores
        self.kline_store = KlineMemoryStore()
        self.orderbook_store = OrderBookMemoryStore()
        self.trade_buffer = TradeBuffer()
        
        if write_to_db:
            self.db_writer = PostgresWriter()
        else:
            self.db_writer = None

        # WebSocket connection
        self.ws = None
        self.connected = False
        self.last_update_id = 0  # For order book sync

    async def connect(self):
        """Establish WebSocket connection."""
        try:
            self.ws = await websockets.connect(self.ws_url)
            self.connected = True
            logger.info(f"Connected to {self.ws_url}")
            
            # Subscribe to channels
            await self._subscribe()
        except Exception as e:
            logger.error(f"Connection failed: {e}", exc_info=True)
            self.connected = False
            raise

    async def _subscribe(self):
        """Subscribe to relevant WebSocket channels."""
        subscriptions = [
            {"op": "subscribe", "channel": f"trades.{self.symbol}"},
            {"op": "subscribe", "channel": f"depth.{self.symbol}"}
        ]
        
        for interval in self.kline_intervals:
            subscriptions.append({
                "op": "subscribe",
                "channel": f"kline.{self.symbol}.{interval}"
            })

        for sub in subscriptions:
            await self.ws.send(json.dumps(sub))
            logger.info(f"Subscribed to {sub['channel']}")

    def _parse_trade(self, data: Dict) -> Trade:
        """Parse trade data from WebSocket message."""
        return Trade(
            symbol=self.symbol,
            trade_id=str(data['id']),
            price=Decimal(str(data['price'])),
            quantity=Decimal(str(data['quantity'])),
            side=data['side'].lower(),
            timestamp=datetime.fromtimestamp(data['timestamp'] / 1000),
            is_liquidation=data.get('liquidation', False)
        )

    def _parse_orderbook(self, data: Dict) -> OrderBook:
        """Parse order book data from WebSocket message."""
        bids = {Decimal(str(price)): Decimal(str(qty)) 
               for price, qty in data['bids']}
        asks = {Decimal(str(price)): Decimal(str(qty)) 
               for price, qty in data['asks']}
        
        return OrderBook(
            symbol=self.symbol,
            timestamp=datetime.fromtimestamp(data['timestamp'] / 1000),
            bids=bids,
            asks=asks,
            last_update_id=data['lastUpdateId']
        )

    def _parse_kline(self, data: Dict) -> Kline:
        """Parse kline data from WebSocket message."""
        return Kline(
            symbol=self.symbol,
            timestamp=datetime.fromtimestamp(data['timestamp'] / 1000),
            interval=data['interval'],
            open=Decimal(str(data['open'])),
            high=Decimal(str(data['high'])),
            low=Decimal(str(data['low'])),
            close=Decimal(str(data['close'])),
            volume=Decimal(str(data['volume'])),
            trade_count=data['trades'],
            closed=data['closed']
        )

    async def _handle_trade(self, data: Dict):
        """Handle incoming trade message."""
        trade = self._parse_trade(data)
        
        # Add to buffer, check if should flush
        if self.trade_buffer.add_trade(trade):
            trades = self.trade_buffer.get_trades()
            if self.write_to_db:
                try:
                    self.db_writer.write_trades(trades)
                except Exception as e:
                    logger.error(f"Failed to write trades: {e}", exc_info=True)

    async def _handle_orderbook(self, data: Dict):
        """Handle incoming order book message."""
        orderbook = self._parse_orderbook(data)
        
        # Only process if update ID is newer
        if orderbook.last_update_id <= self.last_update_id:
            return
            
        self.last_update_id = orderbook.last_update_id
        self.orderbook_store.update_order_book(orderbook)
        
        if self.write_to_db:
            try:
                self.db_writer.write_orderbook(orderbook)
            except Exception as e:
                logger.error(f"Failed to write orderbook: {e}", exc_info=True)

    async def _handle_kline(self, data: Dict):
        """Handle incoming kline message."""
        kline = self._parse_kline(data)
        self.kline_store.add_kline(kline)
        
        if self.write_to_db and kline.closed:
            try:
                self.db_writer.write_kline(kline)
            except Exception as e:
                logger.error(f"Failed to write kline: {e}", exc_info=True)

    async def process_messages(self):
        """Main message processing loop."""
        while True:
            try:
                if not self.connected:
                    await self.connect()

                message = await self.ws.recv()
                data = json.loads(message)
                
                channel = data.get('channel', '')
                
                if channel.startswith('trades'):
                    await self._handle_trade(data)
                elif channel.startswith('depth'):
                    await self._handle_orderbook(data)
                elif channel.startswith('kline'):
                    await self._handle_kline(data)
                else:
                    logger.warning(f"Unknown message type: {message}")

            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed. Reconnecting...")
                self.connected = False
                await asyncio.sleep(1)  # Wait before reconnecting
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def run(self):
        """Run the WebSocket client."""
        while True:
            try:
                await self.process_messages()
            except Exception as e:
                logger.error(f"Fatal error: {e}", exc_info=True)
                if self.ws:
                    await self.ws.close()
                await asyncio.sleep(5)  # Wait before restarting

    def close(self):
        """Clean up resources."""
        if self.db_writer:
            self.db_writer.close()

async def main():
    """Entry point for running the WebSocket client."""
    client = BackpackWebSocketClient()
    try:
        await client.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        client.close()

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run the client
    asyncio.run(main()) 