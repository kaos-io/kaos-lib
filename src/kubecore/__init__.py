"""Deprecated: the ``kubecore`` package is now ``kaos_lib`` (distribution ``kaos-lib``).

This shim keeps ``import kubecore`` and ``from kubecore import datasets`` working for one release.
``kubecore.<module>`` is the very module object ``kaos_lib.<module>``, so state and patches are shared.
"""
import importlib
import pkgutil
import sys
import warnings

import kaos_lib
from kaos_lib import __version__  # noqa: F401

warnings.warn("the kubecore package is now kaos_lib (pip install kaos-lib): import kaos_lib instead; "
              "the kubecore name goes away in the next release", DeprecationWarning, stacklevel=2)

for _info in pkgutil.walk_packages(kaos_lib.__path__, "kaos_lib."):
    _module = importlib.import_module(_info.name)
    sys.modules["kubecore" + _info.name[len("kaos_lib"):]] = _module
    if _info.name.count(".") == 1:
        globals()[_info.name.split(".")[1]] = _module
