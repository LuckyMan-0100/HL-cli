#!/usr/bin/env python3
"""Listen on Redis channel 'exec:fills' for JSON-encoded fill events coming
from the C++ execution bridge and persist them to Postgres via
src.data.db_writer.PostgresWriter.

The script is launched by run_paper_trading.py and runs until SIGTERM.
"""

import json
import logging
import os
import signal
import sys
import time
import uuid

import redis
from decimal import Decimal
from datetime import datetime

# Ensure project root is on sys.path so we can import src.*
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from src.data.db_writer import PostgresWriter
from src.data.memory_store import Trade  # reuse existing dataclass
from config.settings import settings

logger = logging.getLogger("fill_persistor")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

RUNNING = True


def handle_shutdown(signum, frame):
    global RUNNING
    logger.info("Received signal %s – shutting down fill persistor", signum)
    RUNNING = False


for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, handle_shutdown)


REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_OUTPUT_PORT", os.getenv("REDIS_PORT", "6379")))
CHANNEL = "exec:fills"

logger.info("Connecting to Redis %s:%s channel '%s'", REDIS_HOST, REDIS_PORT, CHANNEL)
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
    socket_keepalive=True,
    health_check_interval=30  # prevent 600s idle timeout
)
pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
pubsub.subscribe(CHANNEL)

writer = PostgresWriter()


def persist_event(event_json: str):
    try:
        j = json.loads(event_json)
    except json.JSONDecodeError:
        logger.warning("Malformed JSON received – skipping: %s", event_json[:100])
        return

    required = ("event_timestamp", "trading_symbol", "side", "price", "filled_quantity")
    if not all(k in j for k in required):
        logger.debug("JSON missing required keys – skipping: %s", j)
        return

    trade = Trade(
        timestamp=datetime.fromtimestamp(int(j["event_timestamp"]) / 1000),
        symbol=j["trading_symbol"],
        side=j["side"].lower(),
        price=Decimal(str(j["price"])),
        size=Decimal(str(j["filled_quantity"])),
        fee=Decimal("0"),
        total_value=Decimal(str(j["price"])) * Decimal(str(j["filled_quantity"])),
        status=j.get("event_type", "FILLED"),
        trade_id=j.get("trade_id", str(uuid.uuid4()))
    )
    try:
        writer.write_trade(trade)
        logger.info("Persisted fill %s %s @ %s (qty %s)", trade.symbol, trade.side, trade.price, trade.size)
    except Exception as e:
        logger.error("Failed to write trade to DB: %s", e, exc_info=True)


logger.info("Fill persistor started – waiting for messages…")
while RUNNING:
    message = pubsub.get_message(timeout=1.0)
    if message and message["type"] == "message":
        persist_event(message["data"])
    time.sleep(0.01)

logger.info("Fill persistor stopped.") 