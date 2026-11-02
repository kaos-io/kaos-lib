# Changelog

All notable changes to kaos-lib. Versions follow PEP 440; each release's support window is in its
`release.json`. Packages: `https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib/simple/` (stable),
`.../kaos-lib-rc/simple/` (prerelease).

## 0.3.0 (2026-11-02)

The package is renamed and moves to its own repository, `kaos-io/kaos-lib` (it was `packages/kubecore` in
`novelcore/hera-pipeline-template`; history carried over).

### Changed
- Distribution `kubecore` → `kaos-lib` (extra `kaos-lib[zitadel]`); import `kubecore` → `kaos_lib`; command
  `kubecore` → `kaos-cli`. Published by the platform's CI to public Python repositories (Artifact Registry), not
  PyPI: `pip install --index-url https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib/simple/
  --extra-index-url https://pypi.org/simple/ "kaos-lib[zitadel]==0.3.0"`.
- `KubecoreError` → `KaosLibError`.
- New dependency: `packaging` (PEP 440 support checks).

### Added
- `release.json` (packaged as `kaos_lib/_release.json`, published per release in the public release bucket) and
  `kaos_lib.support.check`: verdicts current / behind / deprecated / unsupported. Pipeline steps check at import
  when `$KAOS_LIB_SUPPORT` is set; `kaos-cli` warns on reads and refuses writes when unsupported.
- Release channels: prerelease `X.Y.ZrcN` (repository `kaos-lib-rc`, every merge to `main`) and stable `X.Y.Z`
  (repository `kaos-lib`, promoted by the platform's release train from a passed rc, checked to hold the rc's
  code byte for byte). `kaos-cli --version` shows the channel and the targeted platform's recommendation;
  `kaos-cli upgrade` installs that recommendation (kaos-lib over https only), else the newest release of the
  install's channel from the public `release.json`.
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
