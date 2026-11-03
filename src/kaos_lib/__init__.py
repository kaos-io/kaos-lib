"""kaos_lib (formerly kubecore): the KAOS platform package (datasets, run outputs, CLI).

Public API:
    kaos_lib.datasets  DatasetRef, resolve, list_datasets, versions, release, create_dataset, materialize
    kaos_lib.outputs   outputs_repo, write_run
    kaos_lib.layouts   load, available, Layout (validate, skeleton, materialize, publish): dataset layouts
    kaos_lib.peers     the projects whose shared datasets this one reads (peers, shared)
    kaos_lib.mlflow    mlflow(), token(); the MLflow request-auth provider ``zitadel`` (extra kaos-lib[mlflow])
    kaos_lib.runtime   context(), run_id(), usable_cpus(): what the platform injected, from the environment
    kaos_lib.lock      DataLock, record, write, load, replay: the commits a run read (data.lock.json)
"""
__version__ = "0.4.0"

from . import support as _support  # noqa: E402

_support.at_step_start(__version__)   # pipeline steps only ($KAOS_LIB_SUPPORT): log, MLflow tag, stop if unsupported
