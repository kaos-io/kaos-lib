"""Where a step runs: the run, app, endpoints and dataset the platform injected, read from the environment only.

Nothing here is hardcoded (PRD kaos#1147 section 3.5): when the platform changes what it injects, an older
kaos-lib keeps reading the names below. Every field is None when its variables are unset or empty; ``context()``
never raises.

=================  ==============================================  ==========================================
field              variables (first non-empty wins)                set today by
=================  ==============================================  ==========================================
run_id             KUBECORE_RUN_ID                                 the enhancer, every step (``workflow.name``)
workflow           KUBECORE_WORKFLOW_NAME                          the enhancer, every step (names the MLflow run)
app                KUBECORE_APP, else derived from outputs_repo    outputs_repo ``outputs-<app>``
project            KUBECORE_PROJECT                                not injected yet
step               KUBECORE_STEP, STEP_NAME                        STEP_NAME: MeluXina submit pod and job
outputs_repo       OUTPUTS_REPO, CHECKPOINT_BUCKET                 CHECKPOINT_BUCKET every step; OUTPUTS_REPO HPC
lakefs_endpoint    LAKEFS_ENDPOINT, LAKEFS_URL                     the enhancer (in-cluster); public URL on HPC
mlflow_uri         MLFLOW_TRACKING_URI                             the enhancer (in-cluster); public URL on HPC
dataset_ref        KUBECORE_DATASET_REF, DATASET,                  steps set KUBECORE_DATASET_REF; DATASET and
                   DATASET_REPO + "@" + DATASET_REF                DATASET_REPO/DATASET_REF on MeluXina
dataset_commit     KUBECORE_DATASET_COMMIT, DATASET_COMMIT         steps / MeluXina job
support            verdict of kaos_lib.support.check against       the platform (``KAOS_LIB_SUPPORT``)
                   KAOS_LIB_SUPPORT
=================  ==============================================  ==========================================
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


def context(environ: Optional[Mapping] = None) -> Context:
    """The step's context from ``environ`` (default ``os.environ``); missing values are None."""
    env = os.environ if environ is None else environ
    values = {name: _first(env, names) for name, names in ENV.items()}
    values["app"] = values["app"] or _app_of(values["outputs_repo"])
    if not values["dataset_ref"]:
        repo, ref = _first(env, ("DATASET_REPO",)), _first(env, ("DATASET_REF",))
        values["dataset_ref"] = f"{repo}@{ref}" if repo and ref else None
    return Context(**values, support=_support(env))


def run_id(environ: Optional[Mapping] = None) -> Optional[str]:
    """The platform's run id (``$KUBECORE_RUN_ID``), or None outside a pipeline run."""
    return _first(os.environ if environ is None else environ, ENV["run_id"])
