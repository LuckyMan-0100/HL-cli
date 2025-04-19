from __future__ import annotations

import importlib
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Data‑classes
# --------------------------------------------------------------------------- #
@dataclass
class Order:
    id: str
    symbol: str
    side: str          # "buy" or "sell"
    qty: float
    price: Optional[float]  # None = market order
    leverage: float
    timestamp: datetime = datetime.utcnow()


@dataclass
class Fill:
    order_id: str
    qty: float
    price: float
    fee: float
    timestamp: datetime = datetime.utcnow()


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #
class ExecutionInterface(ABC):
    """Abstract base for any execution back‑end (live or simulated)."""

    @abstractmethod
    def send_order(self, order: Order) -> Fill: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    def get_open_positions(self) -> List[dict]: ...


# --------------------------------------------------------------------------- #
# Live adapter (C++ bridge ‑ thin wrapper)
# --------------------------------------------------------------------------- #
class LiveExecution(ExecutionInterface):
    """Uses the compiled pybind11 bridge (`strategy._cpp_exec`) for <20 ms latency."""

    def __init__(self, lib_path: str | None = None) -> None:
        try:
            # The compiled module is expected to be import‑able as `strategy._cpp_exec`
            # and expose send_order / cancel_order / get_open_positions
            self._bridge = importlib.import_module("strategy._cpp_exec")
            logger.info("C++ execution bridge loaded successfully.")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Compiled C++ bridge not found.  Build it first (see README.md)."
            ) from exc

    # ------------------------------------------------------------------ #
    # API
    # ------------------------------------------------------------------ #
    def send_order(self, order: Order) -> Fill:
        result = self._bridge.send_order(
            order.symbol,
            order.side.upper(),
            order.qty,
            order.price or 0.0,
            order.leverage,
        )
        return Fill(
            order_id=result["id"],
            qty=result["filled_qty"],
            price=result["avg_price"],
            fee=result["fee"],
            timestamp=datetime.utcnow(),
        )

    def cancel_order(self, order_id: str) -> bool:
        return bool(self._bridge.cancel_order(order_id))

    def get_open_positions(self) -> List[dict]:
        return list(self._bridge.get_open_positions())


# --------------------------------------------------------------------------- #
# Paper‑trading adapter (for staging / CI)
# --------------------------------------------------------------------------- #
class PaperExecution(ExecutionInterface):
    """Executes instantly at the given price and stores state in‑memory."""

    def __init__(self) -> None:
        self._positions: List[dict] = []

    def send_order(self, order: Order) -> Fill:
        price = order.price or 0.0
        self._positions.append(
            {
                "id": order.id,
                "symbol": order.symbol,
                "side": order.side,
                "qty": order.qty,
                "price": price,
                "leverage": order.leverage,
            }
        )
        logger.info(f"[PAPER] Executed order {order.id} – qty={order.qty}")
        return Fill(
            order_id=order.id,
            qty=order.qty,
            price=price,
            fee=0.0,
            timestamp=datetime.utcnow(),
        )

    def cancel_order(self, order_id: str) -> bool:
        self._positions = [p for p in self._positions if p["id"] != order_id]
        logger.info(f"[PAPER] Cancelled order {order_id}")
        return True

    def get_open_positions(self) -> List[dict]:
        return self._positions


__all__ = [
    "Order",
    "Fill",
    "ExecutionInterface",
    "LiveExecution",
    "PaperExecution",
]