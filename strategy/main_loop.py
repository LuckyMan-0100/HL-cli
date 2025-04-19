"""
Main trading loop that orchestrates the strategy execution.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional
import uuid

from config.settings import settings
from data_ingestion.memory_store import KlineMemoryStore, OrderBookMemoryStore, TradeBuffer
from data_ingestion.ws_client import BackpackWebSocketClient
from feature_engineering.calculator import FeatureCalculator
from ml.predictor import ModelPredictor
from risk_management.risk_manager import RiskManager
from .execution_interface import LiveExecution, Order

logger = logging.getLogger(__name__)

class StrategyLoop:
    """Drive the whole decision / execution cycle every *interval_seconds*."""

    def __init__(self, live: bool = False) -> None:
        self.live = live
        self.symbol = settings.trading.symbol
        self.kline_interval = "1m"  # Default to 1-minute klines
        
        # Initialize data stores
        self.kline_store = KlineMemoryStore()
        self.orderbook_store = OrderBookMemoryStore()
        self.trade_buffer = TradeBuffer()
        
        # Initialize components
        self.predictor = ModelPredictor()
        self.risk_manager = RiskManager()
        self.feature_calculator = FeatureCalculator()

        # Initialize execution interface
        self.execution = (
            LiveExecution(str(settings.paths.cpp_exec_module_path))
            if live
            else PaperExecution()
        )

        # Initialize WebSocket client
        self.ws_client = BackpackWebSocketClient(
            symbol=self.symbol,
            kline_intervals={self.kline_interval},
            write_to_db=True
        )

    async def _maybe_trade(self) -> None:
        """Core trading logic executed on each iteration."""
        try:
            # Get latest market data
            klines = self.kline_store.get_last_n(
                symbol=self.symbol,
                interval=self.kline_interval,
                n=60  # Last 60 minutes
            )
            
            orderbook = self.orderbook_store.get_snapshot(self.symbol)
            if not orderbook:
                logger.warning("No orderbook data available")
                return

            # Get current mid price
            mid_price = self.orderbook_store.get_mid_price(self.symbol)
            if not mid_price:
                logger.warning("Unable to determine mid price")
                return

            # Calculate features
            features = self.feature_calculator.calculate(
                klines=klines,
                orderbook=orderbook,
                mid_price=mid_price
            )

            # Get prediction
            prediction = self.predictor.predict(features)

            # Check risk limits
            if not self.risk_manager.check_limits(prediction, mid_price):
                logger.info("Risk limits exceeded, skipping trade")
                return

            # Execute trade if conditions met
            if prediction.should_trade:
                order = Order(
                    id=str(uuid.uuid4()),
                    symbol=self.symbol,
                    side=prediction.side,
                    qty=prediction.size,
                    price=None,  # Market order
                    leverage=settings.trading.leverage
                )
                await self.execution.send_order(order)

        except Exception as e:
            logger.error(f"Error in trading loop: {e}", exc_info=True)

    async def run(self, interval_seconds: float = 1.0) -> None:
        """Run the strategy loop."""
        try:
            # Start WebSocket client
            asyncio.create_task(self.ws_client.run())
            
            logger.info(
                f"Starting strategy loop for {self.symbol} "
                f"with {interval_seconds}s interval"
            )
            
            while True:
                await self._maybe_trade()
                await asyncio.sleep(interval_seconds)
                
        except Exception as e:
            logger.error(f"Fatal error in strategy loop: {e}", exc_info=True)
            raise
        finally:
            self.ws_client.close()

    def close(self) -> None:
        """Clean up resources."""
        self.ws_client.close()

async def main() -> None:
    """Main entry point for the strategy."""
    loop = StrategyLoop(live=False)  # Start in paper mode
    await loop.run(interval_seconds=1.0)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    asyncio.run(main()) 