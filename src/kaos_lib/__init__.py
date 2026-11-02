"""kaos_lib (formerly kubecore): the KAOS platform package (datasets, run outputs, CLI).

Public API:
    kaos_lib.datasets  DatasetRef, resolve, list_datasets, versions, release, create_dataset, materialize
    kaos_lib.outputs   outputs_repo, write_run
    kaos_lib.formats   get_format (creator + consumer pairs, first: ultralytics)
    kaos_lib.peers     the projects whose shared datasets this one reads (peers, shared)
"""
__version__ = "0.3.0"
