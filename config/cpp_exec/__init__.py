from importlib import import_module
import sys as _sys

_module = import_module("config.cpp_exec")
_sys.modules[__name__] = _module
for _k, _v in list(_sys.modules.items()):
    if _k.startswith("config.cpp_exec"):
        _sys.modules[_k.replace("config.cpp_exec", "cpp_exec", 1)] = _v
del _k, _v, _module, import_module, _sys