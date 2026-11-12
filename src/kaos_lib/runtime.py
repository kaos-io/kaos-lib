"""Where a step runs: the run, the app, the step and the endpoints the platform gave it.

The run, app, project, step, kind and experiment come from the step context, the one value the platform hands a
pipeline step (``$KAOS_STEP_CONTEXT``, read in full by ``kaos_lib.step``). The endpoints, the support verdict and
the slot come from the environment. Every field is None when it was not given; ``context()`` never raises, so it
is safe on a laptop. ``kaos_lib.step.start()`` is the call that refuses a missing or malformed context.

=================  =====================================================  =====================================
field              source                                                 None when
=================  =====================================================  =====================================
run_id             the step context (``run``)                             not a pipeline step
app                the step context                                       not a pipeline step
project            the step context                                       not a pipeline step
step               the step context                                       not a pipeline step
kind               the step context                                       not a pipeline step
experiment         the step context                                       not a pipeline step
outputs_repo       ``outputs-<app>``                                      not a pipeline step
lakefs_endpoint    ``LAKEFS_ENDPOINT``, else ``LAKEFS_URL``               unset
mlflow_uri         ``MLFLOW_TRACKING_URI``                                unset
support            verdict of ``kaos_lib.support.check`` against          ``KAOS_LIB_SUPPORT`` unset
                   ``KAOS_LIB_SUPPORT``
slot               ``KUBECORE_SLOT_GPUS``, ``KUBECORE_SLOT_CPUS``,        the step has a node of its own
                   ``KUBECORE_SLOT_MEM_GIB``, ``KUBECORE_SLOT_SHARED``
=================  =====================================================  =====================================

On a shared HPC (Slurm) node a step gets one slot: its GPUs, its cores and its memory share
(``slot``). ``usable_cpus()`` is the number of cores a step should size its worker pools by: the slot's,
else the CPUs this process may run on, else the machine's.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Mapping, Optional

STEP_CONTEXT_ENV = "KAOS_STEP_CONTEXT"
FROM_CONTEXT = {"run_id": "run", "app": "app", "project": "project", "step": "step", "kind": "kind",
                "experiment": "experiment"}
ENV = {
    "lakefs_endpoint": ("LAKEFS_ENDPOINT", "LAKEFS_URL"),
    "mlflow_uri": ("MLFLOW_TRACKING_URI",),
}


@dataclass(frozen=True)
class Slot:
    """This step's share of a shared HPC (Slurm) node: what it may use, not the whole node."""
    gpus: Optional[int] = None
    cpus: Optional[int] = None
    mem_gib: Optional[int] = None
    shared: bool = False


SLOT_ENV = {"gpus": "KUBECORE_SLOT_GPUS", "cpus": "KUBECORE_SLOT_CPUS", "mem_gib": "KUBECORE_SLOT_MEM_GIB",
            "shared": "KUBECORE_SLOT_SHARED"}


@dataclass(frozen=True)
class Context:
    """What the platform told this step about where it runs (see the module table)."""
    run_id: Optional[str] = None
    app: Optional[str] = None
    project: Optional[str] = None
    step: Optional[str] = None
    kind: Optional[str] = None
    experiment: Optional[str] = None
    lakefs_endpoint: Optional[str] = None
    mlflow_uri: Optional[str] = None
    support: Optional[str] = None
    slot: Optional[Slot] = None

    @property
    def outputs_repo(self) -> Optional[str]:
        """The app's outputs repository, ``outputs-<app>``."""
        return f"outputs-{self.app}" if self.app else None


def _first(environ: Mapping, names: tuple) -> Optional[str]:
    for name in names:
        value = (environ.get(name) or "").strip()
        if value:
            return value
    return None


def _step_context(environ: Mapping) -> dict:
    """The step context as far as it can be read: {} when it is unset or not a JSON object."""
    try:
        value = json.loads(environ.get(STEP_CONTEXT_ENV) or "")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def checkpoint_every_minutes(environ: Optional[Mapping] = None) -> Optional[int]:
    """Minutes between the step's periodic checkpoints as the run form set them (``checkpoint_every`` of the step
    context), or None when the step declares no interval or this is not a pipeline step."""
    value = _step_context(os.environ if environ is None else environ).get("checkpoint_every")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _support(environ: Mapping) -> Optional[str]:
    from . import __version__, support
    raw = environ.get(support.ENV)
    return support.check(__version__, raw)["verdict"] if raw else None


def _int(environ: Mapping, name: str) -> Optional[int]:
    value = (environ.get(name) or "").strip()
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _slot(environ: Mapping) -> Optional[Slot]:
    """The slot the platform set, or None when none was set (a node of its own)."""
    values = {k: _int(environ, v) for k, v in SLOT_ENV.items() if k != "shared"}
    if not any(v is not None for v in values.values()):
        return None
    return Slot(**values, shared=(environ.get(SLOT_ENV["shared"]) or "").strip() == "1")


def usable_cpus(environ: Optional[Mapping] = None) -> int:
    """The cores this step should size worker pools by: its slot's (shared Slurm node), else the CPUs this
    process may run on (the scheduler's binding), else the machine's. ``os.cpu_count()`` alone sees every
    core of a shared node, so data loaders sized by it overrun the step's share."""
    slot = _slot(os.environ if environ is None else environ)
    if slot and slot.cpus:
        return slot.cpus
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def context(environ: Optional[Mapping] = None) -> Context:
    """The step's context from ``environ`` (default ``os.environ``); missing values are None."""
    env = os.environ if environ is None else environ
    given = _step_context(env)
    values = {name: (given.get(key) if isinstance(given.get(key), str) and given.get(key) else None)
              for name, key in FROM_CONTEXT.items()}
    values.update({name: _first(env, names) for name, names in ENV.items()})
    return Context(**values, support=_support(env), slot=_slot(env))


def run_id(environ: Optional[Mapping] = None) -> Optional[str]:
    """The run's name, or None outside a pipeline run."""
    return context(environ).run_id
