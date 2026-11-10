# Render your pipeline locally

```bash
kaosctl render --context pipeline-context.yaml
```

renders `pipeline.py` on your machine with **the same pipeline engine the platform's CI uses**, and writes
`out/raw-workflow-template.yaml`. A render that passes here passes in CI; an error you get here is the error CI would
give, without a push.

Your app holds `pipeline.py`, `config/` and `steps/`. It holds no copy of the engine: the platform runs its own
release, so a platform update never needs a change in your repository.

## Which engine

kaosctl uses the release the platform pinned for your app. The first of these that exists:

1. `--engine-wheel 'URL#sha256=<checksum>'`
2. the environment variable `KAOS_ENGINE_WHEEL` (same form)
3. `--context FILE`: the platform's pipeline-context file of your app, which has an `engine:` block

With none of them the command stops and says so. It never guesses a version.

## What it does on your machine

- Downloads the engine once and checks its SHA-256. A download with another checksum is deleted and nothing is installed.
- Installs it into `.kaos/engine/.venv` inside your app folder. The folder ignores itself in git. Nothing is installed
  outside your repository.
- Needs Python 3.11 or newer. kaosctl uses one your machine already has and never installs a Python.
- Runs the engine isolated from your app's folders: only `pipeline.py` and `config/` are read.

The second run reuses the environment and downloads nothing. A new engine release (a new checksum) replaces it.

## Options

| option | meaning |
| --- | --- |
| `path` | your app folder (default: the current folder) |
| `--context FILE` | the platform's pipeline-context file |
| `--engine-wheel URL#sha256=HEX` | an engine release you name yourself |
| `--profile hera\|yolo` | the config-schema profile. Default: `yolo` when your `config/` has a `quantization` section, else `hera` |

## The same engine composes your parameters

[`kaosctl step run`](step-run.md) composes `params.yaml` with this engine too, with the same options, when your app
has no engine copy of its own.

## When it fails

| message | what to do |
| --- | --- |
| `no pipeline engine was given` | pass `--context` or `--engine-wheel` |
| `the context file ... has not pinned an engine` | your platform has not published an engine for this app yet; ask the platform team |
| `has SHA-256 ..., but ... says ...` | the download is not the release that was pinned; try again, then tell the platform team |
| `needs Python 3.11 or newer` | install one (python.org, or `uv python install 3.12`) and run the command again |
| `the render failed (exit code 1)` | your `pipeline.py` raised; the message above it says where |
