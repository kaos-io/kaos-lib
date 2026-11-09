# Develop

## Tests

```bash
pip install -e ".[test]" && pytest
```

A fake lakeFS (`tests/fake_lakefs.py`) runs the real client over an in-memory transport; a fake Zitadel token
endpoint (`tests/fake_zitadel.py`) and a fake MlflowClient (`tests/fake_mlflow.py`) stand in for the others; no
network. With mlflow-skinny installed (the `test` extra) a few tests also drive real MLflow: its auth-provider
registry, a request to a local HTTP server, and a lock round trip through a file store.

## File map

| file | job |
| --- | --- |
| `config.py` | per-app config discovery, lakeFS URL, OIDC settings |
| `credentials.py` | the credential chain, session cache, browser login |
| `oidc.py` | PKCE browser login to Zitadel (ported from `dataset_tools`) |
| `zitadel.py` | machine-key token (JWT-profile grant), extra `kaos-lib[zitadel]` |
| `mlflow.py` | `mlflow()`, `token()`, the MLflow auth provider `zitadel`, extra `kaos-lib[mlflow]` |
| `runtime.py` | `context()`, `run_id()`: the injected run context |
| `lock.py` | the data lock: record, write, load, replay, `$KAOS_LIB_LOCK` |
| `peers.py` | the other projects (`/kaos/v1/peers`) and what they share (`/kaos/v1/shared`) |
| `lakefs.py` | lakeFS REST client |
| `transfer.py` | mirror plan, upload, download of file trees |
| `datasets.py` | refs (`[<owner>/]<repo>@<ref>`), resolve, list, versions, release, create, publish via PR, materialize |
| `layouts/` | layouts: sources, spec and schema subset (`spec.py`), skeletons (`render.py`), rules (`rules.py`), the yolo hook (`yolo.py`), the cache (`local.py`), the files shared with kaos-lake (`shared/`) |
| `formats/` | the 0.3 `get_format` API over layouts |
| `outputs.py` | `outputs-<app>` writes |
| `checkpoint.py` | checkpoints that survive interruptions: `dir`, `save`, `load`, `progress`, `stop_requested`, `exit_for_restart`, `register` + `tick` |
| `frameworks.py` | the automatic checkpoint hooks for Ultralytics, PyTorch Lightning and Hugging Face (`best.pt` kept on a continuation, `resume.<name>` MLflow parameters) |
| `errors.py` | the exception classes (`KaosLibError` and its subclasses) |
| `support.py` | the support window: `release.json` checks for steps and the CLI |
| `channel.py` | release channel of the install (PEP 610), the platform's recommended spec (`upgrade`) |
| `cli.py` | the `kaosctl` command (and the deprecated `kubecore` alias) |
| `kubecore/` | the deprecated `kubecore` import shim (0.3.x and 0.4.x) |

## The documentation site

Build it with `mkdocs build --strict` (`pip install -r docs/requirements.txt -e .`). The mkdocs hook `docs/hooks.py`
runs `docs_gen.py` before every build and writes `docs/generated/`: the CLI reference (every `kaosctl` command's
`--help`, from `kaos_lib.cli.build_parser`), the version line, and each channel's install command (from its public
`release.json`). Never edit `docs/generated/`; it is not committed.
