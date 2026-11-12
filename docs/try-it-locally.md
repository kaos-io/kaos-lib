# 10. Try it locally

You have the app from the earlier pages. On your laptop, with no cluster and no upload, you run a step, test it, and
check the pipeline before you push. Install `kaosctl` as on [page 1](run-it.md#install-kaosctl). Run every command in
the folder of your app.

## Test a step

`kaos_lib.testing.running` gives a step what the platform gives it: the settings, the folders of its inputs and the
results of the steps before it. You call the step's `main()` and read what it handed on.

Save this as `step_tests/test_prepare.py` in your app. Install pytest once, in the Python environment where you
installed kaos-lib: `pip install pytest`.

```python title="step_tests/test_prepare.py"
--8<-- "examples/first-pipeline/try-locally/step_tests/test_prepare.py"
```

```bash
python -m pytest step_tests
```

pytest lists a dot for each test that passes, and one test of `step_tests` is `test_train.py` from
[page 8](long-jobs.md), if you saved it. Nothing is uploaded. The arguments of `running` are in the
[Reference](reference.md#test-a-step-kaos_libtestingrunningtmp_path-kwargs).

## Run steps the way the platform does

`kaosctl step run <step>` starts the step with `python -m app.entry`, in the step's own Python environment. It makes the
environment when there is none; `kaosctl dev` makes one for every step. The settings come from a file, `params.yaml`, which you save in your app:

```yaml title="params.yaml"
--8<-- "examples/first-pipeline/try-locally/params.yaml"
```

`prepare` reads the folder `toy` of [page 1](run-it.md#put-a-few-files-in-a-dataset). `hello-world` also reads a
reference dataset, so make a folder of three small files for it first:

```bash
mkdir reference && printf 'a\n' > reference/a.txt && printf 'b\n' > reference/b.txt && printf 'c\n' > reference/c.txt
```

```bash
kaosctl step run prepare --params-file params.yaml --input dataset=./toy
kaosctl step run hello-world --params-file params.yaml --input reference=./reference
```

The output is abridged here:

```text
  input dataset: the folder ./toy
Running prepare: python -m app.entry (run local-20261112t034217z; ...)
[prepare] kept 2 of 3 files
Result of prepare (kept in .kaos/local/results/prepare.json):
  values: {"files": 2, "dropped": 1}
  read    dataset: dataset-dataset at 0fbede0b4d6d
  wrote   clean (dataset): .kaos/local/staged/clean
  wrote   dropped-files (artifact): .kaos/local/staged/dropped-files
Done: prepare exited 0. Next: kaosctl step run <the step that needs prepare>, or kaosctl build prepare
  input reference: the folder ./reference
  upstream prepare: from its last local run (prepare.json)
Running hello-world: python -m app.entry (run local-20261112t034217z; ...)
[hello-world] hello (my-experiment-v1): 2 files (12 bytes) in clean, 3 in the reference, 1 dropped by prepare: empty.txt
Result of hello-world (kept in .kaos/local/results/hello-world.json):
  values: {"files": 2, "size": 12, "reference": 3}
  read    reference: dataset-reference at 8306d71f5aba
  read    clean: dataset-myapp-clean at b2e7b6573672
  wrote   report (artifact): .kaos/local/staged/report
Done: hello-world exited 0. Next: kaosctl step run <the step that needs hello-world>, or kaosctl build hello-world
```

A step that needs an earlier step finds that step's last local result, so run them in order. Nothing is uploaded: outputs
stay in `.kaos/local/staged/<name>/`. Every flag, and what `--params-file` and `--python` do, is in the
[Reference](reference.md#kaosctl-step-run).

## Check the pipeline

```bash
kaosctl lint
```

```text
steps/hello_world/Dockerfile:3:1: info L-D07 RootUser: The image of step 'hello-world' runs as root (no USER). ...
steps/prepare/Dockerfile:3:1: info L-D07 RootUser: The image of step 'prepare' runs as root (no USER). ...
skipped L-E03 UnknownClass: the catalogue has no list of compute classes (give --context, the project's platform context)
skipped L-I03 Schedules: ...
0 errors, 0 warnings, 2 infos; 2 rules skipped. Rule set 2.1.0; facts from: built-in default.
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
