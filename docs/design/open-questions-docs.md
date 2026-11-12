# Open questions of the client documentation

Status: a design note for the platform team. It is not a client page and is not in the navigation (`docs/design/` is
excluded from the site). Each entry is a question a client engineer will ask, which the repositories kaos-lib, the hera
template and the yolo template do not answer. The guide does not describe them until the owner of the answer supplies
it. Written 2026-11-12 with the audit fixes of PRD kaos#1911.

## Not provable from these repositories

| # | question | what is missing | brief item |
|---|---|---|---|
| 1 | Where does a client see the metrics, the model and the files of a run in the console? | The console is not in these repositories. The guide says what a step writes (`step.result`, `produces=`, MLflow calls) and how to download the files (`kaosctl dataset pull outputs-<app>`), and nothing about screens | E1 |
| 2 | Does the platform set `MLFLOW_TRACKING_URI` and a credential in every step, and on every machine (the platform's own and HPC)? | `kaos_lib.mlflow.mlflow()` reads them (`src/kaos_lib/mlflow.py`), and the yolo template calls it. The engine that sets them is not here | E1 |
| 3 | How does an `ingest` step get a secret for its source (an API key, a password)? Can it reach the internet at all? | No mechanism appears in kaos-lib, in the templates or in `kubecore/authoring.py`. The guide's example reads a folder and says nothing about the network or secrets | E3 |
| 4 | How does the owner of a dataset share it with another project, and who may? | Only the reading side is in the code (`kaosctl dataset list --shared`, `<owner>/dataset-...@<version>`). The message of the command says the owner shares from the dataset's page in the data store; the steps of that page are not documented | E5 |
| 5 | How does a client delete a dataset version, or roll `latest` back to an older version? | `kaosctl` has no such command (`src/kaos_lib/cli.py`). A version never changes ([Principles](principles.md)); whether a version can be removed, and by whom, is not stated anywhere | E6 |
| 6 | How does a client re-run, cancel or stop a run, or re-run one step? | Not in the library or the templates. The console runs them | E6 |
| 7 | What is a machine class, what does it contain (CPU, memory, GPU), and what does it cost? | The class names come from the project's platform context, which is not in these repositories. `kaosctl lint` skips the checks that need them without `--context` | E6 |
| 8 | Which MLflow experiment does a run belong to, when the step does not name one? | The library only logs the ledger onto the MLflow runs a step creates. The example names the experiment and the run itself | E1 |
| 9 | Where in the console is the "advanced config" of a run that holds the request to move `latest`? | The field name `plan: {promote: {...}}` is in the examples; the place on the run form is not in these repositories | D3 |

## Found while fixing, not fixed because it is outside the brief

- `docs/lint/L-E08.md` lists the old environment variables the rule searches for, including a workflow name. It is the
  rule's own content, so it stays.
- `docs/bigger-machines.md` no longer says that a GPU step must keep a shell (`/bin/sh`) in its image: the brief asked to
  keep only what the reader must do. If an image without a shell does fail a GPU step, one line in the page is missing.
- The syntax of `when=` is `{{workflow.parameters.<field>}}`, written by the author exactly as the pipeline engine
  reads it (`kubecore/authoring.py` passes the string on as the condition of the step). The guide calls it "the value of the
  run-form field `<field>`" and does not name the engine. The syntax itself shows an internal name: the owner can decide
  on a friendlier form, for example `when="extra-mode != off"`, which the engine would translate.
- There is no module `kaos_lib.tracking`; MLflow is `kaos_lib.mlflow`.
