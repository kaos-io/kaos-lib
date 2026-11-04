"""Where a step runs: the run, app, endpoints and dataset the platform injected, read from the environment only.

Nothing here is hardcoded: when the platform changes what it injects, an older
kaos-lib keeps reading the names below. Every field is None when its variables are unset or empty; ``context()``
never raises.

=================  ==============================================  ==========================================
field              variables (first non-empty wins)                set today by
=================  ==============================================  ==========================================
run_id             KAOS_RUN_ID                                     the enhancer, every step (``workflow.name``)
workflow           KAOS_WORKFLOW_NAME                              the enhancer, every step (names the MLflow run)
app                KAOS_APP, else derived from outputs_repo        outputs_repo ``outputs-<app>``
project            KAOS_PROJECT                                    not injected yet
step               KAOS_STEP, STEP_NAME                            STEP_NAME: Slurm submit pod and job
outputs_repo       OUTPUTS_REPO, CHECKPOINT_BUCKET                 CHECKPOINT_BUCKET every step; OUTPUTS_REPO HPC
lakefs_endpoint    LAKEFS_ENDPOINT, LAKEFS_URL                     the enhancer (in-cluster); public URL on HPC
mlflow_uri         MLFLOW_TRACKING_URI                             the enhancer (in-cluster); public URL on HPC
dataset_ref        KAOS_DATASET_REF, DATASET,                      steps set KAOS_DATASET_REF; DATASET and
                   DATASET_REPO + "@" + DATASET_REF                DATASET_REPO/DATASET_REF in Slurm jobs
dataset_commit     KAOS_DATASET_COMMIT, DATASET_COMMIT             steps / Slurm job
support            verdict of kaos_lib.support.check against       the platform (``KAOS_LIB_SUPPORT``)
                   KAOS_LIB_SUPPORT
slot               KAOS_SLOT_GPUS, KAOS_SLOT_CPUS,                 the Slurm runner, on a shared node;
                   KAOS_SLOT_MEM_GIB, KAOS_SLOT_SHARED             None elsewhere
=================  ==============================================  ==========================================

Every ``KAOS_<X>`` name is also read as ``KUBECORE_<X>`` when it is not set (steps started before the rename).

On a shared Slurm node a step gets one slot: its GPUs, its cores and its memory share
(``slot``). ``usable_cpus()`` is the number of cores a step should size its worker pools by: the slot's,
else the CPUs this process may run on, else the machine's.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from kaos_lib._env import names as _names

ENV = {
    "run_id": _names("RUN_ID"),
    "workflow": _names("WORKFLOW_NAME"),
    "app": _names("APP"),
    "project": _names("PROJECT"),
    "step": _names("STEP") + ("STEP_NAME",),
    "outputs_repo": ("OUTPUTS_REPO", "CHECKPOINT_BUCKET"),
    "lakefs_endpoint": ("LAKEFS_ENDPOINT", "LAKEFS_URL"),
    "mlflow_uri": ("MLFLOW_TRACKING_URI",),
    "dataset_ref": _names("DATASET_REF") + ("DATASET",),
    "dataset_commit": _names("DATASET_COMMIT") + ("DATASET_COMMIT",),
}


@dataclass(frozen=True)
class Slot:
    """This step's share of a shared Slurm node: what it may use, not the whole node."""
    gpus: Optional[int] = None
    cpus: Optional[int] = None
    mem_gib: Optional[int] = None
    shared: bool = False


SLOT_ENV = {"gpus": _names("SLOT_GPUS"), "cpus": _names("SLOT_CPUS"), "mem_gib": _names("SLOT_MEM_GIB"),
            "shared": _names("SLOT_SHARED")}


@dataclass(frozen=True)
class Context:
    """What the platform told this step about where it runs (see the module table)."""
    run_id: Optional[str] = None
    workflow: Optional[str] = None
    app: Optional[str] = None
    project: Optional[str] = None
    step: Optional[str] = None
    outputs_repo: Optional[str] = None
    lakefs_endpoint: Optional[str] = None
    mlflow_uri: Optional[str] = None
    dataset_ref: Optional[str] = None
    dataset_commit: Optional[str] = None
    support: Optional[str] = None
    slot: Optional[Slot] = None


def _first(environ: Mapping, names: tuple) -> Optional[str]:
    for name in names:
        value = (environ.get(name) or "").strip()
        if value:
            return value
    return None


def _app_of(outputs_repo: Optional[str]) -> Optional[str]:
    from .outputs import OUTPUTS_PREFIX
    if outputs_repo and outputs_repo.startswith(OUTPUTS_PREFIX) and len(outputs_repo) > len(OUTPUTS_PREFIX):
        return outputs_repo[len(OUTPUTS_PREFIX):]
    return None


def _support(environ: Mapping) -> Optional[str]:
    from . import __version__, support
    raw = environ.get(support.ENV)
    return support.check(__version__, raw)["verdict"] if raw else None


def _int(environ: Mapping, names: tuple) -> Optional[int]:
    value = _first(environ, names) or ""
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _slot(environ: Mapping) -> Optional[Slot]:
    """The slot the Slurm runner set, or None when none was set (in-cluster, a node of its own)."""
    values = {k: _int(environ, v) for k, v in SLOT_ENV.items() if k != "shared"}
    if not any(v is not None for v in values.values()):
        return None
    return Slot(**values, shared=_first(environ, SLOT_ENV["shared"]) == "1")


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
    values = {name: _first(env, names) for name, names in ENV.items()}
    values["app"] = values["app"] or _app_of(values["outputs_repo"])
    if not values["dataset_ref"]:
        repo, ref = _first(env, ("DATASET_REPO",)), _first(env, ("DATASET_REF",))
        values["dataset_ref"] = f"{repo}@{ref}" if repo and ref else None
    return Context(**values, support=_support(env), slot=_slot(env))


def run_id(environ: Optional[Mapping] = None) -> Optional[str]:
    """The platform's run id (``$KAOS_RUN_ID``), or None outside a pipeline run."""
    return _first(os.environ if environ is None else environ, ENV["run_id"])
