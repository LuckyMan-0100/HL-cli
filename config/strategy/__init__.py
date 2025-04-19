"""Strategy package – run `python -m strategy` to launch the main loop."""
from .main_loop import main as run   # noqa: F401

__all__ = ["run"]