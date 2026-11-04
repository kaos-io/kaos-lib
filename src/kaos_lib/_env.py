"""Platform environment variables: ``KAOS_<X>``, with the older ``KUBECORE_<X>`` as a fallback.

Steps started before the rename carry only the ``KUBECORE_`` names; ``KAOS_`` wins when both are set.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

PREFIXES = ("KAOS_", "KUBECORE_")  # the second is the deprecated alias


def names(suffix: str) -> tuple:
    """Both spellings of ``suffix``, preferred first."""
    return tuple(p + suffix for p in PREFIXES)


def get(suffix: str, environ: Optional[Mapping] = None, default: Optional[str] = None) -> Optional[str]:
    """The value of ``KAOS_<suffix>``, else ``KUBECORE_<suffix>`` (empty counts as unset), else ``default``."""
    env = os.environ if environ is None else environ
    for name in names(suffix):
        if env.get(name):
            return env[name]
    return default
