# Set up your steps: `kaosctl dev`

`kaosctl dev` gives every step of your pipeline its own Python environment, so you can open a step in your editor and
run it without working out its dependencies. It needs Python and a network connection to the package index. It does not
need Docker, a login or access to the platform.

```bash
cd my-app                 # your app folder (it holds pipeline.py and steps/)
kaosctl dev
```

```text
data-check: setting up steps/data_check/.venv ...
export-report: setting up steps/export_report/.venv ...
  data-check: created (Python 3.11.9, kaos-lib from the default of ARG KAOS_LIB_PACKAGE in the Dockerfile)
  export-report: created (Python 3.11.9)
  model-training: skipped, its dependencies are large (torch ...). Set it up with: kaosctl dev --step model-training
Next: kaosctl step run <step>
```

## What it does

For each step of `pipeline.py`:

1. **Reads what the step installs, without running anything.** The `pip install` lines of its `Dockerfile` are the
   declaration, because that is what the image has. A `-r requirements.txt` they name is read; a Poetry step
   (`poetry export` in the Dockerfile) is read from `poetry.lock`'s main group, or from `pyproject.toml` when there is no
   lock file; a Dockerfile that installs nothing falls back to `requirements.txt` or `pyproject.toml`. Nothing of your code
   or of a dependency's build is executed to find out.
2. **Picks the Python of the step's image.** `FROM python:3.11-slim` means Python 3.11. If this machine has a Python 3.11
   (found on the `PATH`, or by `uv`), that one is used. If not, the Python that runs `kaosctl` is used and the command says
   so, with the link to install the right one. `uv` never downloads a Python by itself.
3. **Creates `steps/<name>/.venv`** and installs the dependencies into it. It uses [`uv`](https://docs.astral.sh/uv/)
   when it is installed (much faster) and `python -m venv` with `pip` otherwise. When `uv` is missing, the command prints
   the link to install it and carries on with `pip`; it never installs `uv` for you.
4. **Adds kaos-lib** to a step that uses it (its Dockerfile declares `ARG KAOS_LIB_PACKAGE`, or its code imports
   `kaos_lib`). A step that does not, such as a step that needs only PyYAML, does not get it.
5. **With `--vscode`, writes `steps/<name>/.vscode/settings.json`** so VS Code picks that environment when you open
   the step's folder (`code steps/data_check`). An existing settings file is merged, not replaced; one with comments
   in it is left alone. Without `--vscode` nothing is written outside `.venv`.

Run it again whenever you like: an environment whose dependencies did not change is left as it is (`up-to-date`).

## Which kaos-lib version

The platform's build installs the kaos-lib version the platform chose. A laptop does not know that choice, so `kaosctl dev`
takes, in this order:

| Order | Source | How |
|---|---|---|
| 1 | what you pass | `--kaos-lib "kaos-lib[zitadel]==0.5.0rc1"` (a whole pip requirement), or the path of a kaos-lib checkout, wheel or archive on your machine |
| 2 | the platform's context file | `--context pipeline-context.yaml`: its `kaosLib.spec` |
| 3 | your Dockerfile's default | the value of `ARG KAOS_LIB_PACKAGE="..."` |
| 4 | the installed `kaosctl` | the same version as the command you are running |

The line for each step says which one was used.

## Steps with large dependencies

A step that depends on torch, TensorFlow, JAX, CUDA libraries or similar downloads several GB. Without arguments,
`kaosctl dev` skips such steps and tells you how to set one up. Name it (`--step model-training`) or use `--all` to
include them. Training on a laptop is rarely the point; trying a step's code on a small sample often is.

## Options

| Option | |
|---|---|
| `[path]` | your app folder (default: the current folder) |
| `--step NAME` | set up only this step; repeat for more |
| `--all` | include steps with large dependencies |
| `--kaos-lib REQUIREMENT` or `PATH` | the kaos-lib to install |
| `--vscode` | also write `.vscode/settings.json` in each step folder |
| `--context FILE` | the platform's context file |

Exit code `0` when every selected step is ready, `1` when one failed (the installer's output is printed).

## What it never does

It installs nothing outside your app folder: environments live in `steps/<name>/.venv` (each has its own `.gitignore`, so
they are never committed), and `kaosctl` never installs `uv`, Python, Docker or anything else on your machine. It writes
no secret, and needs no cluster.
