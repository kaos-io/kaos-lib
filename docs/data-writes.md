# What a run writes

## What a step writes

A step writes what it declares in `produces=`, into the folder `step.output("<name>")` gives it. What the folder holds when
`step.result()` runs is what is saved.

| declared as | what it is | where it is kept |
|---|---|---|
| `dataset("name")` | a version of a dataset | the dataset `dataset-<app>-<name>` |
| `model("name")` | files of one run: weights | the repository `outputs-<app>`, under `<name>/<experiment>/<run>/` |
| `artifact("name")` | files of one run: a report, plots, a table | the same place |

A step with `matrix=` writes each output once for each item, under `<name>/<experiment>/<run>/<index>/`: one model or artifact name, one version for each item, with the item's number and values on the version ([Sweeps](sweeps.md)).

Only the app that declares a dataset in `produces=` writes it. People and other pipelines read it. A step that tries to
write anything it did not declare is refused: `this app may not write dataset-...: only what the step declares in
produces=[...] in pipeline.py can be written.`

## What is saved, and when

Nothing is saved before every output has passed its checks. `step.result()` first checks each output: it was written, it
is not empty, a dataset output holds no file under `.kaos/`, and it passes its `step.check`. If one fails, it saves
nothing. A step that fails before it calls `step.result()` (an exception, `SystemExit`, a crash) saves nothing either: until
then the output folders are only files on the step's machine, and the step hands on no result.

Once the checks pass, `step.result()` saves in two stages, and a failure in a stage can leave something behind:

1. **Seal.** Every output is uploaded and checked, and no model, artifact or `latest` changes. A failure here changes
   nothing that anyone reads, except that a dataset version already sealed for an earlier output of the same step stays in
   its dataset, kept under a name that starts `k-` and the time it was sealed, followed by the run and the step. It is not
   `latest`.
2. **Promote.** Models and artifacts are saved. When that fails, a model or artifact that was already saved stays under its
   folder `<name>/<experiment>/<run>/`; no result refers to it. A dataset is never promoted by its step: its `latest`
   moves once, when the run ends and every step went well ([below](#when-latest-moves)).

In every case the step fails and hands on no result, so the steps that need it do not start. [When a step is run
again](#when-a-step-is-run-again) says what a retry does with it.

## One sealed version for each run

When a step that makes a dataset calls `step.result()`, its files become one new version of the dataset. The version is
sealed: it never changes. It is kept under a name, `k-<time>-<run>-<step>-<12 characters of the id>`, where the time is
when the step sealed it, such as `20261112T093015Z`. The log says it: `kept as ...`.

| the step | the id of the write |
|---|---|
| made new files | the version that was made, whether or not the run moves `latest` at its end |
| made the same files as the last version | the last version: no new version exists |

The steps after it in the same run read exactly that version, whether or not `latest` moves.

### Unchanged content makes no new version

A step that writes exactly the files of the last version makes no new version, and says so:
`output 'clean': the same content as the last version of dataset-myapp-clean (b2e7b6573672); no new version.`

### Only the difference is uploaded

A new version shares every file that did not change with the last version (`latest`), and a run uploads only the files that
changed. A run that does not move `latest` also does not upload what the last run sealed: a file with the same path, size
and content as in the newest version an earlier run sealed is copied inside the data store, not uploaded. Every run still
gets its own version.

The log says how many files were uploaded, how many were unchanged and how many were reused:
`output 'clean': 1 file(s) to upload, 0 to delete, 2 unchanged since the last version of dataset-myapp-clean.` or, after
an earlier run that did not move `latest`, `output 'clean': 0 file(s) to upload, 0 to delete, 0 unchanged since the last
version of dataset-myapp-clean, 201 reused from an earlier run (copied, not uploaded).` If a file cannot be copied, the
step uploads it and says so: `output 'clean': 1 of the 201 file(s) could not be copied and were uploaded.`

Keep each file at the same path from run to run, so that it counts as unchanged. An output of less than 1 MiB to upload is
simply uploaded.

## When `latest` moves

A step only makes its version. `latest` moves once, at the end of the run, and only when the whole run went well. A run that
does not ask still makes its version, and leaves `latest` where it was, so an experiment never changes what other pipelines
read.

You write nothing for it. The platform adds one field `promote-<name>` to the run form for every `dataset("<name>")` in
`produces=` (`promote-clean` for `dataset("clean")`). The person who starts the run picks `true` or `false`, and the default
is `false` ([how to ask](flow-datasets.md#move-latest)).

`latest` moves once, at the end of the run, only if every step succeeded or was skipped, for every dataset whose field is
`true`. A run that fails moves nothing. Every version the run made stays readable by its exact version.

| the run | the version it made | `latest` |
|---|---|---|
| `promote-clean` is `true`, and every step succeeded or was skipped | new | moves to it, at the end of the run |
| `promote-clean` is `true`, and a step failed | new, kept | stays |
| `promote-clean` is `false` | new, kept | stays |
| the step wrote the same files as `latest` already holds | none: the existing version is reused | unchanged |
| the step that makes the dataset was skipped | none | unchanged |
| another run promoted the same dataset while this one ran | new, kept | stays: this run is refused at its end and fails, naming the dataset |

**All or nothing.** When a pipeline makes two datasets and both fields are `true`, the run moves both `latest` names, or neither. At
the end of the run the platform first checks every dataset whose field is `true`: its `latest` must still be the version the step started
from. If one has moved, the run moves none and fails, naming the dataset that moved. Every version the run made is kept.
Then it moves them all. Steps skipped with a condition or with `step.skip()` make nothing, so their datasets are not moved,
and the log of the run says so. The one exception is a cut-short end of the run ([below](#if-the-end-of-the-run-is-cut-short)).

> The word *promote* means two things in a pipeline. The run-form field `promote-<name>` moves the `latest` of a dataset. A
> setting such as `registration-promote_to` in a template gives a model an alias in the registry. They are separate: the
> second never moves a dataset's `latest`.

### When two runs write at once {#when-two-runs-write-at-once}

A dataset has one `latest`. When two runs of the same pipeline overlap and both ask to move it, the first to finish moves
it. **The second is refused whole, at the end.** It finds that `latest` has moved while it was running, and it fails with a
message that says which datasets it promoted (there can be some, when it was overtaken between two of them), which one was
moved by the other run, and which were not tried. A dataset the other run moved is not moved by this one. Every version
this run made stays kept, and you can read it by its exact version. Start a new run to promote the datasets it names: the
new run starts from the new `latest`. Only one pipeline writes a dataset, so this needs two runs of the same pipeline at
the same time.

### If the end of the run is cut short {#if-the-end-of-the-run-is-cut-short}

Moving two or more `latest` names is two or more actions, and one of them can fail after another succeeded (the data store
is not reachable, or another run moved a dataset in the instant between the check and the move). Then the datasets that
were already moved stay moved, and the others do not. The run fails and the message names both lists, and says whether
trying again can help. Nothing is lost: every version the run made is kept. After an outage the platform tries the last
task again by itself, and a dataset that this run already moved is recognised (even when another run has moved it again
since) and left alone. When another run moved a dataset, trying again cannot finish it: start a new run to promote the
datasets the message names.

## When a step is run again

The platform runs a step again when its machine was lost or its time limit was reached ([Long jobs](long-jobs.md)). Each
attempt starts with empty output folders, and only the attempt that ends with `step.result()` makes the result. What a
retry does with what it writes:

| output | what the retry does |
|---|---|
| a dataset | seals its version again. If the files are exactly the ones an earlier attempt of this step already sealed, that version is used: no second version. The version keeps the name `k-<time>-<run>-<step>-<12 characters of the id>` |
| a model or an artifact | replaces the folder `<name>/<experiment>/<run>/` with exactly what the retry wrote; a file of the earlier attempt that the retry did not write is gone |

So a retry writes each output once. If `latest` moved while the step was away (another run moved it), the retry seals on the
new `latest` and does not reuse the older seal. Models and artifacts are not shared between runs: each run keeps its own
folder.

## Models and artifacts

A model or an artifact is files of one run. It is kept in the repository `outputs-<app>`, in a folder for each run:
`<name>/<experiment>/<run>/`. `<name>` is the name in `produces=`, the experiment is the setting `experiment.name`, and the
run's name is on the run page. Each run has its own folder, so a later run never overwrites it. Models and artifacts never
move a `latest`: nothing refers to them but the result of the step that made them.

Download one with `kaosctl dataset pull outputs-<app>@main ./results --prefix <name>/<experiment>/<run>/`
([See your results](see-your-results.md#the-files-of-a-run)).

The names you give are the names in `produces=` ([the rules for names](contract.md#names)). An MLflow experiment or a
registered model that a step creates is named `<app>` or `<app>.<something>`, with the name of the app first: the platform
accepts a step's writes to the project's MLflow only under the names of its own app.

Next: [What is kept, and for how long](data-retention.md).
