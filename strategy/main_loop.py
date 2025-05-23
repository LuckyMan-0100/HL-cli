"""
Main trading loop that orchestrates the strategy execution.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any
import uuid
import pandas as pd
import numpy as np

from config.settings import settings
from data_ingestion.memory_store import KlineMemoryStore, OrderBookMemoryStore, TradeBuffer, Kline, OrderBook
from data_ingestion.redis_client import RedisQuoteClient
from feature_engineering.calculator import FeatureCalculator
from feature_engineering.feature_monitor import FeatureMonitor
from ml.inference.predictor import ModelPredictor
from ml.monitoring.performance_monitor import PerformanceMonitor
from risk_management.risk_manager import RiskManager
from .execution_interface import LiveExecution, PaperExecution, Order
from monitoring.metrics import start_metrics_server, TOTAL_PNL

logger = logging.getLogger(__name__)

MAX_REDIS_CONNECT_ATTEMPTS = 5
REDIS_CONNECT_TIMEOUT = 30  # seconds

def klines_to_dataframe(klines: List[Kline]) -> pd.DataFrame:
    """Convert a list of Kline objects to a pandas DataFrame."""
    if not klines:
        return pd.DataFrame()
        
    data = {
        'timestamp': [k.timestamp for k in klines],
        'open': [float(k.open) for k in klines],
        'high': [float(k.high) for k in klines],
        'low': [float(k.low) for k in klines],
        'close': [float(k.close) for k in klines],
        'volume': [float(k.volume) for k in klines],
        'quote_volume': [float(k.quote_volume) for k in klines]
    }
    
    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df

def orderbook_to_dataframe(ob: OrderBook) -> pd.DataFrame:
    """Convert an OrderBook dataclass to a pandas DataFrame for features."""
    if ob is None:
        return pd.DataFrame(columns=["side", "price", "quantity"])
    data = {"side": [], "price": [], "quantity": []}
    for lvl in ob.bids:
        data["side"].append("bid")
        data["price"].append(float(lvl.price))
        data["quantity"].append(float(lvl.quantity))
    for lvl in ob.asks:
        data["side"].append("ask")
        data["price"].append(float(lvl.price))
        data["quantity"].append(float(lvl.quantity))
    return pd.DataFrame(data)

class StrategyLoop:
    """Drive the whole decision / execution cycle every *interval_seconds*."""

    def __init__(self, live: bool = False, ml_predictor: Optional[ModelPredictor] = None) -> None:
        self.live = live
        self.symbol = settings.trading.symbol
        self.kline_interval = "1m"  # Default to 1-minute klines
        
        # Initialize data stores
        self.kline_store = KlineMemoryStore()
        self.orderbook_store = OrderBookMemoryStore()
        self.trade_buffer = TradeBuffer()
        
        # Initialize Redis client for L1 quotes
        self.quote_client = RedisQuoteClient()
        self._last_quote_warning = datetime.min
        self._quote_warning_interval = timedelta(minutes=1)
        self._listener_task: Optional[asyncio.Task] = None
        
        # Initialize ML predictor if provided
        self.ml_predictor = ml_predictor
        self.use_ml = ml_predictor is not None
        
        # Initialize model for baseline strategy if ML not enabled
        if not self.use_ml:
            self.predictor = ModelPredictor()
        else:
            self.predictor = None
        
        # Initialize components
        self.risk_manager = RiskManager()
        self.feature_calculator = FeatureCalculator()
        
        # Define feature names based on what we calculate
        self.feature_names = [
            # L2 features
            'spread', 'spread_bps',
            'vol_imb_L1', 'vol_imb_L3', 'vol_imb_L5',
            'bid_impact_1k', 'ask_impact_1k',
            'bid_concentration', 'ask_concentration',
            # Price features
            'rsi', 'macd', 'bb_upper', 'bb_lower', 'atr',
            'ret_1m', 'ret_5m', 'vol_1m',
            # Microstructure features
            'bid_depth', 'ask_depth'
        ]
        
        # Initialize monitoring
        self.feature_monitor = FeatureMonitor(
            feature_names=self.feature_names,
            min_samples=100,  # Require 100 samples before computing baseline
            std_epsilon=1e-6  # Small value to prevent division by zero
        )
        self.performance_monitor = PerformanceMonitor(
            feature_names=self.feature_names
        )
        
        # Additional ML-specific metrics
        if self.use_ml:
            self.ml_metrics = PerformanceMonitor(
                feature_names=self.ml_predictor.features_used,
                metrics_dir="logs/ml_metrics"
            )

        # Initialize execution interface (inject quote_client into paper execution)
        self.execution = (
            LiveExecution(str(settings.paths.cpp_exec_module_path))
            if live
            else PaperExecution(self.quote_client)
        )

    async def _ensure_redis_connection(self) -> bool:
        """Ensure Redis connection is established."""
        for attempt in range(MAX_REDIS_CONNECT_ATTEMPTS):
            try:
                if await self.quote_client.connect():
                    if not self._listener_task or self._listener_task.done():
                        self._listener_task = asyncio.create_task(self.quote_client.listen())
                    return True
            except Exception as e:
                logger.warning(f"Redis connection attempt {attempt + 1} failed: {e}")
                if attempt < MAX_REDIS_CONNECT_ATTEMPTS - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                
        logger.error(f"Failed to connect to Redis after {MAX_REDIS_CONNECT_ATTEMPTS} attempts")
        return False

    async def _maybe_trade(self) -> None:
        """Core trading logic executed on each iteration."""
        now_ts = datetime.now()

        # Get latest quote
        quote = await self.quote_client.get_quote()
        logger.debug(f"Received quote: {quote}")
        if not quote or quote['bidPrice'] == 0 or quote['askPrice'] == 0:
            if (now_ts - self._last_quote_warning) > self._quote_warning_interval:
                logger.warning("No valid quote data available")
                self._last_quote_warning = now_ts
            return

        # Get latest klines and orderbook
        # Fetch last 100 klines from in-memory store and convert to DataFrame
        klines = self.kline_store.get_last_n(self.symbol, self.kline_interval, 100)
        klines_df = klines_to_dataframe(klines)
        # Fetch latest order book snapshot and convert to DataFrame
        snapshot = self.orderbook_store.get_snapshot(self.symbol)
        orderbook_df = orderbook_to_dataframe(snapshot)

        # Calculate features
        try:
            features = self.feature_calculator.calculate(
                klines=klines_df,
                orderbook=orderbook_df,
                mid_price=float((quote['bidPrice'] + quote['askPrice']) / 2)
            )
        except Exception as e:
            logger.error(f"Error calculating features: {e}")
            return
        
        if not features:
            logger.warning("No features calculated")
            return
        
        # Check feature drift
        has_drift = self.feature_monitor.check_feature_drift(features)
        if has_drift:
            logger.warning("Significant feature drift detected")
            return

        # Get prediction based on strategy (ML or baseline)
        pred_start = datetime.now()
        if self.use_ml:
            # Use ML model for prediction
            prediction = self.ml_predictor.predict(features)
            # Record ML-specific metrics
            pred_time = (datetime.now() - pred_start).total_seconds() * 1000
            self.ml_metrics.record_prediction(
                timestamp=now_ts,
                features=features,
                prediction=prediction,
                latency_ms=pred_time
            )
        else:
            # Use baseline strategy
            prediction = self.predictor.predict(features)
            
        # Calculate prediction time
        pred_time = (datetime.now() - pred_start).total_seconds() * 1000
        
        # Update performance monitoring
        self.performance_monitor.record_prediction(
            timestamp=now_ts,
            features=features,
            prediction=prediction,
            latency_ms=pred_time
        )
        
        # Execute trading logic based on prediction
        if prediction.should_trade:
            # Check risk limits before placing order (use signal and price)
            price = float(quote['askPrice'] if prediction.side == "buy" else quote['bidPrice'])
            if not self.risk_manager.check_limits(prediction.signal, price):
                logger.warning(f"Risk limits exceeded for {prediction.side} {prediction.size} {self.symbol}")
                return
                
            # Place order
            order = Order(
                id=str(uuid.uuid4()),
                symbol=self.symbol,
                side=prediction.side,
                qty=prediction.size,
                price=float(quote['askPrice'] if prediction.side == "buy" else quote['bidPrice']),
                timestamp=now_ts
            )
            
            # Send order and handle fill
            fill = await self.execution.send_order(order)
            if fill:
                # Record the trade in performance monitor
                self.performance_monitor.record_trade(
                    timestamp=now_ts,
                    fill=fill,
                    prediction=prediction
                )
                # Update Prometheus gauge for total PnL (profit minus loss)
                current_pnl = self.performance_monitor.total_profit - self.performance_monitor.total_loss
                TOTAL_PNL.set(current_pnl)
                
                # Update PnL tracking in ML predictor if using ML
                if self.use_ml and hasattr(fill, 'pnl'):
                    self.ml_predictor.update_pnl(fill.pnl)
                    
                    # Also record in ML metrics
                    self.ml_metrics.record_trade(
                        timestamp=now_ts,
                        fill=fill,
                        prediction=prediction
                    )
        
        # Calculate and log execution time
        exec_time = (datetime.now() - now_ts).total_seconds() * 1000
        logger.info(f"Trading loop execution time: {exec_time:.2f}ms")

    async def run(self, interval_seconds: float = 1.0) -> None:
        """Run the trading loop with specified interval."""
        try:
            # Log which strategy we're using
            if self.use_ml:
                logger.info(f"Using ML-based strategy with model: {self.ml_predictor.model_path}")
            else:
                logger.info("Using baseline strategy")
                
            # Connect to Redis and wait for initial data
            connected = await self.quote_client.connect()
            if not connected:
                logger.error("Failed to establish Redis connection")
                return
                
            # Start Redis listener task
            self._listener_task = asyncio.create_task(self.quote_client.listen())
            
            # Wait for initial quote data
            if not await self.quote_client.wait_for_data(timeout=15.0):
                logger.error("Failed to receive initial quote data")
                return
                
            logger.info("Received initial quote data, starting trading loop")
            
            while True:
                await self._maybe_trade()
                await asyncio.sleep(interval_seconds)
                
        except asyncio.CancelledError:
            logger.info("Trading loop cancelled")
            if self._listener_task:
                self._listener_task.cancel()
                try:
                    await self._listener_task
                except asyncio.CancelledError:
                    pass
            await self.quote_client.close()
            self.performance_monitor.close()
            if self.use_ml:
                self.ml_metrics.close()
        except Exception as e:
            logger.error(f"Fatal error in trading loop: {e}", exc_info=True)
            raise

    def close(self) -> None:
        """Clean up resources."""
        if self._listener_task:
            self._listener_task.cancel()
        asyncio.create_task(self.quote_client.close())

async def main() -> None:
    """Main entry point for the strategy."""
    loop = StrategyLoop(live=False)  # Start in paper mode
    await loop.run(interval_seconds=1.0)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )
    asyncio.run(main()) 