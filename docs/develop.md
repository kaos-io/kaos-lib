# Develop

## Tests

```bash
pip install -e ".[test]" && pytest
```

A fake lakeFS (`tests/fake_lakefs.py`) runs the real client over an in-memory transport; a fake Zitadel token
endpoint (`tests/fake_zitadel.py`) and a fake MlflowClient (`tests/fake_mlflow.py`) stand in for the others; no
network. With mlflow-skinny installed (the `test` extra) a few tests also drive real MLflow: its auth-provider
registry, a request to a local HTTP server, and a lock round trip through a file store.

### Against a real lakeFS

The fake has no merge conflicts, no branch protection and no policies. To run every test that uses it against a real
server in a container as well (needs docker; skipped when docker is not available):

```bash
KAOS_LIB_TEST_LAKEFS=real pytest -k real-lakefs      # only the tests that reach lakeFS, on the real server
KAOS_LIB_TEST_LAKEFS=both pytest                     # everything; those tests run twice
```

The image is `$KAOS_LIB_TEST_LAKEFS_IMAGE`, else a local `kaos-lake:prd1911` when there is one, else
`treeverse/lakefs:1.86.0`, with local block storage. `tests/real_lakefs.py` gives the server the fake's helper names;
the `/kaos/v1` answers stay scripted, and a test that rewrites the fake's state in place is skipped there.
`tests/test_real_server.py` holds what only a real server answers (a refused merge, a protected branch).

## File map

| file | job |
| --- | --- |
| `config.py` | per-app config discovery, lakeFS URL, OIDC settings |
| `credentials.py` | the credential chain, session cache, browser login |
| `oidc.py` | PKCE browser login to Zitadel (ported from `dataset_tools`) |
| `zitadel.py` | machine-key token (JWT-profile grant), extra `kaos-lib[zitadel]` |
| `mlflow.py` | `mlflow()`, `token()`, the MLflow auth provider `zitadel`, extra `kaos-lib[mlflow]` |
| `step.py` | a pipeline step: `start`, `input`, `output`, `upstream`, `check`, `result`; reads the step context, writes the result |
| `runtime.py` | `context()`, `run_id()`: where the step runs |
| `lock.py` | the ledger (the data lock at version 2): reads and writes, the wire form and its cost, load, replay, `$KAOS_LIB_LOCK` |
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
| `channel.py` | release channel of the install (PEP 610), the platform's recommended spec (`upgrade`), the extension published with a release (`public_vscode`) |
| `editor.py` | `kaosctl vscode install`: find the editor's command, download the published `.vsix` and check its SHA-256 |
| `cli.py` | the `kaosctl` command |
| `lint/` | the pipeline linter: `engine.py` runs the rules of `rules_errors.py`, `rules_warnings.py`, `rules_infos.py` over what `pipeline_reader.py` / `project_reader.py` read, with the facts of `catalogue.py`; `model.py` (report), `render.py`, `cli.py`; `standalone.py` runs it without importing the rest of kaos-lib (PR gate). Static: never runs client code. Standard library + PyYAML only |
| `lint/schema.py`, `lint/graph.py` | `kaosctl lint --schema` (what `step()` accepts, for editors) and `--graph` (the step DAG); the extension's bundled copy of the schema is `editors/vscode/resources/step-schema.json`, kept equal by `tests/test_lint_schema.py` |
| `editors/vscode/` | the VS Code extension (TypeScript, no runtime dependencies): `npm test`, `npm run package`; see its README |

## The documentation site

Build it with `mkdocs build --strict` (`pip install -r docs/requirements.txt -e .`). The mkdocs hook `docs/hooks.py`
runs `docs_gen.py` before every build and writes `docs/generated/`: the CLI reference (every `kaosctl` command's
`--help`, from `kaos_lib.cli.build_parser`), the version line, and each channel's install command (from its public
`release.json`). Never edit `docs/generated/`; it is not committed.

The second hook, `docs_check.py`, runs three checks before every build, and a finding fails the build. Run them
alone with `python3 docs_check.py`:

| check | fails on |
| --- | --- |
| words | a page that names what the platform is built from. These pages are for client engineers: the list is `WORDS` in the file |
| removed names | a step or a folder that no longer exists (`REMOVED` in the file) |
| links | a link of this repository that does not resolve, here or in the two pipeline templates (hera, yolo), and a link of a template into this site that does not resolve |

This file is the only copy of the checks. The templates carry none, so an app created from a template is never
checked by it: a template's `scripts/check-docs.sh` and the platform's docs build of the templates run this file
on the template (`python3 docs_check.py <template folder>`).

The link check reads the other repositories at their trunk: it downloads them, or reads the checkouts named by
`DOCS_CHECK_HERA` and `DOCS_CHECK_YOLO`. A download that fails stops the build with a message that names the
repository; nothing is skipped silently. `DOCS_CHECK_OFFLINE=1` checks this repository alone and prints what it
skipped; set it yourself to build without the network. `DOCS_CHECK_EXTERNAL=1` also fetches every other address.
`CHANGELOG.md` and `docs/design/` are not client pages and are not checked for words and removed names.
`python3 docs_check.py --self-test` runs the checker's own cases; the build runs them too.

One topic has one page. What is true for every pipeline is explained here; a template's guide holds only what is
specific to that template and links here for the rest.
