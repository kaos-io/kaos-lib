# Lint checks

`kaosctl lint` reads `pipeline.py`, `config/` and the step folders as text and tells you what the platform would refuse,
or what usually goes wrong later. It runs none of your code and needs no login and no network.

```bash
kaosctl lint                    # a report for the terminal
kaosctl lint --format json      # the same report for tools
```

```text
pipeline.py:19:15: error L-E07 StepDeclaration: Step 'prepare' has no kind=, which every step declares: ...
    fix: Give every step a kind, name its dataset inputs in inputs=[...] and what it writes in produces=[...].
    docs: https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/lint/L-E07.html
0 errors, 0 warnings, 2 infos; 2 rules skipped. Rule set 2.1.0; facts from: built-in default.
```

The exit code is `0` without errors, `2` with at least one, and `1` when the check could not run. The platform runs the
same check on every pull request, and an error fails it. Warnings and infos never do.

## Project facts

Some checks need facts about your project: its compute classes and the longest run of its Slurm site. On a pull
request they come from your project. Locally, a check that lacks them is listed as `skipped`: never as passed.

| option | does |
|---|---|
| (none) | built-in facts: the longest run and the continuations of [the limits](contract.md#the-limits), no list of classes |
| `--context FILE` | reads the facts from your project's context file |
| `--catalogue FILE`, `--catalogue none` | reads them from a catalogue file, or skips every check that needs one |
| `--export-catalogue FILE` | with `--context`, writes the catalogue and stops |

Whether a step can continue after an interruption is judged in this order: what `pipeline.py` says (`resumable=`), what the
platform recorded for the step on the Slurm site, what the step's code shows (`kaos_lib.checkpoint`, a hooked framework),
and otherwise nothing: a check that needs to know stays silent rather than guess.

## Options

| option | does |
|---|---|
| `--format text\|json\|markdown\|status` | the output form; `status` is one line |
| `--output FILE` | writes the report to a file |
| `--pipeline FILE` | the pipeline file (default `pipeline.py`) |
| `--from-report FILE` | shows a saved JSON report |
| `--expect-ruleset VERSION` | refuses to run unless the rule set is exactly this version |
| `--stdin-path FILE` | reads the pipeline file's text from standard input, for editors |
| `--schema` | prints what `step()` accepts as JSON and stops |
| `--graph` | prints the steps and what each needs as JSON and stops |

The report is JSON: `ruleset_version`, `catalogue`, `summary`, `findings` (`rule`, `name`, `level`, `file`, `range`,
`message`, `fix`, `doc`) and `skipped`. The KAOS extension for VS Code shows the findings as you type: `kaosctl vscode install`.

A value built at run time (a loop, a call) cannot be judged, so the check stays silent about it. A clean report does not
prove the pipeline is right.

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
| error | [L-E07 StepDeclaration](lint/L-E07.md) | a step without a `kind`, a folder or a valid name, or with a wrong `inputs=` or `produces=` |
| error | [L-E08 OldStepCode](lint/L-E08.md) | code from before the current pipelines: a copy of the platform's pipeline code, `--params`, old environment variables |
| error | [L-E09 PlatformConfigGroup](lint/L-E09.md) | the `platform` group in the app's config |
| warning | [L-W01 LongGpuStepNotResumable](lint/L-W01.md) | a long GPU step known not to continue |
| warning | [L-W02 IdleTimeoutOff](lint/L-W02.md) | the idle limit turned off |
| warning | [L-W03 DatasetVersionInCode](lint/L-W03.md) | a dataset version written in step code |
| warning | [L-W04 NoMlflowOrModelNotRegistered](lint/L-W04.md) | no MLflow logging, or no registered model |
| warning | [L-W05 DeclaredResumableDidNotResume](lint/L-W05.md) | a step declared resumable restarted from zero on the platform |
| warning | [L-W06 TrainTimeLimitNotResumable](lint/L-W06.md) | a training step with a time limit that is not resumable |
| warning | [L-W07 DatasetProducerStaysOnCluster](lint/L-W07.md) | a GPU step that produces a dataset runs on the cluster, not on HPC |
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
| info | [L-I04 StepsBuiltInALoop](lint/L-I04.md) | steps built in a loop were not read by the checks |
| info | [L-I03 Schedules](lint/L-I03.md) | skipped in every report: a pipeline cannot declare a schedule |

The `L-D` rows read each step's `Dockerfile`, never build it. `kaosctl build` prints the same findings.
