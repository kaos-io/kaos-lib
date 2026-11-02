# Changelog

All notable changes to kaos-lib. Versions follow PEP 440; each release's support window is in its
`release.json`.

## 0.4.0 (unreleased)

PRD novelcore/kaos#1147 F-05, F-07, F-18 (D-03, D-13).

### Added
- `kaos_lib.mlflow`: `mlflow(tracking_uri=None, token=None)` configures the `mlflow` module and returns an
  `MlflowClient`; `token()`. One credential chain: explicit token or `$MLFLOW_TRACKING_TOKEN`, the step's machine
  key (`ZITADEL_MACHINE_KEY_FILE`, `ZITADEL_DOMAIN`, `ZITADEL_MLFLOW_PROJECT_ID`; minted with the organisation
  project's audience scope and refreshed before expiry), then the `kaos-cli login` session (checked for expiry and
  for the organisation project's audience). New extra `kaos-lib[mlflow]`; `mlflow` is imported lazily.
- The MLflow request-auth provider `zitadel` (entry point `mlflow.request_auth_provider`), registered by
  kaos-lib: `MLFLOW_TRACKING_AUTH=zitadel` works without the `mlflow_zitadel_auth.py` file templates copied
  into every step.
- `kaos_lib.runtime`: `context()` (frozen `Context`: run id, workflow, app, project, step, outputs repository,
  lakeFS and MLflow endpoints, dataset ref and commit, support verdict) and `run_id()`, read from the environment
  only; missing values are None.
- `kaos_lib.lock`: the data lock. `datasets.resolve` (and so `materialize`) records every read; `record`,
  `write` (MLflow tags `kaos_lib.data.<repo>.commit` / `.owner` and the artifact `data.lock.json`, merged with
  the run's), `load`, `DataLock.replay`, and `$KAOS_LIB_LOCK`. `LockError` for malformed or missing locks.
- `kaos-cli run --lock <mlflow-run-id> -- <command>`: runs the command with the lock in `$KAOS_LIB_LOCK`.
- `zitadel.grant` (the whole token response, with `expires_in`) and `zitadel.env_settings`.

### Unchanged
- The `kubecore` import shim and command still ship in 0.4.0: templates still import `kubecore`. Support:
  `>=0.2`, no deprecations.

## 0.3.0 (2026-11-02)

The package is renamed and moves to its own repository, `kaos-io/kaos-lib` (it was `packages/kubecore` in
`novelcore/hera-pipeline-template`; history carried over).

### Changed
- Distribution `kubecore` → `kaos-lib` (`pip install kaos-lib`, extra `kaos-lib[zitadel]`); import `kubecore` →
  `kaos_lib`; command `kubecore` → `kaos-cli`. Install from git as
  `kaos-lib @ https://github.com/kaos-io/kaos-lib/archive/<sha>.zip` (no `#subdirectory`).
- `KubecoreError` → `KaosLibError`.
- New dependency: `packaging` (PEP 440 support checks).

### Added
- `release.json` (packaged as `kaos_lib/_release.json`, attached to each GitHub release) and
  `kaos_lib.support.check`: verdicts current / behind / deprecated / unsupported. Pipeline steps check at import
  when `$KAOS_LIB_SUPPORT` is set; `kaos-cli` warns on reads and refuses writes when unsupported.
- Apache-2.0 license, project URLs, this changelog.

### Deprecated (removed in the next release)
- The `kubecore` import shim: `import kubecore` / `from kubecore import datasets` still work (the same
  `kaos_lib` modules) and emit one `DeprecationWarning`.
- The `kubecore` command: runs `kaos-cli` after a note on stderr.
- The `KubecoreError` alias.

### Unchanged on purpose
- `.kubecore/dataset-config.yaml`, `~/.config/kubecore-ml/` (`$KUBECORE_ML_HOME`), the dataset cache
  `~/.cache/kubecore/datasets` with its `.kubecore-dataset.json` markers, and the `KUBECORE_*` variables: other
  platform components and existing logins and caches rely on them.

Support: `>=0.2`, no deprecations.

## 0.2.0

Last release as `kubecore` inside `novelcore/hera-pipeline-template`: datasets as lakeFS repositories, raw format,
shared datasets between projects, branch-per-run outputs.
