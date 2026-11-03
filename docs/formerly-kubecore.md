# Formerly kubecore

Up to 0.2 this was the `kubecore` package in `novelcore/hera-pipeline-template` (`packages/kubecore`). For one
release (0.3.x, and still in 0.4.x) the distribution ships:

- a `kubecore` import shim: `import kubecore` and `from kaos_lib import datasets` keep working (the very
  `kaos_lib` modules) and emit one `DeprecationWarning`. Replace `kubecore` with `kaos_lib` in your imports;
  `KubecoreError` is now `KaosLibError` (the old name stays an alias).
- a `kubecore` command: runs `kaosctl` after a note on stderr.

Unchanged on purpose (other components and existing installs rely on them): the per-app
`.kubecore/dataset-config.yaml`, the login session in `~/.config/kubecore-ml/` (`$KUBECORE_ML_HOME`), the
dataset cache `~/.cache/kubecore/datasets` with its `.kubecore-dataset.json` markers, and the `KUBECORE_*`
environment variables.
