# Check your pipeline (`kaosctl lint`)

`kaosctl lint` reads your pipeline's `pipeline.py` and the files around it and tells you about problems the platform
would refuse, or that usually go wrong later, **before** you open a pull request. It never runs your code: it parses
your files as text. It needs no login and no network.

```bash
cd my-app                 # the folder that holds pipeline.py
kaosctl lint              # a report for the terminal
kaosctl lint --format json   # the same report for tools
```

Example:

```text
pipeline.py:7: error L-E05 DependencyOrProducer: Step 'evaluate' needs 'train', which is defined after it ...
    fix: Move the line that defines 'train' above this step.
    docs: .../lint/L-E05.html
steps/train/app/entry.py:7:7: warning L-W03 DatasetVersionInCode: This string names a dataset and a version ...
0 errors, 1 warning, 0 infos; 2 rules skipped. Rule set 2.0.0; facts from: built-in default.
```

The exit code is `0` when there are no errors and `2` when there is at least one error. Warnings and infos never change
it. (`1` means the check could not run, for example the folder does not exist.)

## Fix what can be fixed for you

```bash
kaosctl lint --fix
```

rewrites `pipeline.py` for the step contract of kaos-lib 0.5 and then checks as usual: it renames `hpc_time_limit=`
to `walltime=`, removes `outputs=`, gives every step without a `kind=` a placeholder, and removes the `platform`
line from the defaults of `config/config.yaml`. The placeholder lists the
six kinds and is not one of them, so the check keeps failing until you choose: `--fix` never chooses a kind for you.
Nothing else in the file is touched. If a change would leave a file that is not valid Python, `--fix` writes nothing to that file, says so and exits non-zero: make that change by hand. [Move to kaos-lib 0.5](migrate-to-0.5.md) has the rest of the change.

## The same check on your pull request

When you open a pull request, the platform runs this same check and reports it as the `pipeline-lint` status on the
pull request, with one comment that is updated on every push. Errors make the status fail; warnings and infos do not.
The report is identical to the one you get locally for the same files, project facts and rule set version.

## Project facts: classes and limits

Some checks need facts about your project: which compute classes you can use, and the longest run of the HPC (Slurm)
site. On the pull request they come from your project. Locally, give them with a file:

| option | what it does |
|---|---|
| (none) | built-in defaults: the longest run is 2 days, a resumable step continues at most 5 times, no list of classes. The check that needs your classes (`L-E03`) is reported as **skipped** |
| `--context FILE` | read the facts from your project's platform context file (`pipeline-context.yaml`): the compute classes, the HPC (Slurm) limits and the platform's resumable-step record |
| `--catalogue FILE` | read them from a catalogue file; `--catalogue none` skips every check that needs one |
| `--export-catalogue FILE` | with `--context`, write the catalogue to FILE and stop |

A check that cannot run is listed under "skipped" in the report. A skipped check is never a pass.

## Evidence from the platform

Whether a step can continue after an interruption is not something to guess from its imports. The checks that depend on it
(`L-E01`, `L-W01`, `L-W05`, and the continuation count of `L-E02`) use evidence, in this order:

1. **What `pipeline.py` says:** `resumable=True` (or a lead time) is resumable, `resumable=False` is not.
2. **What the platform recorded.** On the HPC (Slurm) site the platform notes, per step, whether a continuation loaded its
   checkpoint and got past it. A step with such a record is *verified resumable*; a step whose continuation did not get past
   its checkpoint is recorded as not resumable, with a reason such as `NoProgress`. Your project's platform context carries
   this list (step name, verdict, when, reason: nothing about the jobs), so the pull request check uses it, and so does
   `kaosctl lint --context FILE`.
3. **What the step's code shows:** it uses `KAOS_CHECKPOINT_DIR`, `save_state` or `load_state`, `kaos_lib.checkpoint`, or a
   framework the library hooks for checkpoints (Ultralytics, PyTorch Lightning, Hugging Face).
4. **Nothing.** With no declaration, no record and no checkpoint use in its code, the step is simply not judged: the
   checks that need to know say nothing, rather than guess.

The evidence the run used is part of the report (the `catalogue` section, `resumableSteps`), so a report always shows what
it was judged on.

## Other options

| option | what it does |
|---|---|
| `--format text\|json\|markdown\|status` | the output form (default `text`); `status` is one line, for a commit status |
| `--output FILE` | write the report to a file |
| `--pipeline FILE` | the pipeline file in the folder (default `pipeline.py`) |
| `--from-report FILE` | show a saved JSON report as text or markdown |
| `--expect-ruleset VERSION` | refuse to run unless the rule set is exactly this version |
| `--stdin-path FILE` | read the content of the pipeline file from standard input instead of from disk (FILE must be the pipeline file, `pipeline.py`); everything else is still read from disk. For editors that check unsaved text. The text is parsed, never run, and with the saved text the report is byte for byte the same as without the option |
| `--schema` | print what `step()` accepts (argument names, types, allowed values, docs and links) as JSON, with the rule set version, and stop. Editors read it for suggestions and hover text |
| `--graph` | print your pipeline's steps and what each one needs as JSON, read from the file without running it, and stop. Editors draw it. A step built in a loop or a condition is marked `dynamic` |

## In your editor

The KAOS extension for VS Code shows the findings in the file as you type, suggests `step()` arguments and values,
and draws the step graph. Install the one published with your kaos-lib:

```bash
kaosctl vscode install
```

It has the same version as your `kaosctl`; after `kaosctl upgrade` it offers to update itself. Its README
(`editors/vscode` of the kaos-lib repository) has the details.

## The report

JSON, with: `ruleset_version`, the `catalogue` the run used, a `summary`, the `findings` and the `skipped` checks. Each
finding has `rule`, `name`, `level` (`error`, `warning` or `info`), `file`, `range` (1-based `start` and `end` with
`line` and `column`; the end column is exclusive), `message`, `fix` and `doc` (the link to the rule's page). The
rule set version changes when a rule or a threshold changes; reports of different versions are never mixed.

## What it cannot tell you

It reads files. A value built at run time (a loop, a function call, a variable) cannot be judged, so the check stays
silent about it rather than guess. A clean report does not prove the pipeline is right; the platform still checks at
render and when a step is submitted.

## The checks

| | rule | what it finds |
|---|---|---|
| error | [L-E00 NotAnalysable](lint/L-E00.md) | the file cannot be read |
| error | [L-E01 TooLongNotResumable](lint/L-E01.md) | a limit above the longest run, and the step is known not to continue |
| error | [L-E02 TooLongBeyondContinuations](lint/L-E02.md) | a resumable step needs more runs than allowed |
| error | [L-E03 UnknownClass](lint/L-E03.md) | a pinned class your project cannot use |
| error | [L-E04 ClientIdentity](lint/L-E04.md) | your own service account, a pod patch or a reserved name |
| error | [L-E05 DependencyOrProducer](lint/L-E05.md) | a wrong `needs=`, `reads=`, name or cycle |
| error | [L-E06 RefusedArgument](lint/L-E06.md) | a `step()` argument the library refuses |
| error | [L-E07 StepDeclaration](lint/L-E07.md) | a step without a `kind`, or with a wrong `inputs=` or `produces=` |
| error | [L-E08 StepNotMoved](lint/L-E08.md) | a step whose code is still written for kaos-lib 0.4 |
| error | [L-E09 PlatformConfigGroup](lint/L-E09.md) | the `platform` group still in the app's config |
| warning | [L-W01 LongGpuStepNotResumable](lint/L-W01.md) | a long GPU step known not to continue |
| warning | [L-W02 IdleTimeoutOff](lint/L-W02.md) | the idle limit turned off |
| warning | [L-W03 DatasetVersionInCode](lint/L-W03.md) | a dataset version written in step code |
| warning | [L-W04 NoMlflowOrModelNotRegistered](lint/L-W04.md) | no MLflow logging, or no registered model |
| warning | [L-W05 DeclaredResumableDidNotResume](lint/L-W05.md) | a step declared resumable restarted from zero on the platform |
| error | [L-D01 MissingKaosLibArg](lint/L-D01.md) | a step uses kaos-lib but its Dockerfile has no `ARG KAOS_LIB_PACKAGE` |
| error | [L-D02 KaosLibNotInstalled](lint/L-D02.md) | the step imports kaos_lib but nothing installs `${KAOS_LIB_PACKAGE}` |
| error | [L-D03 WrongArchitecture](lint/L-D03.md) | a `FROM --platform=` other than linux/amd64 |
| error | [L-D04 CopyOutsideContext](lint/L-D04.md) | a `COPY` source the build cannot read |
| error, warning | [L-D05 StepContract](lint/L-D05.md) | no `app/entry.py` (error); no `python -m app.entry` entrypoint (warning) |
| warning | [L-D06 HugeLayers](lint/L-D06.md) | `COPY . .`, baked-in data, pip without `--no-cache-dir`, apt without cleanup |
| info | [L-D07 RootUser](lint/L-D07.md) | the image runs as root |
| warning | [L-D08 NoCudaForGpuStep](lint/L-D08.md) | a GPU step whose image shows no CUDA support, or whose plain base sets no NVIDIA driver path |
| info | [L-I01 NodeSharing](lint/L-I01.md) | a GPU step with no limit cannot share a node |
| info | [L-I02 LearnedLimits](lint/L-I02.md) | a short limit may be shortened further |
| info | [L-I03 Schedules](lint/L-I03.md) | not active yet |

The `L-D` rows are the **Dockerfile doctor**: they read each step's `Dockerfile` (never build it) and run in the same
check, so the pull request check, `kaosctl lint` and `kaosctl build` print the same findings. See
[Build a step image](build.md).

## Install

The linter ships in `kaos-lib` and needs only its standard dependencies: see [Install](install.md).
