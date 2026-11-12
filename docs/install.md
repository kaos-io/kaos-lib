# Install

kaos-lib is served from two **Python package indexes** (Google Artifact Registry), not PyPI. Its dependencies come
from PyPI.

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
| prerelease | `https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib-rc/simple/` | `X.Y.ZrcN` | published first, with every change |
| stable | `https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib/simple/` | `X.Y.Z` | published after a prerelease has been tested |

Use the prerelease channel until a stable release exists. Each release has its own number (`0.5.0rc10`, later
`0.5.0`), so pin it with `==`. The exact current version of each channel is listed at the top of this page.

## Extras

| extra | adds | needed for |
| --- | --- | --- |
| `zitadel` | PyJWT, cryptography | reading datasets that another project shares with yours, from a pipeline step |
| `mlflow` | mlflow-skinny 3, PyJWT, cryptography | `kaos_lib.mlflow`, writing and loading data locks, `kaosctl run --lock`, MLflow sign-in from a step |

Without an extra, drop the `[...]` from the commands above.

## Requirements

Python 3.9 or newer. Dependencies: `requests`, `PyYAML`, `packaging`.

## Check and upgrade

```bash
kaosctl --version     # the version, its channel, and what your platform recommends
kaosctl upgrade       # install the platform's recommendation (--dry-run to see it first)
kaosctl vscode install   # optional: the KAOS extension for VS Code, the version of this kaos-lib
```

Import it as `kaos_lib`. The command is `kaosctl`.
