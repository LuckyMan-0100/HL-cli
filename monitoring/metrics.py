"""
Prometheus metrics helpers for HL-cli.

Exposes a convenience ``start_metrics_server`` that binds the first available
port starting at the requested one, avoiding "Address already in use" errors.
"""

from __future__ import annotations

import errno
import logging
from typing import Optional

from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)

# Example default metrics – extend/replace as your project evolves.
REQUEST_COUNTER = Counter(
    "hl_requests_total",
    "Total number of requests processed by the application",
)
LATENCY_HISTOGRAM = Histogram(
    "hl_request_latency_seconds",
    "Latency of processed requests in seconds",
)
LAST_QUOTE_TS = Gauge(
    "hl_last_quote_timestamp",
    "Unix timestamp of the most recent quote received",
)

# --- Additional metrics expected by monitoring.__init__ ---
risk_limit_breaches = Counter(
    "hl_risk_limit_breaches_total",
    "Total number of times risk limits were breached across all strategies",
)

drawdown_gauge = Gauge(
    "hl_drawdown_ratio",
    "Current drawdown as a fraction of account equity (0–1)",
)

circuit_breaker_trips = Counter(
    "hl_circuit_breaker_trips_total",
    "Total number of circuit-breaker triggers during trading",
)

# --- Additional PnL metric ---
TOTAL_PNL = Gauge(
    "hl_total_pnl",
    "Current cumulative profit and loss of the trading strategy",
)

def start_metrics_server(port: int = 8000, *, max_attempts: int = 10) -> int:
    """
    Start the Prometheus metrics HTTP endpoint.

    Parameters
    ----------
    port
        Preferred TCP port to bind.
    max_attempts
        How many successive ports to try if the preferred one is busy.

    Returns
    -------
    int
        The port number the server was actually bound to.

    Raises
    ------
    RuntimeError
        If no free port could be found within *max_attempts* trials.
    """
    for offset in range(max_attempts):
        candidate = port + offset
        try:
            start_http_server(candidate)
            logger.info("Prometheus metrics server listening on port %s", candidate)
            return candidate
        except OSError as exc:  # pragma: no cover – depends on host OS
            # EADDRINUSE: 98 on Linux, 48 on macOS
            if exc.errno in (errno.EADDRINUSE, 98, 48):
                logger.warning(
                    "Port %s already in use – trying port %s", candidate, candidate + 1
                )
                continue
            raise
    raise RuntimeError(
        f"Unable to start metrics server on any port in range "
        f"[{port}, {port + max_attempts - 1}]"
    )