from importlib import import_module
import sys as _sys

_module = import_module("config.risk_management")
_sys.modules[__name__] = _module
for _k, _v in list(_sys.modules.items()):
    if _k.startswith("config.risk_management"):
        _sys.modules[_k.replace("config.risk_management", "risk_management", 1)] = _v
del _k, _v, _module, import_module, _sys