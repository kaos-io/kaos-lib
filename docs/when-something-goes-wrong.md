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
| `step 'x' did not run, so it left no result, and 'y' needs it.`, `step 'x' was skipped (reason), so it left no result, and 'y' needs it.` and `input 'x' of step 'y' is not there, and ... did not run or was skipped` | `x` was skipped by its `when=` or ended itself with `step.skip()` | read it with `optional=True`: [Conditions and skipping](conditions-and-skipping.md#what-a-step-that-needs-a-skipped-step-sees) |
| `output 'x' was not written: step 'y' declares it in produces= and never called step.output('x').` | a declared output was never asked for | write into `step.output("x")`, or take it out of `produces=` |
| `output 'x' is empty: the step wrote no files into ...` | the folder holds no files | write a file into it. Nothing was saved |
| `output 'x' failed its check: it holds N files; at least M are needed` | a `step.check("x", min_files=M)` was not met | fix what the step writes. Nothing was saved |
| `output 'x' holds a file in .kaos/` | a dataset output has a file under `.kaos/` | write it elsewhere: the platform keeps that folder |
| `the result costs N; the limit is 8192.` | the values passed to `step.result()` are too big | send metrics to MLflow, and files in an output: [Pass things on](pass-things-on.md) |
| `result value 'x' is a ...; values are text, numbers, booleans, lists and objects.` | a value that is not plain data, for example a numpy array | convert it: `int(x)`, `x.tolist()` |
| `this app may not write dataset-...: only what the step declares in produces=[...] in pipeline.py can be written.` | the step wrote a dataset another app declares, or one it did not declare | declare it in `produces=`, or write a dataset of your own |
| `dataset-... does not exist. The platform creates the dataset or the outputs of an app when its pipeline declares them in produces=[...]; it is there shortly after that change is merged.` | the first run started before the platform made the dataset | run again shortly: it is made soon after the change that declares it is merged |
| `kaos-promote FAILED: Promoted by this run: ... Not promoted, because another run promoted the dataset first: dataset 'clean' (dataset-...) ... Another run moved a dataset, so trying this task again cannot finish it: start a new run to promote clean.` | another run moved `latest` of the dataset while this one was running | start a new run to promote the datasets the message names. Every version of this run is kept and can be read by its exact version |
| `kaos-promote FAILED: Promoted by this run: ... Dataset 'x' (...) could not be promoted: ... The data store did not answer as needed: try again.` | the data store failed between two moves of `latest` | the platform tries again by itself; a dataset this run moved is recognised. If it still fails, start a new run ([what is left](flow-datasets.md#if-the-end-of-the-run-is-cut-short)) |
| `lakeFS rejected the credential this step was given, or it has expired. The app cannot fix this: report it to the platform team with the run's name` | the step's sign-in was refused | report it with the run's name; your code cannot fix it |
| `KAOS: this GPU step cannot reach the NVIDIA driver (libcuda.so.1 not found: ...); the image or node is not set up for GPU` | the GPU machine the step got has no usable driver | pick a class that has a GPU; if it has one, tell your platform contact |
| `ERROR: this is not a pipeline step: KAOS_STEP_CONTEXT is not set. Run the step with: kaosctl step run <step>` | you started `entry.py` by hand | use `kaosctl step run`, or [a test](test-your-steps.md) |

## Messages that need no action

| you see | it means |
|---|---|
| `kaos-lib: Zitadel could not be reached (...); the sign-in is tried again in N seconds.` | the sign-in service did not answer. A short outage is normal: the step tries again for about two and a half minutes and goes on when it answers. Do nothing. If the tries run out the step fails with `cannot reach Zitadel` |
| `output 'x': the same content as the last version of dataset-... (...); no new version.` | the step wrote the files the last version already holds |
| `output 'x': sealed dataset-... at ... (kept as ...). It becomes the latest when the whole run has ended well, if the run form's promote-x is ticked.` | the step made its version; `latest` moves at the end of the run, if `promote-<name>` is `true` and every step went well |
| `output 'x': 0 file(s) to upload, 0 to delete, 0 unchanged since the last version of dataset-..., 201 reused from an earlier run (copied, not uploaded).` | the files are the ones an earlier run sealed and did not move `latest` to: they were copied, not uploaded again. The run still has its own version |
| `output 'x': 1 of the 201 file(s) could not be copied and were uploaded.` | a file of an earlier run could not be copied, so this step uploaded it. Nothing to do |

## The pipeline is refused

`kaosctl lint` reports these before you push; the platform reports them when it builds the pipeline. Each lint rule has
a page: [Lint checks](lint.md).

| you see | it means | do this |
|---|---|---|
| `step 'x': outputs= is gone. Declare what the step writes with produces=[...] and hand it on with step.result().` | `outputs=` is gone | declare what a step makes in `produces=`, and hand values on with `step.result(...)` |
| `step 'x': hpc_time_limit= is gone. Use walltime=, for example walltime="12h".` | `hpc_time_limit=` is gone | write `walltime="12h"` |
| `step 'x': disk= is gone. The step gets the disk of the machine class it runs on.` | a step is not told its disk | pick a bigger class on the run form |
| `L-E06 ... when='...' is not a condition the platform can read. A condition compares one name with a text, with == or != and nothing else`, or `... names 'x', which is not a field of the run form` | `when=` is not written as a name, `==` or `!=`, and a text, or the field is not on the run form | write `when="mode != off"` with the name of a setting as the run form shows it, or `when="evaluate.passed == true"` with a value of a step in `needs=`: [Conditions and skipping](conditions-and-skipping.md) |
| `L-E06 ... when= reads a value of step 'x', which this step does not need` | the step `x` is not in `needs=` | add it to `needs=` |
| `step 'x' gave no value 'v' (it was skipped, did not run, or never set it)` | a `when=` on `x.v` found no value | set the value in every case, or test a form field |
| `L-E06 ... when= is written with plain names, not with {{...}}` | `when=` still has the `{{workflow.parameters.<field>}}` form | write the field's name instead |
| `L-E07 ... Step 'x' has no folder steps/x_y/. The folder of a step is steps/ plus the step's name with every hyphen written as an underscore` (also the render, and `kaosctl step run`, which used to end with `exited with code 127`) | the step's folder is missing or written with a hyphen | create `steps/<name with underscores>/` with a `Dockerfile` and `app/entry.py`: [Your first step](first-step.md#the-name-of-a-step-and-its-folder) |
| `L-E07 ... 'clean' is both an input (inputs=) and one of its own outputs (produces=)` (also the render) | a step reads and writes one name | rename the config value, for example `previous-clean`, or the produced name |
| `L-E07 ... the dataset name 'x' is too short. A dataset name has 3 to 40 characters` | `dataset("x")` | give it a longer name |
| `L-E07 ... Step 'x' has no kind=, which every step declares: one of ingest, transform, train, evaluate, publish, control.` | a step has no `kind=` | add the kind that says what the step does. The sentence "This app was made before the current pipelines" follows only when no step has a kind |
| `L-E05 ... needs 'x', which is defined after it` | a step is defined below the step that needs it | move the line of `x` above |
| `L-E05 ... reads the config section 'x', which does not exist in config/` | `reads=` names a section that is not there | fix the name, or add the section to `config/` |
| `L-E07 ... the dataset 'x' is already produced by step 'y'. A dataset has one writer.` | two steps make the same dataset | keep one writer |

## Refused when the pipeline is built

A step that does not keep to the contract of its kind ([Step kinds](step-kinds.md)) is refused with one sentence:

| you see | do this |
|---|---|
| `step 'x': an ingest step brings data in, so it produces a dataset. Add produces=[dataset("name")].` | add the dataset, or choose the kind of the work the step does |
| `step 'x': a transform step turns data into something. Add produces=[...] with a dataset, a model or an artifact.` | add what it makes |
| `step 'x': a train step produces a model. Add produces=[model("name")], or give the step the kind of the work it does (ingest, transform, evaluate, publish, control).` | add the model, or change the kind |
| `step 'x': an evaluate step writes reports only, so it may not produce a dataset or a model. Use kind="transform" for a step that makes a dataset, kind="train" for one that makes a model.` | change the kind, or write an artifact |
| `step 'x': a publish step delivers a result and produces nothing here. Remove produces=, or give the step the kind of the work it does.` | remove `produces=` |
| `step 'x': a control step steers the run and handles no data, so it takes no inputs= and no produces=.` | remove them, or give the step the kind of the work it does |

## When a run is refused before it starts

| you see | it means | do this |
|---|---|---|
| `x-walltime is '1d'. Write minutes or hours, for example 90, 90m or 12h: at least one minute, no other unit.` | the time limit of step `x` on the run form is not minutes or hours | write `90`, `90m` or `12h` in the field |
| `x-walltime is 15 minutes, which is not longer than the 20 minutes before its limit that the step is told to save (resumable= in pipeline.py). Give the step more time.` | the limit is shorter than the time the step needs to save | raise the field, or lower the lead in `resumable=` |
| `x-checkpoint-every is 'often'. Write minutes or hours, ...` | the checkpoint interval is not minutes or hours | write `10m` or `1h` |
| `promote-clean is 'maybe'. Choose true or false.` | the choice of a dataset to promote is not `true` or `false` | choose one of the two |
| `'plan.promote' is no longer read. Tick the field promote-<dataset> of the run form, one for each dataset a step produces.` | the advanced config of the run still holds `plan:` | remove it and set the field `promote-<name>` to `true` |
| `step 'x' cannot run on class 'gpu-t4': it is a GPU machine and the step does not declare gpu=True. Add gpu=True to the step in pipeline.py to run it on a GPU machine.` | the run asked for a class the step is not offered | pick a class the form offers, or add `gpu=True` |

## On the run form

| you see | it means |
|---|---|
| a step offers only machines of your project and no HPC (Slurm) class | a step that makes a dataset is not offered HPC (Slurm) classes. Its neighbours are |
| a step offers no GPU class | a step is offered GPU classes when it declares `gpu=True` |
| no HPC (Slurm) class at all | your project is not connected to a site, or the allocation of that class is used up: ask your platform contact |

### Why an HPC (Slurm) step waits or is refused

The status of a step says why. These are the reasons you can meet:

| reason | meaning | what to do |
|---|---|---|
| `WaitingForBudget` | the project's allocation covers the step once running steps end | wait |
| `ConcurrencyLimit` | the project runs as many Slurm jobs as it may | wait |
| `BudgetBlocked` | the step needs more node-hours than the project's share has left this month | shorten it, or ask your platform contact |
| `SiteLimit` | the site's monthly limit for the account is used up | ask your platform contact |
| `SubmitLimit` | the site allows only so many queued and running jobs, and the project has that many. The step fails | run it again when jobs have ended |
| `TooLongNotResumable`, `TooLongBeyondContinuations` | the time limit is longer than the site allows | make it resumable, or shorten it |
| `GPUViolation` | the step used a GPU that was not its own, on a node several steps share | use only the GPU the step is given |

## On your laptop

| you see | it means | do this |
|---|---|---|
| `To run with the settings you have, write a params.yaml (a section per config file the step reads ...) and pass --params-file params.yaml. ... no pipeline engine was given.` | `kaosctl step run` needs the settings from a file you write | write a `params.yaml` and pass `--params-file params.yaml`: [Try it locally](try-it-locally.md#run-steps-the-way-the-platform-does) |
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
