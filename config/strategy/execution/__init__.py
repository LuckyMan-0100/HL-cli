"""
Execution adapter sub‑package.

Usage
-----
>>> from strategy.execution import LiveExecution
"""
from ..execution_interface import ExecutionInterface, LiveExecution  # type: ignore

__all__ = ["ExecutionInterface", "LiveExecution"]