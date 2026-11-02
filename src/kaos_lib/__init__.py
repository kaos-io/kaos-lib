"""kaos_lib (formerly kubecore): the KAOS platform package (datasets, run outputs, CLI).

Public API:
    kaos_lib.datasets  DatasetRef, resolve, list_datasets, versions, release, create_dataset, materialize
    kaos_lib.outputs   outputs_repo, write_run
    kaos_lib.layouts   load, available, Layout (validate, skeleton, materialize, publish): dataset layouts
    kaos_lib.peers     the projects whose shared datasets this one reads (peers, shared)
"""
__version__ = "0.3.0"

from . import support as _support  # noqa: E402

_support.at_step_start(__version__)   # pipeline steps only ($KAOS_LIB_SUPPORT): log, MLflow tag, stop if unsupported
