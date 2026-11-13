# Sweeps

**You want** to try one step with several settings, for example three learning rates and two batch sizes, and keep
the best. You write the values once, in `matrix=`. The run starts the step once for each combination, and the step
after it gets the results of all of them.

## One example, from end to end

`train` has `matrix=`. It runs six times, once for each of the six combinations of the values. Each run reads its own
values like any other setting: `ctx.params["lr"]` and `ctx.params["batch"]`.

```python title="pipeline.py"
--8<-- "examples/flows/sweep/pipeline.py"
```

```python title="steps/train/app/entry.py"
--8<-- "examples/flows/sweep/steps/train/app/entry.py"
```

```yaml title="config/train.yaml"
--8<-- "examples/flows/sweep/config/train.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/sweep/config/config.yaml"
```

`pick-best` needs `train`. `step.upstream("train")` is a list with one entry for each run, in the order of the
combinations. It keeps the model of the best one:

```python title="steps/pick_best/app/entry.py"
--8<-- "examples/flows/sweep/steps/pick_best/app/entry.py"
```

The guide runs this app on every change: all six runs, and `pick-best` twice, once with every run finished and once with
one run failed.

Each run saves its own model. The model `model` has one version for each run, and each version carries the run's values
(`lr`, `batch`) and its number. The runs are numbered from 0, in the order of the combinations: the first name changes
slowest (`lr` 0.1 with `batch` 16, then 0.1 with 32, then 0.01 with 16, and so on). One run of the step is called an
*item*, and its number is its `index`.

## Choose values on the run form

The run form has two fields for a step with `matrix=`. The values in `pipeline.py` are only the default.

| field | holds | default |
|---|---|---|
| `<step>-matrix` | the combinations to run, as a list of objects: `[{"lr": 0.01, "batch": 16}, {"lr": 0.001, "batch": 32}]` | every combination of the values in `matrix=` |

To run two combinations instead of six, write only those two. Each object gives a value for every name, and only the
names `matrix=` has. The form refuses what it cannot read before any step starts and names the field. The rules for the
field are in the [run form table](contract.md#the-run-form).

## Run fewer at once

| field | holds | default |
|---|---|---|
| `<step>-parallel` | `all`, or a whole number from 1 to 32: how many runs go at the same time | `4` |

With `2` the six runs go two at a time. The class of machine (`<step>-class`) and the time limit (`<step>-walltime`) are
the step's, and every run gets them: the limit is for one run, not for all.

## On HPC (Slurm) the items share a node

Pick an HPC (Slurm) class for the step as for any step ([HPC (Slurm)](hpc.md)). On an HPC (Slurm) class the runs of one
run share a machine when it has room, so a small sweep costs one machine, not six. With the default of 4 up to four runs
share one machine. Ask for more with `<step>-parallel` and the sweep runs on more machines, and uses more of your
allocation.

## Pick the best

`step.upstream("train")` returns a plain list. Each entry has:

| attribute | holds |
|---|---|
| `index` | the number of the run, from 0 |
| `matrix` | the run's values: `{"lr": 0.01, "batch": 16}` |
| `status` | `"ok"`, `"failed"` (the run ended without a result) or `"skipped"` (it called `step.skip(reason)`) |
| `values` | what the run gave to `step.result(...)`; `{}` unless `status` is `"ok"` |
| `reads`, `writes` | what the run read and saved, as for any needed step ([Values to the next step](flow-between-steps.md#values-to-the-next-step)) |
| `reason` | why a skipped run skipped; `""` otherwise |

**By default one failed run fails the whole step and the pipeline run.** The other runs go on to the end, then the step
ends as failed and names each failed run by its number and values. Nothing after it runs, and nothing is promoted.

To pick the best of the runs that did not fail, write `matrix_allow_failed=True` on the step with `matrix=`. The step after
it then runs when at least one run finished with `"ok"`, and it sees the failed runs in the list, with `status` `"failed"`
and no values. When none finished, the step still fails. You have said that failed runs are acceptable, so the pipeline run
can end as succeeded and promote what it made.

!!! warning "A dataset after `matrix_allow_failed=True`"
    A step that produces a dataset after such a step would be written even when a training failed, and, if it is
    promoted, it becomes the latest version. `kaosctl lint` warns about it ([L-W08](lint/L-W08.md)). Remove
    `matrix_allow_failed=True`, or let the step that writes the dataset check the `status` of every run in
    `step.upstream(...)` and call `step.skip(reason)` when too few are `"ok"`.

To read the model of one run, name it: `step.input("model", item=3)`. Without `item=` the call refuses, because there are
six models and it cannot know which you mean. `item=` works only for what a step with `matrix=` saved.

A step that needs `train` and is skipped as a whole (its `when=` was false) is handled as any skipped step:
`step.upstream("train", optional=True)` is `None` ([Conditions and skipping](conditions-and-skipping.md)).

## Try it on your machine

Run one combination: `kaosctl step run train --matrix-index 3` is the fourth combination of the values in
`pipeline.py`. Without `--matrix-index` the command refuses and says how many there are. Its model and result are kept
for that number, and `kaosctl step run pick-best` reads the ones you ran (the others count as failed). To test a step
in code, see [Test your steps](test-your-steps.md#a-step-with-matrix).

## Limits

- At most 32 combinations for one step.
- A name is lowercase letters, digits and `_`, starting with a letter (`lr`, `batch_size`). It may not be a section of
  `reads=` or a name of the step's settings: the step reads both the same way and could not tell them apart.
- A value is a number, `True` or `False`, or a text of 1 to 64 letters, digits, spaces and `. _ + / : = @ , ( ) [ ] # % ^ ~ * -`.
  Numbers keep the type and the text you wrote (`1.0` stays `1.0`): a whole number beyond 2^53 (9007199254740992) must be
  written as text.
- What a step hands back with `step.result(...)` reaches the step after it as numbers in the usual form: a whole
  number such as `1.0` arrives as `1`, and the names of an item's values arrive in alphabetical order. A whole number
  beyond 2^53 is refused when the item ends: hand it on as text.
- A step with `matrix=` may read and write at most 4 things in all: `inputs=` and `produces=` together.
- A step may need only one step with `matrix=`. When it does, it may need at most 4 steps in all.
- The step may not produce a dataset: a dataset has one writer and one version for each run. Produce a model or an
  artifact, and let the step after it write the dataset.
- A step of the kind `ingest`, `publish` or `control` runs once and cannot have `matrix=` ([Step kinds](step-kinds.md)).
- A step with `matrix=` cannot need another step with `matrix=`. Put a step between them that picks which results to use.
- A `when=` cannot read a value of a step with `matrix=` (it has one value for each run). A `when=` on the step itself is
  fine: every run is then skipped.
- The values of all runs share 16 KiB: the values a run gives to `step.result(...)` may cost at most 16 KiB divided by the
  number of runs, and never more than 8 KiB (32 runs: 512 bytes each, 4 runs: 4 KiB). What the run read and wrote does not
  count against this share, only against the 8 KiB of the whole result. A larger result is refused with the limit. Log
  curves to MLflow and keep large things in the model or an artifact ([See your results](see-your-results.md)).

`kaosctl lint` checks each of these as you write ([L-E06](lint/L-E06.md#matrix)).

Next: [Several pipelines](several-pipelines.md).
