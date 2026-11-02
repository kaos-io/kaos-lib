# Changelog

All notable changes to kaos-lib. Versions follow PEP 440; each release's support window is in its
`release.json`.

## Unreleased

Dataset layouts: the formats become declarative, user-definable layouts.

### Added
- `kaos_lib.layouts`: a layout is a `layout.yaml` (spec `layouts/shared/layout.schema.json`) with parameters, a
  starter skeleton (`{{placeholders}}`), declarative rules (required and allowed patterns, extensions, pairs, line
  patterns, a manifest schema), what a pull downloads, and an optional Python hook (`validate`, `materialize`).
  `layouts.load(name|path)`, `layouts.available()`, `Layout.validate/skeleton/parse/materialize/publish`.
- Sources, in lookup order: built-in (`yolo`, `raw`), installed packages (entry point group `kaos_lib.layouts`),
  the project's registry in kaos-lake (`GET /kaos/v1/dataset-templates`, from the project's `layouts`
  repository); a path is read as is.
- `kaos-cli layout list|show|init|validate|publish`; `dataset create --layout <name|path> --param key=value`;
  `dataset push` validates with the layout of the repository's label.
- The schema, the built-in layouts and the test fixtures (`tests/layout_fixtures`) are shared byte for byte with
  kaos-lake, pinned by `SHA256SUMS`; both implementations pass the same fixtures.
- Guide: [Make your own dataset layout](docs/make-your-own-layout.md).

### Changed
- The `yolo` format is the built-in `yolo` layout: a declarative `layout.yaml` plus a small hook
  (`kaos_lib.layouts.yolo`: class ids, value counts, coordinates, the `data.yaml` path rewrite). Some problems are
  worded differently (`data.yaml: no file matches (required)`, `images/x.jpg has no labels/x.txt`).
- `raw` creates a README; `create_dataset`'s default layout is `yolo`, as before.
- `datasets.materialize(..., layout=...)` and `datasets.layout_of`; `fmt_name=`, `format_of` and
  `kaos_lib.formats.get_format` keep working.
- The cache marker records the layout's download patterns: a copy made with other patterns is fetched again.

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
