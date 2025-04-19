from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from config.settings import settings
from data_ingestion.ws_client import BackpackWebSocketClient
from feature_engineering.calculator import FeatureCalculator
from ml.predictor import ModelPredictor
from risk_management.risk_manager import RiskManager
from .execution_interface import LiveExecution, PaperExecution, Order

logger = logging.getLogger(__name__)


class StrategyLoop:
    """Drive the whole decision / execution cycle every *interval_seconds*."""

    def __init__(self, live: bool = False) -> None:
        self.live = live
        self.ws_client = BackpackWebSocketClient(
            symbol=settings.trading.symbol,
            kline_intervals={"1m"},
            write_to_db=True,
        )
        self.predictor = ModelPredictor()
        self.risk_manager = RiskManager()

        self.execution = (
            LiveExecution(str(settings.paths.cpp_exec_module_path))
            if live
            else PaperExecution()
        )

    # ------------------------------------------------------------------ #
    # Core step
    # ------------------------------------------------------------------ #
    async def _maybe_trade(self) -> None:
        klines = self.ws_client.kline_store.get_last_n(60)
        orderbook = self.ws_client.orderbook_store.get_snapshot()

        # Need data first
        if len(klines) < 60 or orderbook is None:
            return

        # Build features & get probability
        calc = FeatureCalculator()
        feats = calc.calculate_features(orderbook=orderbook, klines=klines)
        prob = self.predictor.predict_proba(feats)
        logger.info(f"Predicted edge={prob:0.3f}")

        if prob < settings.ml.prediction_threshold:
            return

        if self.risk_manager.trading_halted():
            logger.warning("Trading halted by risk manager")
            return

        # Position sizing – simple Kelly‑style scale (placeholder)
        size_usd = self.risk_manager.size_position(
            equity=settings.sizing.initial_equity_usd,
            confidence=prob,
        )
        side = "buy" if prob >= 0.5 else "sell"

        order = Order(
            id=str(uuid.uuid4()),
            symbol=settings.trading.symbol,
            side=side,
            qty=size_usd,        # assume qty expressed in quote currency
            price=None,          # market order
            leverage=settings.sizing.max_leverage,
            timestamp=datetime.utcnow(),
        )
        fill = self.execution.send_order(order)
        self.risk_manager.register_fill(fill)
        logger.info(f"Executed order {fill} – new risk state {self.risk_manager.state}")

    # ------------------------------------------------------------------ #
    # Outer loop
    # ------------------------------------------------------------------ #
    async def run(self) -> None:
        ws_task = asyncio.create_task(self.ws_client.run())

        try:
            step = max(2, settings.strategy_loop.interval_seconds)
            while True:
                await self._maybe_trade()
                await asyncio.sleep(step)
        finally:
            ws_task.cancel()


# --------------------------------------------------------------------------- #
# Entrypoints
# --------------------------------------------------------------------------- #
async def _async_main() -> None:
    loop = StrategyLoop(live=False)  # start in paper‑mode; flip to True for prod
    await loop.run()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s – %(levelname)s – %(name)s – %(message)s",
    )
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()