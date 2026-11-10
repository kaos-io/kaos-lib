# Changelog

All notable changes to kaos-lib. Versions follow PEP 440; each release's support window is in its
`release.json`. Packages: `https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib/simple/` (stable),
`.../kaos-lib-rc/simple/` (prerelease).

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
- Guide: [Make your own dataset layout](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/make-your-own-layout.html).

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
