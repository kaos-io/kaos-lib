"""kaos_lib (formerly kubecore): the KAOS platform package (datasets, run outputs, CLI).

Public API:
    kaos_lib.datasets  DatasetRef, resolve, list_datasets, versions, release, create_dataset, materialize
    kaos_lib.outputs   outputs_repo, write_run
    kaos_lib.layouts   load, available, Layout (validate, skeleton, materialize, publish): dataset layouts
    kaos_lib.peers     the projects whose shared datasets this one reads (peers, shared)
    kaos_lib.mlflow    mlflow(), token(); the MLflow request-auth provider ``zitadel`` (extra kaos-lib[mlflow])
    kaos_lib.runtime   context(), run_id(), usable_cpus(): what the platform injected, from the environment
    kaos_lib.lock      DataLock, record, write, load, replay: the commits a run read (data.lock.json)
    kaos_lib.checkpoint  dir, save, load, progress, stop_requested, exit_for_restart: checkpoints that survive interruptions
    kaos_lib.progress  report(done, total, unit): how far the step is, shown on the run page
"""
__version__ = "0.4.0"

from . import support as _support  # noqa: E402

_support.at_step_start(__version__)   # pipeline steps only ($KAOS_LIB_SUPPORT): log, MLflow tag, stop if unsupported

import os as _os  # noqa: E402

if _os.environ.get("KAOS_CHECKPOINT_DIR"):          # the platform's checkpoint folder: stop signals and framework hooks
    from . import checkpoint as _checkpoint  # noqa: E402

    _checkpoint.activate()
elif _os.environ.get("KUBECORE_RUN_ID"):             # a pipeline step without a checkpoint folder: progress hooks only
    try:
        from . import frameworks as _frameworks  # noqa: E402

        _frameworks.install()
    except Exception as _exc:                       # the hooks must never break an import
        import sys as _sys

        print("kaos-lib: progress hooks not attached: %s" % _exc, file=_sys.stderr, flush=True)
