# Install

kaos-lib is published by the platform's CI to two **public Python repositories** (Google Artifact Registry), not
PyPI. Its dependencies come from PyPI.

## The newest release of each channel

--8<-- "generated/install.md"

Pin the version (`==`): pip takes the highest version it finds across both indexes, and kaos-lib exists only in the
first. Run it inside a virtual environment:

```bash
python3 -m venv .venv && . .venv/bin/activate
```

## Channels

| channel | pip index | versions | made by |
| --- | --- | --- | --- |
| prerelease | `https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib-rc/simple/` | `X.Y.ZrcN` | every merge to `main` |
| stable | `https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib/simple/` | `X.Y.Z` | the platform's release train only, from an rc that passed the dev e2e |

`X.Y.Z` is the version in `pyproject.toml`, the next release. Versions are immutable in a repository, so every rc
has its own number; the stable `X.Y.Z` is the rc's commit built again at `X.Y.Z`, and the release train checks that
it holds the rc's code byte for byte.

Each channel's newest release metadata is public, at
`https://storage.googleapis.com/kaos-dev-511509-kaos-lib/<channel>/release.json` (`rc` or `stable`), with
`<channel>/<tag>/release.json` and `SHA256SUMS` for every release. Its `recommended` field is the exact requirement
platform images install: one wheel file with its `#sha256=`, so no index decides anything.

## Extras

| extra | adds | needed for |
| --- | --- | --- |
| `zitadel` | PyJWT, cryptography | a pipeline step reading datasets other projects share (machine-key tokens) |
| `mlflow` | mlflow-skinny 3, PyJWT, cryptography | `kaos_lib.mlflow`, writing and loading data locks, `kaosctl run --lock`, the MLflow auth provider `zitadel` |

Without an extra, drop the `[...]` from the commands above.

## Requirements

Python 3.9 or newer. Dependencies: `requests`, `PyYAML`, `packaging`.

## Check and upgrade

```bash
kaosctl --version     # the version, its channel, and what your platform recommends
kaosctl upgrade       # install the platform's recommendation (--dry-run to see it first)
```

Import it as `kaos_lib`. The command is `kaosctl`; `kaos-cli` still works for one release and prints a notice.
