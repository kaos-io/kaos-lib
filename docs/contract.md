# Your contract with the platform

This is the one page that says what you write, what the platform does for you on every run, what a step receives and
must return, what the run form offers, what the platform refuses, what is guaranteed, and what is not promised today.
Every rule here is checked by `kaosctl lint`, by the platform when it builds the pipeline or starts the run, or by the
library when the step runs. The other pages teach; this one states.

The contract has three parts. This page is the first. The second says what each [step type](step-types.md) must and may
do. The third is [the data contract](data-contract.md): datasets, versions, what a run reads and writes, and what is kept.

- [What you write](#what-you-write)
- [What the platform does on every run](#what-the-platform-does-on-every-run)
- [What a step receives and must return](#what-a-step-receives-and-must-return)
- [The run form](#the-run-form)
- [What the platform refuses](#what-the-platform-refuses)
- [What is guaranteed](#what-is-guaranteed)
- [What is not promised today](#what-is-not-promised-today)
- [What you can add](#what-you-can-add)
- [The limits](#the-limits)

## What you write

An app is a repository with four kinds of file. You write these and nothing else.

| you write | what it is | the rules |
|---|---|---|
| `pipeline.py` | the steps, what each one reads and makes, and their order | one pipeline per app. A step is `step(name, kind=..., ...)`. Define a step above the steps that need it (`L-E05`). No `outputs=`, `hpc_time_limit=` or `disk=` (`L-E06`). A pipeline cannot declare a schedule |
| `steps/<folder>/app/entry.py` | the code of one step | started as `python -m app.entry`, with no arguments. It calls `step.start()` first and `step.result()` last |
| `steps/<folder>/Dockerfile` | the image of one step | keeps the line `ARG KAOS_LIB_PACKAGE` and installs `${KAOS_LIB_PACKAGE}` (`L-D01`, `L-D02`); no `--platform=` other than `linux/amd64` (`L-D03`); `COPY` only files inside the step's folder (`L-D04`) |
| `config/*.yaml` | the settings | `config/config.yaml` lists the files that are read. Every plain value is a field on the run form. A top-level text value that holds a dataset reference is an input. No key `plan` or `pipeline-version`, and no `platform` group (`L-E09`) |

### The step name and its folder

A step's folder is `steps/` plus the step's name with every hyphen written as an underscore.

| the step | its folder |
|---|---|
| `step("prepare", ...)` | `steps/prepare/` |
| `step("hello-world", ...)` | `steps/hello_world/` |
| `step("model-eval", ...)` | `steps/model_eval/` |

A folder with the hyphen, `steps/model-eval/`, is not found. The folder holds the `Dockerfile` and `app/entry.py`. A step
without its folder is refused, and the message names the folder to create (`L-E07`).

### Names

| what | the rule |
|---|---|
| a step, an input and a name in `produces=` | lowercase letters, digits and hyphens, not starting or ending with a hyphen, at most 40 characters, not starting with `kaos-` |
| the name of a dataset a step makes | the same, and at least 3 characters |
| the dataset and the app together | the dataset is `dataset-<app>-<name>`, and `<app>-<name>` has at most 48 characters; an app name has at most 55 |
| step names the platform keeps | `main`, `hpc-follower`, every name that ends in `-hpc`, and a few more that the refusal lists |
| a name in the values of `step.result(...)` | does not start with `kaos-` |
| a settings key | not `plan`, not `pipeline-version`; no top-level `platform` group |
| a folder at the root of a dataset you make | `.kaos/` is the platform's: a dataset output that holds a file there is refused |
| a branch or a tag in a dataset you make | `run-*` branches and `k-*` and `keep-*` tags are the platform's ([what is kept](data-retention.md)) |

## What the platform does on every run

1. **It checks the pipeline.** On every pull request it runs the checks of `kaosctl lint` and builds `pipeline.py`. A
   check that fails stops the pull request, with the sentence of [what the platform refuses](#what-the-platform-refuses).
2. **It builds your steps.** The merge builds an image for each step whose own folder changed, with the version of
   kaos-lib the platform chooses (that is why `ARG KAOS_LIB_PACKAGE` stays). A run uses the images the platform built.
   They are on the run form as the fields `image-<step>`, set by the platform: do not change them.
3. **It reads the run form.** The values you gave and the settings of `config/` become the settings of the run. A value
   that cannot work (a time limit that is not minutes or hours, a class the step is not offered) refuses the run before
   the first step, with a sentence that names the field.
4. **It pins every input to one exact version.** Each dataset choice on the form becomes one version, once, before the
   first step. Every step of the run reads that version, even if `latest` moves while the run is going
   ([what a run reads](data-reads.md)).
5. **It starts each step with one context.** After the steps it needs, on the machine class you chose, with its time
   limit. The context holds the run, the app, the project, the step and its kind, the experiment, the settings of the
   sections in `reads=`, the exact version of each input, what the step declared in `produces=`, and the results of the
   steps in `needs=`. It costs at most 96 KiB.
6. **It collects one result from each step.** What the step hands on with `step.result(...)` reaches the steps that need
   it. A step that ends without a result fails, and the steps that need it do not start.
7. **It records what was read and written.** The result of every step lists the exact version of each dataset it read
   and of everything it wrote ([which data made this model](data-reads.md#which-data-made-this-model)).
8. **It runs a step again when the machine was lost** or the time limit was reached and the step can continue
   ([when a step ends](reference.md#when-a-step-ends)).
9. **It moves `latest` once, at the end.** Only when every step went well, and only for the datasets whose
   `promote-<name>` the person who started the run set to `true` ([what a run writes](data-writes.md#when-latest-moves)).
10. **It keeps some things and removes others, on a schedule** ([what is kept, and for how long](data-retention.md)).

The same step code runs on the platform's own machines and on HPC (Slurm): the command, the context and the result are the
same. The step never names a place.

## What a step receives and must return

A step gets one context and hands back one result. `from kaos_lib import step` reads the one and writes the other. Your code
reads no environment variable. Every failure is a `StepError` with a message that says what to change, and the step fails.

| call | what it gives you | what you must do | what happens if you do not |
|---|---|---|---|
| `step.start()` | the step: `run`, `app`, `project`, `step`, `kind`, `experiment`, `params` (the sections of `reads=`), `produces` | call it first. A second call returns the same step. Keep an input and an output of one step under different names | any other call before it: `call step.start() first.` Outside a run: `ERROR: this is not a pipeline step: KAOS_STEP_CONTEXT is not set. Run the step with: kaosctl step run <step>` and exit code 1. A context that cannot be read: `ERROR: the step context ...` on one line, exit code 1. An input and an output of one name: the pipeline is refused when it is built, and a step that still has one fails in `start()` |
| `step.input(name, optional=False, writable=False)` | a read-only folder: a dataset the run pinned (`inputs=`), or a dataset, model or artifact a step in `needs=` made | name it in `inputs=`, or make a step that produces it a `needs=`. Do not write into the folder. Ask for `writable=True` for a private copy that costs the dataset's size in disk and time | `'x' is not an input of step 'y'. Its inputs are: ... Add it to inputs=[...] in pipeline.py.` A needed step that did not run: `input 'x' of step 'y' is not there, and ... did not run or was skipped` (`optional=True` returns `None`). A dataset with no files: `input 'x': dataset-... holds no files at the version this run read (...).` A version that no longer exists: `input 'x': commit ... of dataset-... does not exist any more.` |
| `step.output(name)` | an empty folder for an output you declared | declare it in `produces=`. Write at least one file into it before `step.result()` | `'x' is not produced by step 'y'. It produces: ... Add it to produces=[...] in pipeline.py.` An output never asked for: `output 'x' was not written: ...`. An empty one: `output 'x' is empty: ...`. A folder that is a link: `output 'x': ... is a link, and the folder must be a real folder.` Nothing is saved |
| `step.upstream(step, optional=False)` | the result of a step in `needs=`: `values`, `reads`, `writes` | name the step in `needs=` | `step 'x' is not upstream of 'y'. Add needs=['x'] in pipeline.py.` A step that did not run or was skipped: `step 'x' did not run, so it left no result, and 'y' needs it.` (`optional=True` returns `None`) |
| `step.skipped(step)` | the reason an earlier step gave to `step.skip()`, `""` when it did not run, `None` when it ran | name the step in `needs=` | `step 'x' is not upstream of 'y'.` |
| `step.check(name, layout=None, min_files=1)` | nothing: a condition on an output, checked inside `step.result()` | call it before `step.result()` | `output 'x' failed its check:` and what failed, then `Nothing was saved.` |
| `step.workdir()` | a scratch folder, emptied at each attempt, never saved | use it for files that are neither an input nor an output | nothing |
| `step.result(**values)` | nothing. It checks and saves every output, then writes the result | call it once, last. Hand on only text, numbers, booleans, lists and objects, under names that do not start with `kaos-`. The whole result may cost 8 KiB | a step that ends without it: `ERROR: step 'x' ended without step.result(): the next step would get nothing. Call step.result() as the last line.` A bad value: `result value 'k' is a ...`. Too big: `the result costs N; the limit is 8192.` A file under `.kaos/` in a dataset: `output 'x' holds a file in .kaos/`. A dataset another app declares: `this app may not write dataset-...: only what the step declares in produces=[...] in pipeline.py can be written.` A second call: `step.result() was already called.` |
| `step.skip(reason)` | nothing: it writes a skipped result, saves no output and ends the step with exit code 0. The steps that need it still run | give a reason of 1 to 300 characters | `step.skip() needs the reason, as text`; `the reason of step.skip() has N characters; the limit is 300`; `step.result() or step.skip() was already called.` |

`step.result()` checks every output before it saves any: written, not empty, nothing under `.kaos/`, and each
`step.check`. If one fails, nothing is saved. [What a run writes](data-writes.md#what-is-saved-and-when) says what a step
that fails half-way can leave behind.

## The run form

Every field of the run form is made by you or by the platform, and every value is set by the person who starts the run.
This table says, for each field: who makes it, who sets its value and when, and the default.

| field | who makes it | who sets the value, and when | default, and where it comes from |
|---|---|---|---|
| `experiment-name` and the other `experiment-*` fields | you, in `config/experiment.yaml` | whoever starts the run, on the form | the value in the file |
| `<section>-<key>`, one for each plain value | you, in the files of `config/` listed in `config/config.yaml`. A list is not a field. The comment next to the value is the text of the field | whoever starts the run, on the form | the value in the file |
| a dataset field, named like the input | you: a top-level value in `config/` that `inputs=` names | whoever starts the run picks one of your project's datasets and versions. The platform pins it to one exact version when the run starts | the reference in the file |
| `<step>-class` | the platform, for every step. You choose what it offers with `gpu=True` | whoever starts the run. A class the form does not offer is refused before the first step. GPU classes only with `gpu=True`; HPC (Slurm) classes only for a step that may run there ([where it runs](step-types.md)) | the step's default class, chosen by the platform |
| `<step>-walltime` | the platform, for every step | whoever starts the run. Minutes or hours (`90`, `90m`, `12h`), at least one minute, at most 30 days, longer than the lead of `resumable=` | `walltime=` on the step, else `4h` |
| `<step>-checkpoint-every` | the platform, for a step that declares `checkpoint_every=` | whoever starts the run. Minutes or hours | `checkpoint_every=` on the step |
| `promote-<name>` | the platform, one for each `dataset("<name>")` in `produces=`. You write nothing for it | whoever starts the run picks `true` or `false`. `true` asks the run to move `latest` of that dataset at its end | `false`, set by the platform |
| the fields a `when=` names | you: a `when=` names a field that is on the form (any field above), or a value of a step in `needs=` | whoever starts the run sets the field. A `when=` on a field the form does not have is refused | the default of the field it names |
| `<step>-matrix`, `<step>-parallel` | a step that runs many times: see [Sweeps](sweeps.md) | see that page | see that page |
| `config` | the platform, always: "Extra settings for this run, as YAML" | whoever starts the run. At most 16 KiB. It replaces the values above | empty |
| `image-<step>` | the platform, always | the platform, when it builds your steps. Do not change | the image the platform built |

## What the platform refuses

A refusal is one sentence that names the step and says what to do. `...` stands for a name or a number that is yours.
`kaosctl lint` reports the first group before you push. The platform reports the first and second when it builds the
pipeline, and the third when a run starts.

### When you push, and when the pipeline is built

| you see | it means | do this |
|---|---|---|
| `step 'x': outputs= is gone. Declare what the step writes with produces=[...] and hand it on with step.result().` | `outputs=` is gone | declare what a step makes in `produces=`, and hand values on with `step.result(...)` |
| `step 'x': hpc_time_limit= is gone. Use walltime=, for example walltime="12h".` | `hpc_time_limit=` is gone | write `walltime="12h"` |
| `step 'x': disk= is gone. The step gets the disk of the machine class it runs on.` | a step is not told its disk | pick a bigger class on the run form |
| `L-E06 ... when='...' is not a condition the platform can read. A condition compares one name with a text, with == or != and nothing else`, or `... names 'x', which is not a field of the run form` | `when=` is not a name, `==` or `!=`, and a text, or the field is not on the run form | write `when="mode != off"` or `when="evaluate.passed == true"`: [Conditions and skipping](conditions-and-skipping.md) |
| `L-E06 ... when= reads a value of step 'x', which this step does not need` | the step `x` is not in `needs=` | add it to `needs=` |
| `L-E06 ... when= is written with plain names, not with {{...}}` | `when=` has the `{{workflow.parameters.<field>}}` form | write the field's name instead |
| `Step 'x' has no folder steps/x_y/. The folder of a step is steps/ plus the step's name with every hyphen written as an underscore` | the step's folder is missing or has a hyphen | create `steps/<name with underscores>/` with a `Dockerfile` and `app/entry.py` |
| `Step 'x' has no kind=, which every step declares: one of ingest, transform, train, evaluate, publish, control.` | a step has no `kind=` | add the kind that says what the step does. "This app was made before the current pipelines" follows only when no step has a kind |
| `kind is 'x', which is not a kind. A step is one of ingest, transform, train, evaluate, publish, control.` | a kind that does not exist | choose one of the six |
| `'clean' is both an input (inputs=) and one of its own outputs (produces=)` | a step reads and writes one name | rename the setting, for example `previous-clean`, or the produced name |
| `... has the input 'x' and needs a step that produces 'x'`; `needs 'a' and 'b', which both produce 'x'` | a name would mean two things | rename one |
| `the dataset name 'x' is too short. A dataset name has 3 to 40 characters` | `dataset("x")` | give it a longer name |
| `the dataset 'x' is already produced by step 'y'. A dataset has one writer.` | two steps make the same dataset | keep one writer |
| `dataset('x') in app 'y' is the repository 'dataset-y-x', and the lake allows 3 to 48 characters after 'dataset-' ...` | the app's name and the dataset's name together are too long | shorten one (`kaosctl lint` does not check this: it does not know the app's name) |
| `needs 'x', which is defined after it` | a step is defined below the step that needs it | move the line of `x` above |
| `reads the config section 'x', which does not exist in config/` | `reads=` names a section that is not there | fix the name, or add the section to `config/` |
| `Step 'z' needs 11 steps; a step can need at most 10.` | more than ten steps in `needs=` | put a step in between that gathers some of their results |
| `can read 17 datasets by name ...` | more than 16 datasets in one step | split the step, or join datasets |
| `dataset(..., of=...) is reserved for a later release` | `of=` is not available yet | remove it |

### When a step does not keep to its kind

A step that breaks the contract of its kind is refused with one sentence. The platform says it with a small `s`
(`step 'x': ...`) and `kaosctl lint` with a capital (`Step 'x': ...`, rule `L-E07`). Each type's page shows its own.

| you see | do this |
|---|---|
| `an ingest step brings data in, so it produces a dataset. Add produces=[dataset("name")].` | add the dataset, or choose the kind of the work the step does |
| `a transform step turns data into something. Add produces=[...] with a dataset, a model or an artifact.` | add what it makes |
| `a train step produces a model. Add produces=[model("name")], or give the step the kind of the work it does (ingest, transform, evaluate, publish, control).` | add the model, or change the kind |
| `an evaluate step writes reports only, so it may not produce a dataset or a model. Use kind="transform" for a step that makes a dataset, kind="train" for one that makes a model.` | change the kind, or write an artifact |
| `a publish step delivers a result and produces nothing here. Remove produces=, or give the step the kind of the work it does.` | remove `produces=` |
| `a control step steers the run and handles no data, so it takes no inputs= and no produces=.` | remove them, or give the step the kind of the work it does |

### When a run starts

| you see | it means | do this |
|---|---|---|
| `x-walltime is '1d'. Write minutes or hours, for example 90, 90m or 12h: at least one minute, at most 30 days, no other unit.` | the time limit of step `x` is not minutes or hours | write `90`, `90m` or `12h` in the field |
| `x-walltime is 15 minutes, which is not longer than the 20 minutes before its limit that the step is told to save (resumable= in pipeline.py). Give the step more time.` | the limit is shorter than the time the step needs to save | raise the field, or lower the lead in `resumable=` |
| `x-checkpoint-every is 'often'. Write minutes or hours, ...` | the checkpoint interval is not minutes or hours | write `10m` or `1h` |
| `promote-clean is 'maybe'. Choose true or false.` | the choice of a dataset to promote is not `true` or `false` | choose one of the two |
| `'plan.promote' is no longer read. Tick the field promote-<dataset> of the run form, one for each dataset a step produces.` | the extra settings of the run still hold `plan:` | remove it and set the field `promote-<name>` to `true` |
| `step 'x' cannot run on class 'gpu-t4': it is a GPU machine and the step does not declare gpu=True. Add gpu=True to the step in pipeline.py to run it on a GPU machine.` | the run asked for a class the step is not offered | pick a class the form offers, or add `gpu=True` |
| `step 'x' cannot run on class '...': an ingest step never runs on HPC (Slurm). Choose one of: ...` (also `publish` and `control`; for a step that produces a dataset: `a step that produces a dataset runs on the cluster for now`) | an HPC (Slurm) class for a step that never runs there | choose a class from the list |

What you see while a step runs is in [When something goes wrong](when-something-goes-wrong.md).

## What is guaranteed

- **The same code runs everywhere.** On the platform's own machines and on HPC (Slurm) a step is `python -m app.entry`, with
  one context and one result.
- **Versions are exact.** Every dataset a run reads is one exact version, fixed before the first step, and recorded in
  the result of every step. A version never changes after it is made.
- **`latest` moves only at the end of a fully successful run, and only for the datasets whose `promote-<name>` is `true`.** It moves for all of
  them or for none. A run that fails, or that you did not ask, leaves `latest` where it was.
- **Nothing is saved before every output has passed its checks.**
- **Only the app that declares a dataset writes it.**
- **A platform update changes nothing of yours.** Your code, your settings and your images change only when you merge a
  change.

## What is not promised today

Each row is a limit of today. A row is not a promise that it will go away.

| not available | what happens | what to do |
|---|---|---|
| more than one pipeline in an app | the app has one pipeline: the file `pipeline.py` | make a second app that reads what the first makes ([Several pipelines](several-pipelines.md)) |
| starting a run from a step in the middle | every run starts at the first step | make the long step resumable, and write a dataset before the step you may want to skip ([Re-running](rerun.md)) |
| reusing the result of an earlier run | a step is never skipped because its inputs did not change | pin the versions you read ([Re-running](rerun.md)) |
| a step that produces a dataset on HPC (Slurm) | it runs on the platform's own machines, and the run form offers it no HPC class | make the heavy work an artifact in one step and the dataset in a cheap second step ([Produce a dataset](produce-a-dataset.md#where-it-runs)) |
| `ingest`, `publish` and `control` steps on HPC (Slurm) | they run on the platform's own machines | none needed |
| a dataset that is a variant of another (`dataset("x", of=...)`) | refused | write a dataset of its own |
| a schedule | a pipeline cannot declare one | start the run yourself |
| a promise for how long finished runs and their step logs are kept | not part of the contract today | copy what you need into an artifact or a dataset |
| a `when=` with `<`, `>` or parentheses | refused | compute the value in an earlier step and compare it with `==` |
| two runs moving the same `latest` at once | the second one moves nothing and fails, naming the dataset | start it again ([when two runs write at once](data-writes.md#when-two-runs-write-at-once)) |
| composing your settings on your laptop without a file | `kaosctl step run` needs `--params-file` | [Try it locally](try-it-locally.md#run-steps-the-way-the-platform-does) |

What a run keeps and removes, and when, is in [What is kept, and for how long](data-retention.md).

## What you can add

| what | how | page |
|---|---|---|
| Read a dataset at the version chosen on the form | `inputs=["dataset"]`, `step.input("dataset")` | [Read data](read-data.md) |
| Read several datasets in one step | several names in `inputs=` | [A step with two inputs](flow-datasets.md#a-step-with-two-inputs) |
| Read a dataset that another pipeline of the project makes | a setting that holds `dataset-<app>-<name>@latest` | [A second pipeline reads it](flow-datasets.md#a-second-pipeline-reads-the-dataset) |
| Read a dataset that another project shares with yours | `<owner>/dataset-<name>@<version>` in the same setting | [Share a dataset](share-a-dataset.md) |
| Hand small values to the next step | `step.result(**values)`, `step.upstream("x").values` | [Values and files](flow-between-steps.md) |
| Hand files to the next step | `artifact("name")` in `produces=` | [Values and files](flow-between-steps.md#files-to-the-next-step) |
| Make a dataset, a model or an artifact | `dataset("n")`, `model("n")`, `artifact("n")` in `produces=` | [Pass things on](pass-things-on.md) |
| Skip a step by a choice on the form, or by a value an earlier step handed on | `when=` | [Conditions and skipping](conditions-and-skipping.md) |
| End a step as skipped while it runs | `step.skip("reason")` | [Conditions and skipping](conditions-and-skipping.md) |
| Cope with a skipped step | `step.upstream("x", optional=True)`, `step.input("x", optional=True)` | [A step that may be skipped](flow-between-steps.md#a-step-that-may-be-skipped) |
| Need several steps at once | `needs=[a, b]` | [Fan-in](flow-between-steps.md#one-step-needs-several-steps) |
| Check an output before it is saved | `step.check("name", min_files=10)`, or `layout=` | [Produce a dataset](produce-a-dataset.md) |
| Edit files of an input | `step.input("x", writable=True)` | [Reference](reference.md#step-api-kaos_libstep) |
| Use a scratch folder that is never saved | `step.workdir()` | [Cheat sheet](cheat-sheet.md) |
| Ask for a GPU | `gpu=True` | [Bigger machines](bigger-machines.md) |
| Set the longest a step may run, anywhere | `walltime="12h"`, the default of the field `<step>-walltime` | [Long jobs](long-jobs.md#the-time-limit) |
| Continue after an interruption | `checkpoint.load/save`, `resumable=`, `checkpoint_every=` | [Long jobs](long-jobs.md) |
| End a GPU step that sits idle sooner or later | `idle_timeout=` | [Reference](reference.md#pipelinepy) |
| Run a step many times, once for each combination of values | see [Sweeps](sweeps.md) | [Sweeps](sweeps.md) |
| Move `latest` of a dataset you make | the field `promote-<name>` of the run form | [Move `latest`](flow-datasets.md#move-latest) |
| Bring data in from outside | a step of kind `ingest` | [Bring data in](bring-data-in.md) |
| Add Python packages to a step | `RUN pip install` in the step's `Dockerfile` | [Add packages](add-packages.md) |
| Test a step on your laptop | `kaos_lib.testing.running`, `kaosctl step run` | [Test your steps](test-your-steps.md) |

## The limits

Every number of the guide is in this table.

| what | limit |
|---|---|
| a step, input or output name | 40 characters of `a-z`, `0-9`, `-`; no `kaos-` at the start |
| step names that are kept | `main` and `hpc-follower`; a name that ends in `-hpc`; the refusal lists the others |
| the name of a dataset a step makes | 3 to 40 characters |
| the app name and the dataset name together | the dataset is `dataset-<app>-<name>`, and `<app>-<name>` has at most 48 characters, so a long app name leaves a short dataset name |
| an app name | 55 characters |
| steps in `needs=` | 10 |
| datasets one step reads | 16 (its inputs and what its needed steps produce) |
| the result of a step | 8 KiB |
| the reason of `step.skip()` | 300 characters |
| what a step receives (settings and results of needed steps) | 96 KiB |
| the extra settings of a run | 16 KiB |
| the definition of one step in `pipeline.py` | 24 KiB |
| a dataset version in a reference | 255 characters |
| the time limit of a step that sets no `walltime=` | 4 hours, on the platform's own machines and on HPC (Slurm). `walltime=` sets the default, and the field `<step>-walltime` of the run form sets the limit of a run. Waiting for a machine does not count |
| the longest time limit | 30 days |
| the longest run on HPC (Slurm) | set by the site; `kaosctl lint` assumes 2 days when it has no project facts |
| continuations of a resumable step, on the platform's own machines and on HPC (Slurm) | 5; the time limit applies to each run of the step |
| a step without a checkpoint whose machine was lost | runs again from the start at most twice |
| a GPU step with no GPU use and no new log line | ends as idle after 20 minutes (`idle_timeout=` changes it, `0` turns it off) |
