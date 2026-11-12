# When something goes wrong

Find the message you see, read what it means, do what it says. The messages are written as the library and the platform
print them; `...` stands for a name or a number that is yours. Every message that starts with `ERROR:` ends the step or
the command.

## A run fails

| you see | it means | do this |
|---|---|---|
| `input 'dataset': dataset-default holds no files at the version this run read (latest). Push data to it with kaosctl dataset push <folder> dataset-default, or choose another dataset for 'dataset' on the run form.` | the dataset the step reads is empty at that version. A new app's first run reads the empty default dataset | push files and merge the pull request, as on [page 1](run-it.md#put-a-few-files-in-a-dataset), or pick another dataset on the run form |
| `ERROR: step '...' ended without step.result(): the next step would get nothing. Call step.result() as the last line.` | the step finished, or exited with 0, without handing a result | end the step with `step.result()`, with no values if there are none |
| `'x' is not an input of step 'y'. Its inputs are: ... Add it to inputs=[...] in pipeline.py.` | the step asked for a name it did not declare | declare it in `inputs=`, or name the step that makes it in `needs=` |
| `'x' is not produced by step 'y'. It produces: ... Add it to produces=[...] in pipeline.py.` | `step.output("x")` for an output the step did not declare | add `dataset("x")`, `model("x")` or `artifact("x")` to `produces=` |
| `step 'x' is not upstream of 'y'. Add needs=['x'] in pipeline.py.` | `step.upstream("x")` without `needs=` | add the step to `needs=` |
| `step 'x' did not run, so it left no result, and 'y' needs it.` and `input 'x' of step 'y' is not there, and ... did not run` | `x` was skipped by its `when=` | read it with `optional=True`: [A step that may be skipped](flow-between-steps.md#a-step-that-may-be-skipped) |
| `output 'x' was not written: step 'y' declares it in produces= and never called step.output('x').` | a declared output was never asked for | write into `step.output("x")`, or take it out of `produces=` |
| `output 'x' is empty: the step wrote no files into ...` | the folder holds no files | write a file into it. Nothing was saved |
| `output 'x' failed its check: it holds N files; at least M are needed` | a `step.check("x", min_files=M)` was not met | fix what the step writes. Nothing was saved |
| `output 'x' holds a file in .kaos/` | a dataset output has a file under `.kaos/` | write it elsewhere: the platform keeps that folder |
| `the result costs N; the limit is 8192.` | the values passed to `step.result()` are too big | send metrics to MLflow, and files in an output: [Pass things on](pass-things-on.md) |
| `result value 'x' is a ...; values are text, numbers, booleans, lists and objects.` | a value that is not plain data, for example a numpy array | convert it: `int(x)`, `x.tolist()` |
| `this app may not write dataset-...: only what the step declares in produces=[...] in pipeline.py can be written.` | the step wrote a dataset another app declares, or one it did not declare | declare it in `produces=`, or write a dataset of your own |
| `dataset-... does not exist. The platform creates the dataset or the outputs of an app when its pipeline declares them in produces=[...]; it is there shortly after that change is merged.` | the first run started before the platform made the dataset | run again shortly: it is made soon after the change that declares it is merged |
| `output 'x': dataset-... changed 3 times while this step was promoting it. Another run is writing the same dataset.` | two runs of this pipeline asked to move `latest` together | run again: [When two runs write at once](datasets-versions-hashes.md#when-two-runs-write-at-once) |
| `lakeFS rejected the credential this step was given, or it has expired. The app cannot fix this: report it to the platform team with the run's name` | the step's sign-in was refused | report it with the run's name; your code cannot fix it |
| `ERROR: this is not a pipeline step: KAOS_STEP_CONTEXT is not set. Run the step with: kaosctl step run <step>` | you started `entry.py` by hand | use `kaosctl step run`, or [a test](test-your-steps.md) |

## Messages that need no action

| you see | it means |
|---|---|
| `kaos-lib: Zitadel could not be reached (...); the sign-in is tried again in N seconds.` | the sign-in service did not answer. A short outage is normal: the step tries again for about two and a half minutes and goes on when it answers. Do nothing. If the tries run out the step fails with `cannot reach Zitadel` |
| `output 'x': the same content as the last version of dataset-... (...); no new version.` | the step wrote the files the last version already holds |
| `output 'x': sealed dataset-... at ... (kept as ...); latest was not moved.` | the run made a version and did not ask to move `latest` |

## The pipeline is refused

`kaosctl lint` reports these before you push; the platform reports them when it builds the pipeline. Each lint rule has
a page: [Lint checks](lint.md).

| you see | it means | do this |
|---|---|---|
| `L-E06 ... step() no longer takes 'outputs'. This app was made before the current pipelines. Create it again from the template.` | `outputs=` is gone | declare the things a step makes in `produces=`, and hand values on with `step.result(...)` |
| `step() no longer takes 'hpc_time_limit'` | `hpc_time_limit=` is gone | write `walltime="12h"` |
| `step() no longer takes 'disk'` | a step is not told its disk | pick a bigger class on the run form |
| `L-E07 ... Step 'x' has no kind=, which every step declares: one of ingest, transform, train, evaluate, publish, control.` | a step has no `kind=` | add the kind that says what the step does. The sentence "This app was made before the current pipelines" follows only when no step has a kind |
| `L-E05 ... needs 'x', which is defined after it` | a step is defined below the step that needs it | move the line of `x` above |
| `L-E05 ... reads the config section 'x', which does not exist in config/` | `reads=` names a section that is not there | fix the name, or add the section to `config/` |
| `L-E07 ... the dataset 'x' is already produced by step 'y'. A dataset has one writer.` | two steps make the same dataset | keep one writer |

## On the run form

| you see | it means |
|---|---|
| a step offers only machines of your project and no HPC (Slurm) class | a step that makes a dataset is not offered HPC (Slurm) classes for now. Its neighbours are |
| a step offers no GPU class | a step is offered GPU classes when it declares `gpu=True` |
| no HPC (Slurm) class at all | your project is not connected to a site, or the allocation of that class is used up: ask your platform contact |
| `WaitingForBudget`, `ConcurrencyLimit`, `BudgetBlocked`, `SiteLimit`, `SubmitLimit` and others | the reasons an HPC (Slurm) step waits or is refused: [HPC (Slurm)](hpc.md#why-a-step-waits-or-is-refused) |

## On your laptop

| you see | it means | do this |
|---|---|---|
| `To run with the settings you have, write a params.yaml (a section per config file the step reads ...) and pass --params-file params.yaml. ... no pipeline engine was given.` | `kaosctl step run` cannot compose `config/` without the platform's context file for your app, which you do not make yourself | write a `params.yaml` and pass `--params-file params.yaml`: [Try it locally](try-it-locally.md#run-steps-the-way-the-platform-does) |
| `--python x: no such interpreter (/path/x).` | the Python you named is not at that path. A relative path is read from the folder you run the command in | give a path that exists from there, or an absolute one |
| `--python x cannot import kaos_lib: install kaos-lib into that ...` | that Python has no kaos-lib | install kaos-lib into it |
| `not signed in. Run kaosctl login, or set LAKEFS_ACCESS_KEY/LAKEFS_SECRET_KEY ...` | no sign-in on this machine | run `kaosctl login` inside your app folder |
| `your kaosctl login session has expired: run kaosctl login again.` | the session ended | `kaosctl login` again |
| `no step named 'x' in ... Steps: ...` | a typo in the step name | use one of the names listed |

## Datasets and commands

| you see | it means | do this |
|---|---|---|
| `cannot determine the lakeFS URL ...` | `kaosctl` does not know your project | run it inside your app folder, or pass `--url` |
| `... has no version v3. Available: v1, v2.` | the version does not exist | `kaosctl dataset versions <repo>`; release a version after the pull request is merged |
| `nothing new to release: the head of ... main is already v2.` | nothing changed since `v2` | merge a pull request first |
| `'x' is not a dataset reference: write <repository>@<ref>` | a reference without its version | write `dataset-name@v1` |
| `dataset failed validation (N problem(s))` (exit code 2) | the files do not fit the layout | fix the files the lines above name, and run `kaosctl dataset validate <dir>` |
| `unknown layout 'x'. Known: raw, yolo.` | a layout name that does not exist | `kaosctl layout list` |
| `kaos_lib.mlflow needs the mlflow extra` | the step's image has no MLflow client | install `kaos-lib[mlflow]` in the image |

Exit codes of `kaosctl`: `0` ok, `1` a mistake of yours (one `ERROR:` line), `2` an invalid dataset or a lint error.
