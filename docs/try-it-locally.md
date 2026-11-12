# 10. Try it locally

You have the app from the earlier pages. On your laptop, with no cluster and no upload, you run a step, test it, and
check the pipeline before you push. Install `kaosctl` as on [page 1](run-it.md#install-kaosctl).

## Test a step

`kaos_lib.testing.running` gives a step what the platform gives it: the settings, the folders of its inputs and the
results of the steps before it. You call the step's `main()` and read what it handed on.

```python title="step_tests/test_prepare.py"
--8<-- "examples/first-pipeline/try-locally/step_tests/test_prepare.py"
```

```bash
python -m pytest step_tests
```

```text
..                                                                       [100%]
2 passed in 0.10s
```

(`test_train.py` from [page 8](long-jobs.md) is the second test.) `running` takes `params`, `inputs` (a name and a
folder), `upstream` (what a step handed on), `upstream_writes` (what it wrote) and `produces`. Nothing is
uploaded. The outputs stay in the folder you give: `run.output("clean")`.

## Run steps the way the platform does

`kaosctl step run <step>` starts the step with `python -m app.entry`, in the step's own Python environment. It makes the
environment when there is none; `kaosctl dev` makes one for every step. The settings come from a file:

```yaml title="params.yaml"
--8<-- "examples/first-pipeline/try-locally/params.yaml"
```

```bash
kaosctl step run prepare --params-file params.yaml --input dataset=./toy
kaosctl step run hello-world --params-file params.yaml --input reference=./reference
```

```text
  input dataset: the folder ./toy
Running prepare: python -m app.entry (run local-20261112t034217z; the step context holds 27 characters of composed params: prepare)
[prepare] kept 2 of 3 files
Result of prepare (kept in .kaos/local/results/prepare.json):
  values: {"files": 2, "dropped": 1}
  read    dataset: dataset-dataset at 0fbede0b4d6d
  wrote   clean (dataset): .kaos/local/staged/clean
  wrote   dropped-files (artifact): .kaos/local/staged/dropped-files
Done: prepare exited 0. Next: kaosctl step run <the step that needs prepare>, or kaosctl build prepare
  input reference: the folder ./reference
  upstream prepare: from its last local run (prepare.json)
Running hello-world: python -m app.entry (run local-20261112t034217z; the step context holds 27 characters of composed params: hello)
[hello-world] hello (my-experiment-v1): 2 files (12 bytes) in clean, 3 in the reference, 1 dropped by prepare: empty.txt
Result of hello-world (kept in .kaos/local/results/hello-world.json):
  values: {"files": 2, "size": 12, "reference": 3}
  read    reference: dataset-reference at 8306d71f5aba
  read    clean: dataset-myapp-clean at b2e7b6573672
  wrote   report (artifact): .kaos/local/staged/report
Done: hello-world exited 0. Next: kaosctl step run <the step that needs hello-world>, or kaosctl build hello-world
```

- `--input NAME=FOLDER` gives an input a folder as it is. `--input NAME=dataset-x@v1` downloads a small sample of that
  version with your own sign-in (`--sample-mb` sets the most). Folders alone work offline.
- A step that needs an earlier step finds that step's last local result: run them in order.
- Nothing is uploaded. Outputs stay in `.kaos/local/staged/<name>/`, results in `.kaos/local/results/`. The commit
  you see is a fingerprint of the content: the same files give the same commit.
- The step runs with a short list of your environment variables. The addresses and tokens the platform gives a running
  step are not passed, even if your shell has them.
- Without `--params-file` the settings are composed from `config/` by the platform's own composer. For that, pass the
  context file of your app with `--context`.
- `--python <interpreter>` runs the step with a Python you already have, for a step with heavy dependencies.

## Check the pipeline

```bash
kaosctl lint
```

```text
steps/hello_world/Dockerfile:3:1: info L-D07 RootUser: The image of step 'hello-world' runs as root (no USER). ...
steps/prepare/Dockerfile:3:1: info L-D07 RootUser: The image of step 'prepare' runs as root (no USER). ...
skipped L-E03 UnknownClass: the catalogue has no list of compute classes (give --context, the project's platform context)
skipped L-I03 Schedules: pipelines cannot declare a schedule yet, so there is nothing to check
0 errors, 0 warnings, 2 infos; 2 rules skipped. Rule set 2.0.0; facts from: built-in default.
```

`kaosctl lint` reads `pipeline.py`, `config/` and the Dockerfiles as text and runs nothing. With a step's `kind=` taken
off:

```text
pipeline.py:19:15: error L-E07 StepDeclaration: Step 'prepare' has no kind=, which every step declares: one of ingest, transform, train, evaluate, publish, control.
```

The exit code is 0 without errors and 2 with one. The platform runs the same check on every pull request. A check that
needs facts about your project, such as the list of classes, is skipped, never passed, until you give `--context`.
[Reference](lint.md) lists every rule.

Next: [A real pipeline](a-real-pipeline.md).
