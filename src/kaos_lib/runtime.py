"""Where a step runs: the run, app, endpoints and dataset the platform injected, read from the environment only.

Nothing here is hardcoded: when the platform changes what it injects, an older
kaos-lib keeps reading the names below. Every field is None when its variables are unset or empty; ``context()``
never raises.

=================  ==============================================  ==========================================
field              variables (first non-empty wins)                set today by
=================  ==============================================  ==========================================
run_id             KUBECORE_RUN_ID                                 the platform, every step (``workflow.name``)
workflow           KUBECORE_WORKFLOW_NAME                          the platform, every step (names the MLflow run)
app                KUBECORE_APP, else derived from outputs_repo    outputs_repo ``outputs-<app>``
project            KUBECORE_PROJECT                                not injected yet
step               KUBECORE_STEP, STEP_NAME                        STEP_NAME: HPC (Slurm) jobs
outputs_repo       OUTPUTS_REPO, CHECKPOINT_BUCKET                 CHECKPOINT_BUCKET every step; OUTPUTS_REPO HPC
lakefs_endpoint    LAKEFS_ENDPOINT, LAKEFS_URL                     the platform (the public URL on HPC)
mlflow_uri         MLFLOW_TRACKING_URI                             the platform (the public URL on HPC)
dataset_ref        KUBECORE_DATASET_REF, DATASET,                  steps set KUBECORE_DATASET_REF; DATASET and
                   DATASET_REPO + "@" + DATASET_REF                DATASET_REPO/DATASET_REF in HPC (Slurm) jobs
dataset_commit     KUBECORE_DATASET_COMMIT, DATASET_COMMIT         steps / HPC (Slurm) jobs
support            verdict of kaos_lib.support.check against       the platform (``KAOS_LIB_SUPPORT``)
                   KAOS_LIB_SUPPORT
slot               KUBECORE_SLOT_GPUS, KUBECORE_SLOT_CPUS,         the platform, on a shared HPC (Slurm) node
                   KUBECORE_SLOT_MEM_GIB, KUBECORE_SLOT_SHARED     (None elsewhere)
=================  ==============================================  ==========================================

On a shared HPC (Slurm) node a step gets one slot: its GPUs, its cores and its memory share
(``slot``). ``usable_cpus()`` is the number of cores a step should size its worker pools by: the slot's,
else the CPUs this process may run on, else the machine's.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

ENV = {
    "run_id": ("KUBECORE_RUN_ID",),
    "workflow": ("KUBECORE_WORKFLOW_NAME",),
    "app": ("KUBECORE_APP",),
    "project": ("KUBECORE_PROJECT",),
    "step": ("KUBECORE_STEP", "STEP_NAME"),
    "outputs_repo": ("OUTPUTS_REPO", "CHECKPOINT_BUCKET"),
    "lakefs_endpoint": ("LAKEFS_ENDPOINT", "LAKEFS_URL"),
    "mlflow_uri": ("MLFLOW_TRACKING_URI",),
    "dataset_ref": ("KUBECORE_DATASET_REF", "DATASET"),
    "dataset_commit": ("KUBECORE_DATASET_COMMIT", "DATASET_COMMIT"),
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
    values = {name: _first(env, names) for name, names in ENV.items()}
    values["app"] = values["app"] or _app_of(values["outputs_repo"])
    if not values["dataset_ref"]:
        repo, ref = _first(env, ("DATASET_REPO",)), _first(env, ("DATASET_REF",))
        values["dataset_ref"] = f"{repo}@{ref}" if repo and ref else None
    return Context(**values, support=_support(env), slot=_slot(env))


def run_id(environ: Optional[Mapping] = None) -> Optional[str]:
    """The platform's run id (``$KUBECORE_RUN_ID``), or None outside a pipeline run."""
    return _first(os.environ if environ is None else environ, ENV["run_id"])
