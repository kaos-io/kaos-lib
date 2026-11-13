# Re-running

## Start a run from a step

If step 5 of 7 fails after 20 hours, you do not have to run steps 1 to 4 again. Start a new run from step 5 and take the
results of the earlier run for the steps before it.

The run form has two fields, both empty by default, which means a normal run:

| field | what you write |
|---|---|
| `reuse-from-run` | the name of an earlier run of this app. Steps before the step below are not run again: their results and outputs are taken from that run |
| `start-from-step` | the step to run first. It and every step after it run again |

Both go together: one without the other is refused. Everything else on the form works as always.

Take a pipeline `prepare -> train -> evaluate -> publish`, where `evaluate` failed in the run `myapp-x7k2p`. You fix the
code of `evaluate`, push, and start a run with `reuse-from-run` set to `myapp-x7k2p` and `start-from-step` set to
`evaluate`. `prepare` and `train` do not start: they are shown as skipped. `evaluate` starts at once and gets what `train`
handed on, as it did in the earlier run, and `publish` runs after it.

## What is reused

For every step that is not run again, the new run takes from the earlier run:

- **what the step handed on**: its values, what it read and what it wrote. A step after it that asks for them with
  `step.upstream("train")` gets them as in the earlier run, and a `when=` on one of those values is decided by them;
- **the models and artifacts it wrote**: `step.input("model")` reads them from the folder of the earlier run. Nothing is
  copied;
- **the datasets it made**: they are read by version, as always;
- **the versions it read**: the dataset versions the earlier run read are the ones the new run reads for those steps.
  `latest` is not looked up again: it stays what it was in the earlier run.

A step is not run again when it comes before the step you start from, and also when it is on a branch of the pipeline that
does not lead to that step. Only the step you name and the steps after it run again.

**The code of a step that is not run again is the code of the earlier run, and the platform checks it.** The image of
each step that is not run again must be the very build it was in the earlier run (the platform compares the image's
digest). If you pushed a change that rebuilt a step before the start, the run is refused: start from that step to run it
again with the new code.

## What must not change

A step that is not run again cannot read different settings. Before any step starts, the platform compares them with the
earlier run and refuses the run when something differs:

- the settings the step reads (the sections of `config/` in its `reads=`), and the values of the run form fields its
  `when=` names;
- the build of the step: its image must be the one it had in the earlier run;
- what the step is: its kind, its `needs=`, its `inputs=` and its `produces=`. A step the earlier run did not have (the
  pipeline changed since) cannot be left out of the new run;
- the dataset an input names. The form may leave the version out, or write the one the earlier run read; another dataset,
  or a version that is another commit, is refused.

A value is compared with its type: `1`, `true` and `"1"` are three different settings, and the refusal shows the types when
only the type differs (`1 (number) -> "1" (text)`). The refusal names what changed, for example:

```text
step 'train' reads different settings than in run 'myapp-x7k2p': train.lr: 0.1 -> 0.01. A step before 'evaluate' is not
run again, so its settings cannot change. Set them back, or start from step 'train'.
```

Settings of the step you start from, and of the steps after it, may change: they run again.

## What the platform checks before it starts

Each refusal is one sentence, and the run does not start.

| the sentence says | what to do |
|---|---|
| `reuse-from-run and start-from-step go together: <field> is empty.` | fill both fields, or empty both |
| `start-from-step: this pipeline has no step 'x'. Its steps are: ...` | write one of the steps listed |
| `reuse-from-run: run 'r' saved no record for this app (its step images may be older than this feature, or saving failed: see that run's log).` | write the name of a run of this app, as the run page shows it. A run whose steps were built with an older library saved none |
| `the records of run 'r' do not all belong to one run: ...` | a run with that name existed before: choose another run |
| `a run named 'r' already saved its records for this app. Start the run again under a name no earlier run had.` | give the new run a name no earlier run of this app had |
| `step 's' was built from a different image in run 'r' than it has now, so its code changed.` | start from step `s` |
| `step 's' has no image with a digest in run 'r' or now, so its code cannot be compared.` | start from step `s` |
| `run 'r' has no result for step 's' (it failed or did not finish)...` | the earlier run did not finish that step: start from it, or choose a run that finished it |
| `step 's' reads different settings than in run 'r': ...` | set them back, or start from step `s` |
| `step 's' is not the step run 'r' ran: ...` or `step 's' is not in run 'r'...` | the pipeline changed after that run: start from step `s` |
| `input 'x': step s is not run again and read ... in run 'r', but the form now names ...` | set the input back, or leave its version out, or start from step `s` |
| `output 'x' of step 's' (run 'r') is no longer there: ...` | start from step `s`, which makes it again |
| `promote-x is true, but the dataset x was made by step s of run r, which this run does not run again...` | a run moves `latest` only for what it made: promote it from run `r`, or start from step `s` |

## Which run to name

Name a run that ran the steps itself. A run that took results from another run keeps no record of them, so it cannot be
named: name the run it took them from. Each step that ends well keeps what it handed on in the app's outputs repository,
in the folder `kaos-runs/<run>/`, with the run's plan beside it. Leave that folder as it is. A step that cannot save its
record warns in its log ("This run cannot be reused from a later step") and still succeeds. Call `step.result()` last in a
step: what the step does after it is not in the record. The records are small (a result is at most 8 KiB) and are kept:
the platform does not remove them.

## Which library version

Every step image needs a **kaos-lib from 2026-11-13 or later** (the 0.5.0 builds that save records), in the earlier run and
in the new one. An earlier run made with an older library left no records, and the new run is refused ("saved no record" or
"has no result for step"). A step image with an older library fails loudly in the new run when it reads a model of an
earlier run: it looks in the folder of the new run and stops with
`input 'model': ... holds no files under model/<experiment>/<new run>/`. Build the step image again with the newer library.

## What is not available yet

- A step with `matrix=` cannot be left out of the new run. Start from it, or from a step before it.
- A step that ran on an HPC (Slurm) class in the earlier run cannot be left out of the new run.
- A step that runs on an HPC (Slurm) class cannot read a model or an artifact taken from an earlier run. Choose a machine
  class of the platform for it.
- A step that the earlier run skipped by its own `when=` has no result. It can be left out of the new run when its `when=`
  is on run form fields only and was false with the values the earlier run had: it counts as skipped, as the earlier run saw
  it. A `when=` on a value of another step cannot be told: start from that step.
- Reusing a result because nothing changed (a cache that skips a step by itself) is not available. You choose the step.

## What a re-run does without these fields

Run the pipeline again and you start a new run. **Every step runs again, from the first.**

What stays the same and what changes:

| | in the new run |
|---|---|
| the settings | the run form's values at that time. Change them, or keep them |
| a dataset you read | the version named in the settings. `latest` is the version it points to when the run starts. A named version (`@v3`) is the same data every time |
| a dataset the pipeline makes | a new version for the files that changed. A step that writes the same files as before makes no new version, and uploads only the files that differ |
| a model or an artifact | a new folder for the new run, `<name>/<experiment>/<run>/`. Earlier runs keep theirs |
| `latest` of a dataset the pipeline makes | moves only if the run asks, and only if every step went well ([Move `latest`](flow-datasets.md#move-latest)) |

So a failed run costs you its time, and nothing else. It changes no `latest` and it overwrites no earlier result.

## A step that was cut short is not a re-run

A step that loses its machine or reaches its time limit is run again by the platform, inside the same run. A step that
saves checkpoints continues from the last one ([Long jobs](long-jobs.md)). You do nothing.

## Read the same data again

To make two runs comparable, pin the version of every dataset they read:

```yaml title="config/dataset.yaml"
--8<-- "examples/flows/rerun/config/dataset.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/rerun/config/config.yaml"
```

The run records the exact version each step read ([What a run reads](data-reads.md#what-a-run-records)).

Next: [When something goes wrong](when-something-goes-wrong.md).
