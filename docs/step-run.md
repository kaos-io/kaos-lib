# Run one step on your machine: `kaosctl step run`

`kaosctl step run <step>` starts one step the way the platform starts it, in the step's own environment
([`kaosctl dev`](dev.md) makes it, and `step run` makes it for you if it is missing). No cluster, no login and no Docker are
needed, and no platform secret is ever used.

```bash
kaosctl step run data-summary
```

```text
  input --dataset-info: empty ({}); give it with --input
Running data-summary: python -m app.entry --params <1636 characters of composed params> --dataset-info ...
Data summary: dataset='dataset-default@v1' source='lakefs' seed=42
Outputs of data-summary (the platform's /work/output, here .kaos/local/work/data-summary/output):
  none written
Done: data-summary exited 0. Next: kaosctl step run <the step that needs data-summary>, or kaosctl build data-summary
```

## What is the same as on the platform

* **The command.** `python -m app.entry --params <params> --<name> <json> ...`, started in the step's folder.
* **The parameters.** `--params` receives the *content* of the composed `params.yaml`: your `config/` tree with its defaults
  and the overrides you give. It is composed here by the same composer the platform uses: the platform's pipeline engine, fetched
  as for [`kaosctl render`](render.md) (pass `--context` or `--engine-wheel`), or, in an app that still has its own
  `kubecore/` folder, that copy in the environment of `compose-and-validate`; `--set key=value` adds an override as on the submit form, and `--params-file FILE` uses a
  params file you already have.
* **The inputs.** A step receives one `--<name> <json>` for each output of the steps it `needs=`. Here the value comes from
  `--input name=<json>` or `--input name=@file.json`, else from the last local run of the step that produces it, else `{}`
  (what the platform passes for an output that is not there). Run the steps in order and each one finds the last one's
  outputs.
* **The outputs.** A step writes small results to `/work/output/<name>.json`. A laptop has no `/work`, so `kaosctl` maps
  that folder to `.kaos/local/work/<step>/` for the run (nothing is written to your machine's root). When the step ends, its
  outputs are printed and copied to `.kaos/local/outputs/<step>/<name>.json`.

## What is different, on purpose

* **No platform secrets or services.** The step runs with a short allowlist of your environment (`PATH`, `HOME`, locale,
  proxy and certificate settings). Endpoints, tokens, buckets and keys that the platform injects into a running step
  (`MLFLOW_TRACKING_URI`, `LAKEFS_*`, `CHECKPOINT_BUCKET`, cloud keys ...) are not passed, even if your own shell exports
  them. If the step's code names one of them, the command says so before it runs. A step that needs the service stops with
  its own error; a step that has a fallback (config, a default) runs on it. To try such a step, give it a stub: read the
  value in the step's code through a function you can replace in a test.
* **A sample of a dataset, on request.** `--dataset <repository>@<ref>` first downloads a small sample of that dataset with
  your own sign-in (`kaosctl login`), the same lakeFS client as `kaosctl dataset pull`, and puts its folder in
  `$KAOS_LOCAL_DATASET_DIR`. The sample takes root files first, then spreads over the dataset's folders, smallest files
  first, up to `--sample-mb` (default 50). Without `--dataset` nothing is downloaded and the run works offline.
* **Your hardware.** A step that needs a GPU runs on the CPU, or fails, like any program would.

## Options

| Option | |
|---|---|
| `step` | the step's name, as in `pipeline.py` |
| `[path]` | your app folder (default: the current folder) |
| `--set KEY=VALUE` | a config override for the composition (repeat for more) |
| `--params-file FILE` | use this `params.yaml` instead of composing one |
| `--input NAME=VALUE` or `NAME=@FILE` | the value of an upstream output |
| `--dataset REPO@REF`, `--sample-mb MB` | a small dataset sample (needs `kaosctl login`) |
| `--kaos-lib REQUIREMENT`, `--context FILE` | as in [`kaosctl dev`](dev.md), for the environment it may have to make |

The exit code is the step's own; `1` when the step could not be started (for example an unknown step name).

## Where things are

Everything a run writes is under `.kaos/local/` in your app folder, which has its own `.gitignore` (nothing in it is ever
committed): `params.yaml` (the composed parameters), `work/<step>/` (the mapped `/work`), `outputs/<step>/` (each step's
results), `data/` (dataset samples).

!!! note "Not `kaosctl run`"
    `kaosctl run --lock <mlflow-run-id> -- <command>` already exists: it replays the data a past MLflow run read.
    Running a step is `kaosctl step run`.
