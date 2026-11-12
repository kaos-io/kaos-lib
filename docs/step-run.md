# Run one step on your machine: `kaosctl step run`

`kaosctl step run <step>` starts one step the way the platform starts it, in the step's own environment
([`kaosctl dev`](dev.md) makes it, and `step run` makes it for you if it is missing). No cluster, no login and no Docker are
needed, and no platform secret is ever used.

```bash
kaosctl step run prepare --input dataset=./toy
```

```text
  input dataset: the folder ./toy
  upstream data-check: from its last local run (data-check.json)
Running prepare: python -m app.entry (the step context holds 412 characters of composed params)
Result of prepare (kept in .kaos/local/results/prepare.json):
  values: {"rows": 250, "dropped": 0}
  read    dataset: dataset-toy at 5f2c9a1b0d3e
  wrote   clean (dataset): .kaos/local/staged/clean
Done: prepare exited 0. Next: kaosctl step run <the step that needs prepare>, or kaosctl build prepare
```

## What is the same as on the platform

* **The command.** `python -m app.entry` with no arguments, started in the step's folder. Everything the step needs
  reaches it through `kaos_lib.step` ([The step API](step.md)), exactly as on the platform.
* **The parameters.** `step.start().params` is the composed config: your `config/` tree with its defaults and the
  overrides you give. It is composed here by the same composer the platform uses: the platform's pipeline engine, fetched
  as for [`kaosctl render`](render.md) (pass `--context` or `--engine-wheel`); `--set key=value` adds an override as on
  the submit form, and `--params-file FILE` uses a params file you already have.
* **The run and the experiment.** `ctx.run` is `local-<date and time>`, new for every local run. `ctx.experiment`
  is `experiment.name` of your config, or the app's name when there is none.
* **The checks.** A step that names an input it did not declare, hands on a value that is too large, or ends without
  `step.result()` fails here with the same message.
* **The results of earlier steps.** `step.upstream("<step>")` gives the result of that step's last local run. Run the
  steps in order and each one finds the last one's result and what it produced. A step that has not run here is seen as
  not run, as a skipped step is on the platform. `--upstream STEP=<json>` or `--upstream STEP=@file.json` gives a result
  by hand.

## What is different, on purpose

* **Inputs are folders on your machine.** Give each input the step declares in `inputs=` with `--input`:
  `--input dataset=./a-few-files` uses a folder as it is; `--input dataset=dataset-toy@v1` downloads a small sample
  of that dataset version with your own sign-in (`kaosctl login`). The sample takes root files first, then spreads
  over the dataset's folders, smallest files first, up to `--sample-mb` (default 50). With folders only, the run
  works offline.
* **Nothing is uploaded.** What the step writes into `step.output("<name>")` is kept in `.kaos/local/staged/<name>/`,
  where the next step finds it with `step.input("<name>")`. No dataset version and no model is created.
* **No platform secrets or services.** The step runs with a short allowlist of your environment (`PATH`, `HOME`, locale,
  proxy and certificate settings). Endpoints, tokens and keys that the platform gives a running step
  (`MLFLOW_TRACKING_URI`, `LAKEFS_*`, cloud keys ...) are not passed, even if your own shell exports them. If the
  step's code names one of them, the command says so before it runs. A step that needs the service stops with its own
  error; a step that has a fallback (config, a default) runs on it.
* **Your hardware.** A step that needs a GPU runs on the CPU, or fails, like any program would.

## Options

| Option | |
|---|---|
| `step` | the step's name, as in `pipeline.py` |
| `[path]` | your app folder (default: the current folder) |
| `--set KEY=VALUE` | a config override for the composition (repeat for more) |
| `--params-file FILE` | use this `params.yaml` instead of composing one |
| `--input NAME=FOLDER` or `NAME=REPO@REF` | what the step gets for the input `NAME`: a local folder, or a small sample of a dataset version (needs `kaosctl login`) |
| `--sample-mb MB` | the most a sample downloads |
| `--upstream STEP=JSON` or `STEP=@FILE` | the result of a step this one needs |
| `--kaos-lib REQUIREMENT` or `PATH`, `--context FILE` | as in [`kaosctl dev`](dev.md), for the environment it may have to make |

The exit code is the step's own; `1` when the step could not be started (for example an unknown step name, or an
input that was not given).

## Where things are

Everything a run writes is under `.kaos/local/` in your app folder, which has its own `.gitignore` (nothing in it is ever
committed): `params.yaml` (the composed parameters), `work/<step>/` (the step's working folder), `staged/<name>/` (each
input, and everything a step produced), `results/<step>.json` (each step's result).

!!! note "Not `kaosctl run`"
    `kaosctl run --lock <mlflow-run-id> -- <command>` already exists: it replays the data a past MLflow run read.
    Running a step is `kaosctl step run`.
