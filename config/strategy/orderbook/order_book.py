from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class BookLevel:
    price: float
    qty: float


class OrderBook:
    """
    Extremely small L1 order‑book cache (best bid / ask only).

    Extend to full depth or aggregate buckets when ready.
    """

    def __init__(self) -> None:
        self.best_bid: BookLevel | None = None
        self.best_ask: BookLevel | None = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def update_snapshot(self, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]) -> None:
        """
        Accept full snapshot arrays ``[(price, qty), …]`` (descending for bids,
        ascending for asks) and retain the top of book.
        """
        self.best_bid = BookLevel(*bids[0]) if bids else None
        self.best_ask = BookLevel(*asks[0]) if asks else None

    def update_l2(self, side: str, price: float, qty: float) -> None:
        """
        Incremental depth‑2 (price‑level) update. Only top‑of‑book relevance is
        tracked to keep it simple.
        """
        if side.upper() == "BID":
            if (self.best_bid is None) or price > self.best_bid.price:
                self.best_bid = BookLevel(price, qty)
        else:
            if (self.best_ask is None) or price < self.best_ask.price:
                self.best_ask = BookLevel(price, qty)

    # ------------------------------------------------------------------ #
    # Convenience
    # ------------------------------------------------------------------ #
    def mid_price(self) -> float | None:
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2
        return None

    def spread(self) -> float | None:
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None