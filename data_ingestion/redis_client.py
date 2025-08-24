"""
Asynchronous client for receiving top-of-book (L1) quotes from Redis.

Supports two wire formats
1. *bookTicker* – already contains ``bidPrice`` / ``askPrice`` …
2. *depth*      – ``bids`` / ``asks`` arrays, from which we derive best bid/ask

After normalisation every internal quote dict has **REQUIRED_FIELDS**.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, List, Optional
import os

import redis.asyncio as redis

# --------------------------------------------------------------------------- #
# Configuration constants
# --------------------------------------------------------------------------- #
DEFAULT_HOST: str = "localhost"
DEFAULT_PORT: int = 6969
DEFAULT_DB:   int = 0

MAIN_CHANNEL   = "l1:quotes"
TEST_CHANNEL   = "l1:test"

RECONNECT_DELAY: float = 1.0          # seconds between reconnect attempts
MAX_RECONNECT_ATTEMPTS: int = 5
STALE_THRESHOLD_SEC: float = 5.0      # quote considered stale after N seconds

REQUIRED_FIELDS = {
    "bidPrice", "askPrice",
    "bidQty",   "askQty",
    "timestamp",
}
# --------------------------------------------------------------------------- #

logger = logging.getLogger(__name__)


class RedisQuoteClient:
    """High-level quote source used by the trading strategy."""

    # --------------------------------------------------------------------- #
    # Construction / connection helpers
    # --------------------------------------------------------------------- #
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        db: int = DEFAULT_DB,
        *,
        channel: str = MAIN_CHANNEL,
        test_channel: str = TEST_CHANNEL,
        symbol: str = os.getenv("TRADING_SYMBOL", "WIF_USDC_PERP"),
        test_mode: bool = False,
    ) -> None:
        self.host             = host
        self.port             = port
        self.db               = db
        self.channel          = channel
        self.test_channel     = test_channel
        self.symbol           = symbol
        self.test_mode        = test_mode

        self.redis: Optional[redis.Redis]         = None
        self.pubsub: Optional[redis.client.PubSub] = None
        self._listen_task: Optional[asyncio.Task] = None

        # Mutable state populated by listener
        self.best_bid: Decimal = Decimal("0")
        self.best_ask: Decimal = Decimal("0")
        self.last_update_us: int = 0              # micro-seconds unix epoch
        self._last_heartbeat: datetime = datetime.utcnow()
        self._has_data_evt: asyncio.Event = asyncio.Event()

        self._stop = False
        logger.info(
            "RedisQuoteClient initialised – host=%s port=%s channel=%s test_channel=%s",
            host, port, channel, test_channel,
        )

    # ..................................................................... #
    async def connect(self) -> bool:
        """Establish Redis connection and subscribe; starts background listener."""
        try:
            self.redis = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                decode_responses=True,
            )
            # Basic ping to verify connectivity (raises on failure)
            await self.redis.ping()

            self.pubsub = self.redis.pubsub()
            await self.pubsub.subscribe(self.channel, self.test_channel)

            # Spawn listener once
            if self._listen_task is None or self._listen_task.done():
                self._listen_task = asyncio.create_task(self._listen_loop())

            logger.info(
                "Connected to Redis @ %s:%s – subscribed to %s + %s",
                self.host, self.port, self.channel, self.test_channel,
            )

            return True

        except Exception as exc:
            logger.error("Redis connect failed: %s", exc, exc_info=False)
            await self._cleanup()
            return False

    async def _ensure_connected(self) -> bool:
        """(Re)connect if needed, with exponential back-off."""
        attempts = 0
        while attempts < MAX_RECONNECT_ATTEMPTS:
            if self.redis and self.pubsub:
                try:
                    await self.redis.ping()
                    return True
                except (redis.ConnectionError, redis.TimeoutError):
                    # fall through to reconnect
                    pass

            if await self.connect():
                return True

            attempts += 1
            await asyncio.sleep(RECONNECT_DELAY * (2 ** attempts))

        logger.error("Exceeded maximum Redis reconnect attempts")
        return False

    # --------------------------------------------------------------------- #
    # Public API used by strategy
    # --------------------------------------------------------------------- #
    async def wait_for_data(self, timeout: float = 15.0) -> bool:
        """Block until the first valid quote is received (or timeout)."""
        if not await self._ensure_connected():
            return False
        try:
            await asyncio.wait_for(self._has_data_evt.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for initial quote")
            return False

    async def get_quote(self) -> Dict[str, Decimal]:
        """Return latest bid/ask; returns zeroes if stale / unavailable."""
        if (datetime.utcnow() - self._last_heartbeat).total_seconds() > STALE_THRESHOLD_SEC:
            logger.warning("Quote data is stale (> %ss)", STALE_THRESHOLD_SEC)
            return {k: Decimal("0") for k in ("bidPrice", "askPrice", "bidQty", "askQty")}

        return {
            "bidPrice": self.best_bid,
            "askPrice": self.best_ask,
            "bidQty":   Decimal("1"),   # size not stored – supply dummy ≥ 0
            "askQty":   Decimal("1"),
        }

    async def close(self) -> None:
        """Stop listener and close network resources."""
        self._stop = True
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        await self._cleanup()
        logger.info("RedisQuoteClient closed")

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #
    async def _listen_loop(self) -> None:
        """Background consumer; normalises + validates messages."""
        logger.info("Quote listener started (%s)", "test mode" if self.test_mode else "live mode")
        while not self._stop:
            try:
                if not await self._ensure_connected():
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue

                msg = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not msg:
                    continue
                if msg["type"] != "message":
                    continue

                raw = msg["data"]
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    logger.debug("Discarded non-JSON payload: %s", raw)
                    continue

                if not self._normalise_and_validate(data):
                    # invalid message already logged
                    continue

                # --- Store latest quote ---
                self.best_bid = Decimal(str(data["bidPrice"]))
                self.best_ask = Decimal(str(data["askPrice"]))
                self.last_update_us = int(data["timestamp"])
                self._last_heartbeat = datetime.utcnow()
                self._has_data_evt.set()

            except (redis.ConnectionError, redis.TimeoutError) as exc:
                logger.error("Redis connection lost: %s", exc)
                await asyncio.sleep(RECONNECT_DELAY)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Unexpected error in listener: %s", exc)
                await asyncio.sleep(0.1)

    # ..................................................................... #
    def _normalise_and_validate(self, data: Dict) -> bool:
        """Return *True* if ``data`` represents a sane quote for *self.symbol*."""
        # Convert depth snapshot → top-of-book
        if "bids" in data and "asks" in data:
            try:
                bid_p, bid_q = data["bids"][0]
                ask_p, ask_q = data["asks"][0]
                data.update(
                    bidPrice=str(bid_p),
                    askPrice=str(ask_p),
                    bidQty=str(bid_q),
                    askQty=str(ask_q),
                )
                data.setdefault(
                    "timestamp", int(datetime.utcnow().timestamp() * 1_000_000)
                )
            except Exception as exc:
                logger.debug("Malformed depth message skipped: %s (%s)", data, exc)
                return False

        # Mandatory keys
        if not REQUIRED_FIELDS.issubset(data):
            logger.debug("Missing fields: %s – %s",
                         REQUIRED_FIELDS - set(data), data)
            return False

        # Instrument check
        if data.get("symbol") and data["symbol"] != self.symbol:
            return False

        # Numeric sanity
        try:
            bid_price = Decimal(str(data["bidPrice"]))
            ask_price = Decimal(str(data["askPrice"]))
            bid_qty   = Decimal(str(data["bidQty"]))
            ask_qty   = Decimal(str(data["askQty"]))
        except (InvalidOperation, TypeError, ValueError):
            logger.debug("Non-numeric values in quote: %s", data)
            return False

        if min(bid_price, ask_price, bid_qty, ask_qty) <= 0:
            return False
        if bid_price >= ask_price:
            logger.debug("Crossed book (bid ≥ ask) %s", data)
            return False

        # Timestamp sanity (ignore if clearly in the future)
        try:
            ts = int(data["timestamp"])
            now_us = int(datetime.utcnow().timestamp() * 1_000_000)
            if ts > now_us + 1_000_000 or ts <= 0:
                logger.debug("Suspicious timestamp %s (now=%s)", ts, now_us)
                return False
        except Exception:
            return False

        return True

    # ..................................................................... #
    async def _cleanup(self) -> None:
        """Close Redis connections without raising."""
        try:
            if self.pubsub:
                await self.pubsub.close()
        except Exception:
            pass
        try:
            if self.redis:
                await self.redis.close()
        except Exception:
            pass