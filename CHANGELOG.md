# Changelog

All notable changes to kaos-lib. Versions follow PEP 440; each release's support window is in its
`release.json`. Packages: `https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib/simple/` (stable),
`.../kaos-lib-rc/simple/` (prerelease).

## 0.5.0 (unreleased)

PRD novelcore/kaos#1911 F-02: one step contract. **Breaking: no app is moved; every app is created again from the
template.** Nothing in kaos-lib converts an old app.

### Added
- A job on HPC can sign in to the data store with the key pair of its own app from a file (`LAKEFS_KEY_FILE`, JSON with
  `access_key_id`, `secret_access_key` and `expiration`). The file is read again when it changes or the key is near its
  end, so a long step goes on with a refreshed key. A key pair is used before a bearer token, and a step that started on the bearer (the file was not there yet) changes to the key pair as soon as the file holds one (PRD novelcore/kaos#1911 AC-14).
- Start a run from a step: the run form's `reuse-from-run` and `start-from-step` (PRD novelcore/kaos#1911, novelcore/kaos#2080). The steps
  before the step are not run again; the new run takes the earlier run's results and outputs. Every step that ends
  (`step.result()`, `step.skip()`) now saves the exact result it handed on as `kaos-runs/<run>/<step>.json` of the app's
  `outputs-<app>` (`kaos_lib.record`; it says whose it is, the app, run, instance and step, around the exact result; best effort: a failure is a warning in the step's log and the step still succeeds; not
  for an item of a step with `matrix=` and not in a local run). A write in a result may carry `path`, the folder of the run
  that wrote a model or an artifact (`kaos_lib.lock.Write.path`), and `step.input(name)` reads it from there. A step image with
  an older kaos-lib cannot read a model of an earlier run and fails with a message that names the folder it did not find. The page
  Re-running is rewritten; the contract page has the two fields.
- A value in `when=` is compared exactly: a string as text, a number or a boolean by its JSON text (`evaluate.rows !=
  1000000` is false for 1000000; `1e6`, `1000000.0` and `1000000` all match it). A text that could never match is refused
  by `kaosctl lint` and the render (`.5`, `+1`, `True`, an integer above 9007199254740992, a line break). `when=` text with a
  control character is refused. `L-E07` also refuses a step that writes a name a step it needs writes.
- The final task of a run says the truth in every outcome (what it promoted, what another run moved, what it did not try, and
  whether trying again helps), and no pod starts for it when no `promote-<name>` is `true`. A run that overlaps another
  promoting run on the same dataset is refused whole at the end; its versions stay readable by their exact version.
- Sweeps with one keyword: `step("train", kind="train", matrix={"lr": [0.01, 0.001], "batch": [16, 32]}, ...)` runs the step once
  for each combination (at most 32). Each run reads its values like any setting, `step.params["lr"]` (`Step.matrix` says
  which run it is), and saves its own model or artifact under `<name>/<experiment>/<run>/<index>/` as one version with the
  run's number and values on it. The step after it gets a plain list: `step.upstream("train")` has one `UpstreamItem` for each
  run, in order (`index`, `matrix`, `status` `ok` / `failed` / `skipped`, `values`, `reads`, `writes`, `reason`), and
  `step.input("model", item=N)` reads one run's output. The values an item hands on cost at most the smaller of 8 KiB and 16 KiB divided
  by the number of items (what it read and wrote does not count). One failed item fails the step; `matrix_allow_failed=True` lets the
  step after it run and see which failed (`L-W08` warns when a dataset is written after it). `<step>-parallel` defaults to 4. A whole
  number beyond 2^53 in `matrix=` is refused: write it as text. `kaosctl step run <step> --matrix-index N` runs one combination on your machine;
  `testing.running(matrix=..., matrix_index=..., upstream_matrix=...)` tests a step and the step after it. Lint rule set 2.5.0:
  `L-E06` reports what the render refuses in `matrix=` (shape, names, values, more than 32 combinations, kinds that run once,
  a dataset in `produces=`, a matrix step that needs a matrix step, a `when=` on a matrix step's value), and `kaosctl lint --graph`
  gives a step with `matrix=` one node with its `matrix_items`. The page Sweeps is rewritten for it and replaces the loop inside
  one step.
- Conditions and skipping. `when=` can test a value an earlier step handed on: `when="evaluate.passed == true"`
  (`<step>.<value>`, the step must be in `needs=`; a missing value stops the run with a message that names the step and the
  value). `kaos_lib.step.skip("reason")` ends a step as skipped: exit code 0, a skipped result with the reason, nothing
  saved. The steps that need a skipped step still run and find it with `step.skipped(name)` or
  `step.upstream(name, optional=True)`. `kaos_lib.testing.running(upstream_skipped=...)` and `kaosctl step run` show it.
  New pages: Conditions and skipping, Sweeps, Several pipelines, Re-running.
- **Breaking, in the same release: a dataset's `latest` moves once, at the end of the run, for all or none.** A step only
  seals its version (`step.result()` no longer moves `latest`; the context has no `promote`). A final task of the run
  checks every dataset whose `promote-<name>` is `true` and moves them all, or none when one of them moved meanwhile.
  `kaos.promoted` stays on the merge. Skipped producers are not promoted. Pages "Move `latest`" and "Principles" say so.
- Lint rule set 2.3.0: `L-E07` also refuses a dataset name under 3 characters, an input that is also an output of the same
  step, and a step with no folder `steps/<name with underscores>/`; `L-E05` reads a config file with several top-level
  keys as several sections, as the engine does; `L-W06` is silent when the step sets `checkpoint_every=`; new `L-W07` (a
  GPU step that produces a dataset runs on the cluster) and `L-I04` (steps built in a loop were not read). `L-I01` and `L-I02`
  name a step built in a loop by its line. `kaosctl step run` finds steps built in a loop by running `pipeline.py` with a
  recorder, and says which folder is missing instead of `exited with code 127`.
- `kaosctl render` and `kaosctl step run` take the engine release from the `engine` block of this kaos-lib release's
  `_release.json` when no flag, variable or context gives one. No release names one yet: the message says so and says what
  to do.
- Step kinds are a contract, checked by `L-E07` and by the platform: an ingest step produces a dataset, a transform step
  produces something, a train step produces a model, an evaluate step produces artifacts only, a publish step and a
  control step produce nothing (page "Step kinds"). `L-W06` warns about a training step with a time limit
  that is not resumable. The removed keywords (`outputs=`, `hpc_time_limit=`, `disk=`) say what to write instead. Rule
  set 2.2.0.
- `kaos_lib.checkpoint` uses the run form's `<step>-checkpoint-every` as the interval of `tick()` when the step sets none.
- A dataset is promoted by the run-form field `promote-<name>`; `plan.promote` of the advanced config is gone.
- `kaos_lib.step`: `start()`, `input(name)`, `output(name)`, `upstream(step)`, `check(name)`, `result(**values)`. A step is
  started with no arguments, reads everything from `step.start()` and hands one result on. A step that ends without
  `step.result()` fails.
- The ledger: the data lock at version 2, with named reads and with writes. Each step records what it read and wrote in
  its result and, on its MLflow run, in its own `ledger/<step>.json`.
- `step()` in `pipeline.py` takes `kind=` (required), `inputs=`, `produces=` and `walltime=`. `kaosctl lint` checks them
  (`L-E07`), and refuses what an app from before the contract has (`outputs=`, `hpc_time_limit=`, `disk=`, a step
  with no `kind=`, a `kubecore/` folder, `--params`, the `platform` config group: `L-E06`, `L-E08`, `L-E09`) with the
  sentence the engine uses. Rule set 2.0.0.
- `step.workdir()` (a scratch folder for tool caches and run folders, emptied at each attempt, never saved),
  `step.input(name, writable=True)` (a private full copy of an input that the step may write into) and
  `testing.running(upstream_writes=...)` (what an upstream step wrote, for tests).
- `kaosctl step run --python INTERPRETER` runs a step with an existing Python and builds no environment. The
  environments of `kaosctl dev` and `kaosctl step run` now live in the cache folder, never in the app's repository.
- The wire form of the context and the result writes `$` inside strings as `\u0024` (Kubernetes expands `$(NAME)` in an
  environment value).
- `kaosctl step run` starts a step with the new contract: `--input NAME=FOLDER|REPO@REF` gives an input, `--upstream`
  a needed step's result; outputs and results stay in `.kaos/local/`.
- On HPC (Slurm) every input of a step is read from its own staged copy.
- A step can produce a dataset (`produces=[dataset("name")]`, PRD novelcore/kaos#1911 F-11, F-12): `step.result()` makes
  the folder one version of `dataset-<name>`. Only files that changed since the last version are uploaded; the version
  is checked against what the step wrote before and after it is sealed; `latest` moves only when the run asks, and never
  onto a dataset that another run changed in the meantime (the step then writes its version again on the new one).
- Uploads are tried again after a failure that can pass (a dropped connection, a busy server).
- `step.result()` saves in order: it checks everything it can, saves every output without moving any dataset's
  `latest`, and only then moves `latest` of the datasets the run asked to move. A step that fails moves none. A model
  or an artifact holds exactly the files of the attempt that made the result.
- `kaos_lib.testing.running`: call a step's `main()` in your own tests with a prepared context and local folders.
- `kaosctl dev --vscode` writes `.vscode/settings.json` (it is no longer written otherwise); `--kaos-lib` takes the
  path of a checkout, a wheel or an archive on your machine.
- A step that ends with exit code 0 without a result now ends with 1; the exit code a step chose is kept.
- `kaosctl dataset push` to a new repository whose name no dataset can have is refused with the reason, before anything
  is created.

### Fixed
- What `kaos_lib.checkpoint` saves (the state file of `save(obj)`, the folder of a checkpoint) is readable by other users, so the platform's helper can copy it and a resumable step no longer restarts from zero (PRD novelcore/kaos#1911 AC-24, D-64).

### Changed
- A step reads a dataset another project shares as the app itself, not with the project's key (PRD novelcore/kaos#1911 D-44).
  Nothing in an app changes: `<project>/dataset-<name>@<version>` reads as before. The key it gets there reads only the
  datasets shared with your project, never writes, and lasts about an hour. When the owner stops sharing a dataset, the next
  read of it is refused. `credentials.resolve_peer` no longer mints a token from the project's key; it is the chain of a
  person (`kaosctl login`) or a job that carries `LAKEFS_BEARER_TOKEN`.
- The merge that moves `latest` records which version it promoted (`kaos.promoted` on that commit), so the platform
  knows a promoted version and never expires it.
- A step that makes a dataset uploads only the files that differ from `latest` and from the newest version an earlier run
  sealed in it: a file with the same path, size and content is copied inside the data store, and a file that cannot be
  copied is uploaded. Every run still makes its own version and tag. The log line says how many were reused. Models and
  artifacts are unchanged. An output of less than 1 MiB to upload does not look for a version to copy from.
- The tag that keeps a sealed dataset version is now `k-<time>-<run>-<step>-<12 characters of the commit>`, the time being
  when the step sealed it (`20261112T093015Z`), so the newest version is found by name in a few calls. Tags of the
  old form `k-<run>-<step>-<commit>` are never used as a source of copies.
- A step that fails for a reason kaos-lib explains (an input that holds no files, an output that was not written, a
  refused write) prints one line, `ERROR: <what happened and what to do>`, and the line of the step's code it came
  from, with no traceback. A failure of the step's own code keeps its traceback.
- `runtime.context()` takes the run, app, project, step, kind and experiment from what the platform hands the step.
- Inside a pipeline step, `datasets.resolve` and `datasets.materialize` refuse a dataset the run did not pin.
- `kaosctl lint` reads only the repository's own files (no virtualenv, `.kaos/`, caches or ignored folders) and its
  `L-W03` now warns about a dataset version written in step code instead of the default version in config.
- `kaosctl dataset versions BAD` and other invalid names answer "invalid dataset name" instead of an HTTP error.
- A machine-key sign-in (the MLflow token a step asks for at its start) is tried again after a failure that can pass (no
  connection, a timeout, HTTP 502/503/504), for about 2.5 minutes, with one line on stderr per try. A refused key still
  fails at once.
- `kaosctl step run --python` with a relative path now resolves it from the folder you ran the command in, and names the
  path when no interpreter is there, instead of "exited with code 127".
- `kaosctl step run` without `--params-file` or `--context` now starts by telling you to write a `params.yaml`.
- `when=` of `step()` is written in plain words: the name of a run-form field, `==` or `!=`, and a value
  (`when="quantization-mode != off"`), joined with `and` / `or`. `kaosctl lint` reports (`L-E06`) a `when=` that is
  not written that way and a field the run form does not have. Rule set 2.1.0.

### Removed
- `hpc_time_limit=` (use `walltime=`) and `outputs=` (use `step.result()`), with no alias.
- The `kubecore` import shim, the `kubecore` and `kaos-cli` commands, `kaos_lib.errors.KubecoreError`.
- `lock.write()` and writing `data.lock.json` (reading one, for a run made with 0.4, stays).
- `runtime.context().dataset_ref`, `.dataset_commit`, `.workflow`, and reading `KUBECORE_RUN_ID`, `KUBECORE_APP`,
  `KUBECORE_STEP`, `STEP_NAME`, `OUTPUTS_REPO`, `CHECKPOINT_BUCKET`, `KUBECORE_DATASET_*`, `DATASET*` and
  `KUBECORE_STAGED_DIR`.
- `kaosctl step run --dataset` (use `--input NAME=REPO@REF`).
- The `{{workflow.parameters.<field>}}` form of `when=`, with no alias: it is refused with the field-name form as the
  example.
- A file next to every step folder that the platform keeps for itself: the marker of a downloaded or staged copy is the
  file beside the folder (`<folder>.kubecore-dataset.json`, `<folder>.kaos-ready`), never a file in it, so a step sees
  only the files of the dataset.

## 0.4.0 (unreleased)

PRD novelcore/kaos#1147 F-05, F-07, F-18 (D-03, D-13); dataset layouts: the formats become declarative,
user-definable layouts.

### Changed
- In a pipeline step the support line no longer says `Fix: pip install --upgrade ...`: nobody can install into a step's
  image. Older but supported is one neutral line; deprecated and unsupported say that the image must be rebuilt and who
  does it. `kaosctl` on a laptop keeps the upgrade command.
- `runtime.context().slot` now also carries `gpus` for a GPU step that runs alone on its HPC (Slurm) node (the platform sets
  `KUBECORE_SLOT_GPUS` there too), and `CUDA_VISIBLE_DEVICES` reaches the step as a clean list without trailing blanks.

### Added
- `kaosctl vscode install`: install or update the KAOS extension for VS Code. Every release now publishes the extension
  built from the same commit, at the same version (`0.4.0rc7` comes with extension `0.4.0-rc.7`); the command downloads
  the one of your kaos-lib, checks its SHA-256 and installs it into `code`, `cursor`, `codium` or `code-insiders`
  (`--editor`, `--download DIR`, `--dry-run`). The extension compares itself with the `kaosctl` it runs and offers
  **Update** when they differ (also **KAOS: Check for an extension update**). `kaosctl upgrade` reminds you. It is no
  longer a file handed over by hand.
- In a pipeline step the data lock is written to the MLflow run by itself when the run ends (tags `kaos_lib.data.*` and
  `data.lock.json`): the step no longer calls `lock.write()`. A failed run gets it too; a tracking problem is logged and
  never fails the step. Calling `lock.write()` yourself still works and writes nothing twice.
- Docs: the Steps guide (`docs/steps.md`, `docs/step-examples.md`, `docs/steps-and-datasets.md`): the contract between a pipeline
  step and the platform, a complete example for every kind of step, and how every step of a run reads the same pinned
  dataset. Describes the contract after the platform's breaking release (PRD-HPC-1461 D-80, D-81).
- `kaosctl render`: render `pipeline.py` on your machine with the platform's pipeline engine, the release the platform
  pinned for your app (`--context`, `--engine-wheel 'URL#sha256=...'` or `$KAOS_ENGINE_WHEEL`). The wheel is checked by its
  SHA-256 and installed into `.kaos/engine/.venv` inside the repository; the engine runs isolated from the app's folders.
  `kaosctl step run` composes the parameters with the same engine in an app that has no `kubecore/` folder (PRD
  novelcore/kaos#1461 D-79). See docs/render.md.
- `kaos_lib.progress.report(done, total, unit)`: how far a step is, for the run page. One line in the step's log
  (`KAOS_PROGRESS {...}`), at most every 10 seconds, plus MLflow tags `kaos.progress.*` when the step has an active run.
  Never fails the step. Ultralytics, PyTorch Lightning and Hugging Face Trainer report by themselves in a pipeline run,
  with or without a checkpoint folder. `KAOS_PROGRESS=0` turns it off. See docs/progress.md.
- Lint rule set `1.3.0`: L-D08 `NoCudaForGpuStep` also warns when a `gpu=True` step's Dockerfile starts from a plain (non-CUDA) base and
  sets no `ENV LD_LIBRARY_PATH` with `/usr/local/nvidia`. Still a warning. The platform adds the driver path on its own GPU
  machines (and fails a GPU step whose driver cannot be reached in its first second), so the warning is about other
  environments.
- `kaosctl lint --stdin-path pipeline.py` reads the pipeline text from standard input (an editor's unsaved buffer) and the rest
  from disk; it works with `--graph` too. Static as before. The VS Code extension (0.1.1) uses it to check as you type, and
  prints the skipped rules once instead of on every check (they are in the status bar tooltip).
- `kaosctl lint --schema` and `kaosctl lint --graph`, and the VS Code extension in `editors/vscode` (PRD novelcore/kaos#1682
  F-05, F-19, F-20). `--schema` prints what `step()` accepts (argument names, types, allowed values, docs, links, the
  arguments that were renamed) as JSON versioned with the rule set; `--graph` prints the pipeline's steps and
  dependencies as JSON, read from the file without running it. The extension shows the linter's findings in the editor,
  suggests step arguments and values, offers the `walltime=` to `hpc_time_limit=` fix, draws the step graph and signs in
  with `kaosctl login`. It is built as a local `.vsix` and is not published. No rule changed, so the rule set stays `1.1.0`.
- `kaosctl dev`, `kaosctl step run` and `kaosctl build` (PRD novelcore/kaos#1682 F-29 to F-34, D-15 to D-17, D-19): set up,
  run and build one step on your own machine, with no cluster and no login. `kaosctl` only detects, verifies and
  suggests: it never installs a container engine, `uv` or anything else, and never runs a package manager or an installer.
  - `kaosctl dev` makes `steps/<name>/.venv` for each step from what its Dockerfile installs (read, never run): `pip
    install` lines, `-r` files, Poetry steps from `poetry.lock`, `requirements.txt`, `pyproject.toml`. The Python of the
    step's base image when this machine has it, kaos-lib added to the steps that use it, a `.vscode/settings.json`
    interpreter hint per step. `uv` when present, else `python -m venv` and pip, with the link to get `uv`. Idempotent. Steps
    with large dependencies (torch, CUDA, TensorFlow) are skipped unless named or `--all`.
  - `kaosctl step run <step>` starts the step as the platform does (`python -m app.entry --params <composed params>
    --<upstream output> <json>`) in its environment, with the platform's `/work` mapped into `.kaos/local/work/<step>`, an
    allowlisted environment (no platform secret or endpoint), `--input`, `--set`, `--params-file`, and an optional small
    dataset sample (`--dataset`, `--sample-mb`) through the same client as `kaosctl dataset pull`. It prints the outputs.
  - `kaosctl build [step]` runs the Dockerfile doctor, finds and verifies an engine (Docker Engine, Docker Desktop, Colima,
    Rancher Desktop, Podman: the daemon, a test build, disk space, architecture and emulation), builds with CI's Dockerfile,
    context, `REGISTRY_URL`, `VERSION`, `KAOS_LIB_PACKAGE` and `io.kaos.lib` label for the platform's architecture, never
    pushes, and turns the engine's common errors into a message and a fix. With no usable engine it prints, for your OS, a
    free engine, the official link, the exact command to run yourself and the Docker Desktop licence note, and stops.
  - The Dockerfile doctor: eight rules `L-D01` to `L-D08` in the linter (rule set `1.2.0`), so `kaosctl lint`, the pull
    request check and `kaosctl build` report the same findings: a missing or unused `ARG KAOS_LIB_PACKAGE`, a wrong
    architecture, a `COPY` outside the build context, a missing `app/entry.py` or entrypoint, huge layers, root user, no CUDA
    for a GPU step. Guides: `docs/dev.md`, `docs/step-run.md`, `docs/build.md`, `docs/troubleshooting-build.md`, one page per rule.
- New dependency: `tomli` on Python before 3.11 (reads `pyproject.toml` and `poetry.lock`).
- The pipeline linter judges whether a step can continue from evidence, not from a guess (PRD novelcore/kaos#1682, rule
  set `1.1.0`). A step is resumable when `pipeline.py` says so, when the platform recorded that a continuation of it loaded
  its checkpoint and got past it (`hpc.resumableSteps` in the project's platform context, read by `--context`), or when its
  code uses `KAOS_CHECKPOINT_DIR`, `save_state`/`load_state` or `kaos_lib.checkpoint`. With no evidence at all `L-E01` and
  `L-W01` stay silent instead of guessing from imports. New warning `L-W05` (a step that declares `resumable=` but whose
  continuation the platform saw make no progress). The report's `catalogue` lists `resumableSteps`, and an exported
  catalogue keeps its `source`, so the gate and `kaosctl lint --context` print the same bytes.
- `kaosctl lint` and `kaos_lib.lint`: the pipeline linter (PRD novelcore/kaos#1682 F-01, F-03, D-13). It reads your
  `pipeline.py`, the `config/` tree and your step folders and reports problems the platform would refuse or that
  usually go wrong later: 7 errors (`L-E00` to `L-E06`), 5 warnings, 3 infos, each with the file range, a message, a fix
  and a link to its page in the docs. Static only: it parses your files and never imports or runs them, and needs no
  login and no network. Exit code 0 without errors, 2 with errors, 1 when it cannot run. `--format text|json|markdown`,
  `--context` (your project's platform context: the compute classes and HPC (Slurm) limits), `--catalogue`,
  `--export-catalogue`, `--from-report`, `--expect-ruleset`. A check that needs facts it does not have is reported as
  skipped, never as passed. The report carries the rule-set version (`1.0.0`, now `1.1.0`); reports of different versions are never
  mixed. Standard library and PyYAML only. The platform runs the same check on every pull request as the
  `pipeline-lint` status. Guide: `docs/lint.md`, one page per rule in `docs/lint/`.
- `kaos_lib.checkpoint`: checkpoints that survive interruptions, the same on Kubernetes and HPC. `dir()` is the
  platform's checkpoint folder (`KAOS_CHECKPOINT_DIR`; a fresh temporary folder off the platform): point any framework
  at it. `save(obj, name)` / `load(name, default)` keep your own state atomically (bytes, JSON-able data or pickles),
  `progress(n)` feeds the no-progress guard, `stop_requested()` is true on SIGTERM and SIGUSR1 and `exit_for_restart()`
  ends the step with exit code 85. Ultralytics, PyTorch Lightning and Hugging Face `Trainer` are hooked automatically
  when the step imports them (`KAOS_CHECKPOINT_HOOKS=0` turns it off). Also `register(save=, load=)` + `tick()`:
  periodic, versioned, checksum-verified checkpoints of custom state. The earlier `save(save_fn)`, `is_resume()` and
  `resume_path()` still work. Python standard library only (PRD-HPC-1461 D-44, D-74 to D-76).
- `kaos_lib.runtime`: `context().slot`, a step's share of a shared Slurm node (`Slot(gpus, cpus, mem_gib,
  shared)` from `KUBECORE_SLOT_*`, PRD-HPC-1609), and `usable_cpus()`: the cores to size worker pools by (the
  slot's, else the process's CPU binding, else the machine's).

### Fixed
- An Ultralytics run continued from its checkpoint keeps its `best.pt`: the hook saves it with `last.pt` and puts it back
  in the run directory on the continuation. Before, a new job started with an empty run directory and Ultralytics
  (which writes `best.pt` only when an epoch beats the fitness restored from `last.pt`) ended with no `best.pt`, so
  the step's best checkpoint was empty for everything after it (PRD-HPC-1461 AC-13).
- A step continued from its checkpoint no longer loses the framework's MLflow parameter logging: the continuation
  logs into the same run, and parameters that changed since the first attempt are logged as `resume.<name>` instead of
  MLflow rejecting the whole batch ("Changing param values is not allowed"; seen with Ultralytics, and the same for
  Lightning's `MLFlowLogger` and Hugging Face's `MLflowCallback`).

### Changed
- Documentation sweep: the checkpoint guide now covers `resumable=`, runs longer than the longest HPC class run and the idle limit; the Python API reference includes `kaos_lib.checkpoint`; docstrings rendered on the site no longer name platform internals; a wrong example in "Formerly kubecore" is fixed. One message changed: a peer without a public URL now says it cannot be read from outside "the platform" (was "the cluster").
- The docs and docstrings say Slurm, not MeluXina: Slurm is the kind of machine, MeluXina is today's provider.
  No API or environment variable changes.

### Added
- The documentation site (`mkdocs.yml`, `docs/`), <https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/index.html>,
  republished with every rc: guides for datasets, outputs, MLflow, the run context, the data lock and layouts, an API
  reference from the docstrings, and pages generated on every build by `docs_gen.py` (the CLI reference from the
  parser, the version, each channel's install command).
- `kaos_lib.errors.EmptyDataset`, a `DatasetError`: `materialize` raises it when the commit holds no files
  (a new project's `dataset-default`), so a step can tell "no data yet" from other dataset failures.
- `kaos_lib.mlflow`: `mlflow(tracking_uri=None, token=None)` configures the `mlflow` module and returns an
  `MlflowClient`; `token()`. One credential chain: explicit token or `$MLFLOW_TRACKING_TOKEN`, the step's machine
  key (`ZITADEL_MACHINE_KEY_FILE`, `ZITADEL_DOMAIN`, `ZITADEL_MLFLOW_PROJECT_ID`; minted with the organisation
  project's audience scope and refreshed before expiry), then the `kaosctl login` session (checked for expiry and
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
- `kaosctl run --lock <mlflow-run-id> -- <command>`: runs the command with the lock in `$KAOS_LIB_LOCK`.
- `zitadel.grant` (the whole token response, with `expires_in`) and `zitadel.env_settings`.
- `kaos_lib.layouts`: a layout is a `layout.yaml` (spec `layouts/shared/layout.schema.json`) with parameters, a
  starter skeleton (`{{placeholders}}`), declarative rules (required and allowed patterns, extensions, pairs, line
  patterns, a manifest schema), what a pull downloads, and an optional Python hook (`validate`, `materialize`).
  `layouts.load(name|path)`, `layouts.available()`, `Layout.validate/skeleton/parse/materialize/publish`.
- Sources, in lookup order: built-in (`yolo`, `raw`), installed packages (entry point group `kaos_lib.layouts`),
  the project's registry in kaos-lake (`GET /kaos/v1/dataset-templates`, from the project's `layouts`
  repository); a path is read as is.
- `kaosctl layout list|show|init|validate|publish`; `dataset create --layout <name|path> --param key=value`;
  `dataset push` validates with the layout of the repository's label.
- The schema, the built-in layouts and the test fixtures (`tests/layout_fixtures`) are shared byte for byte with
  kaos-lake, pinned by `SHA256SUMS`; both implementations pass the same fixtures.
- Guide: [Make your own dataset layout](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/reference.html#dataset-layouts).

### Changed
- The command is `kaosctl` (it was `kaos-cli`, which keeps working as a hidden alias for one release, as does
  `kubecore`).
- The `yolo` format is the built-in `yolo` layout: a declarative `layout.yaml` plus a small hook
  (`kaos_lib.layouts.yolo`: class ids, value counts, coordinates, the `data.yaml` path rewrite). Some problems are
  worded differently (`data.yaml: no file matches (required)`, `images/x.jpg has no labels/x.txt`).
- `raw` creates a README.
- `kaosctl dataset create` and `create_dataset` make an empty dataset unless a layout is named: the default layout is
  `none`, not `yolo` (owner, 2026-11-03). Name it: `--layout yolo`, or `create_dataset(name, "yolo", ...)`.
  `--classes` / `--param` without a layout is an error naming `--layout yolo`.
- `datasets.materialize(..., layout=...)` and `datasets.layout_of`; `fmt_name=`, `format_of` and
  `kaos_lib.formats.get_format` keep working.
- The cache marker records the layout's download patterns: a copy made with other patterns is fetched again.

### Unchanged
- The `kubecore` import shim and command still ship in 0.4.0: templates still import `kubecore`. Support:
  `>=0.2`, no deprecations.

## 0.3.0 (2026-11-02)

The package is renamed and moves to its own repository, `kaos-io/kaos-lib` (it was `packages/kubecore` in
`novelcore/hera-pipeline-template`; history carried over).

### Changed
- Distribution `kubecore` → `kaos-lib` (extra `kaos-lib[zitadel]`); import `kubecore` → `kaos_lib`; command
  `kubecore` → `kaosctl`. Published by the platform's CI to public Python repositories (Artifact Registry), not
  PyPI: `pip install --index-url https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib/simple/
  --extra-index-url https://pypi.org/simple/ "kaos-lib[zitadel]==0.3.0"`.
- `KubecoreError` → `KaosLibError`.
- New dependency: `packaging` (PEP 440 support checks).

### Added
- `release.json` (packaged as `kaos_lib/_release.json`, published per release in the public release bucket) and
  `kaos_lib.support.check`: verdicts current / behind / deprecated / unsupported. Pipeline steps check at import
  when `$KAOS_LIB_SUPPORT` is set; `kaosctl` warns on reads and refuses writes when unsupported.
- Release channels: prerelease `X.Y.ZrcN` (repository `kaos-lib-rc`, every merge to `main`) and stable `X.Y.Z`
  (repository `kaos-lib`, promoted by the platform's release train from a passed rc, checked to hold the rc's
  code byte for byte). `kaosctl --version` shows the channel and the targeted platform's recommendation;
  `kaosctl upgrade` installs that recommendation (kaos-lib over https only), else the newest release of the
  install's channel from the public `release.json`.
- Apache-2.0 license, project URLs, this changelog.

### Deprecated (removed in the next release)
- The `kubecore` import shim: `import kubecore` / `from kubecore import datasets` still work (the same
  `kaos_lib` modules) and emit one `DeprecationWarning`.
- The `kubecore` command: runs `kaosctl` after a note on stderr.
- The `KubecoreError` alias.

### Unchanged on purpose
- `.kubecore/dataset-config.yaml`, `~/.config/kubecore-ml/` (`$KUBECORE_ML_HOME`), the dataset cache
  `~/.cache/kubecore/datasets` with its `.kubecore-dataset.json` markers, and the `KUBECORE_*` variables: other
  platform components and existing logins and caches rely on them.

Support: `>=0.2`, no deprecations.

## 0.2.0

Last release as `kubecore` inside `novelcore/hera-pipeline-template`: datasets as lakeFS repositories, raw format,
shared datasets between projects, branch-per-run outputs.
