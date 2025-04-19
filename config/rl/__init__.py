"""
Namespace shim – exposes ``config.rl`` as top‑level package ``rl`` so imports
like ``import rl.environment`` work regardless of the physical layout.
"""
from importlib import import_module
import sys as _sys

_module = import_module("config.rl")
_sys.modules[__name__] = _module        # register alias
# expose sub‑modules under the new namespace
for _k, _v in list(_sys.modules.items()):
    if _k.startswith("config.rl"):
        _sys.modules[_k.replace("config.rl", "rl", 1)] = _v
del _k, _v, _module, import_module, _sys