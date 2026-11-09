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
config/dataset.yaml:1:10: warning L-W03 UnpinnedDataset: The dataset 'dataset-default@latest' follows the newest data ...
0 errors, 1 warning, 0 infos; 2 rules skipped. Rule set 1.0.0; facts from: built-in default.
```

The exit code is `0` when there are no errors and `2` when there is at least one error. Warnings and infos never change
it. (`1` means the check could not run, for example the folder does not exist.)

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
| `--context FILE` | read the facts from your project's platform context file (`pipeline-context.yaml`) |
| `--catalogue FILE` | read them from a catalogue file; `--catalogue none` skips every check that needs one |
| `--export-catalogue FILE` | with `--context`, write the catalogue to FILE and stop |

A check that cannot run is listed under "skipped" in the report. A skipped check is never a pass.

## Other options

| option | what it does |
|---|---|
| `--format text\|json\|markdown\|status` | the output form (default `text`); `status` is one line, for a commit status |
| `--output FILE` | write the report to a file |
| `--pipeline FILE` | the pipeline file in the folder (default `pipeline.py`) |
| `--from-report FILE` | show a saved JSON report as text or markdown |
| `--expect-ruleset VERSION` | refuse to run unless the rule set is exactly this version |

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
| error | [L-E01 TooLongNotResumable](lint/L-E01.md) | a limit above the longest run, and the step cannot continue |
| error | [L-E02 TooLongBeyondContinuations](lint/L-E02.md) | a resumable step needs more runs than allowed |
| error | [L-E03 UnknownClass](lint/L-E03.md) | a pinned class your project cannot use |
| error | [L-E04 ClientIdentity](lint/L-E04.md) | your own service account, a pod patch or a reserved name |
| error | [L-E05 DependencyOrProducer](lint/L-E05.md) | a wrong `needs=`, `reads=`, name or cycle |
| error | [L-E06 RefusedArgument](lint/L-E06.md) | a `step()` argument the library refuses |
| warning | [L-W01 LongGpuStepNotResumable](lint/L-W01.md) | a long GPU step that cannot continue |
| warning | [L-W02 IdleTimeoutOff](lint/L-W02.md) | the idle limit turned off |
| warning | [L-W03 UnpinnedDataset](lint/L-W03.md) | a dataset reference that follows `@latest` |
| warning | [L-W04 NoMlflowOrModelNotRegistered](lint/L-W04.md) | no MLflow logging, or no registered model |
| info | [L-I01 NodeSharing](lint/L-I01.md) | a GPU step with no limit cannot share a node |
| info | [L-I02 LearnedLimits](lint/L-I02.md) | a short limit may be shortened further |
| info | [L-I03 Schedules](lint/L-I03.md) | not active yet |

## Install

The linter ships in `kaos-lib` and needs only its standard dependencies: see [Install](install.md).
