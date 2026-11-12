# kaos-lib

`kaos_lib` is the Python library of the KAOS platform, and `kaosctl` is its command line. Use them to keep your
training data in versioned **datasets**, read a dataset from a pipeline step or your laptop, save run **outputs**
(checkpoints, results) and log to your project's **MLflow**.

**Documentation: <https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/index.html>** : quickstart, guides,
troubleshooting and a complete command and API reference. The site is rebuilt with every prerelease, so it shows the
newest rc, which can be ahead of the version you have installed.

## Install

Python 3.9 or newer, in a virtual environment. kaos-lib is served from its own package index, not PyPI; the
[Install page](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/install.html) always shows the exact
current command and version:

```bash
pip install --index-url https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib-rc/simple/ \
    --extra-index-url https://pypi.org/simple/ "kaos-lib[zitadel]==<version>"
```

Extras: `zitadel` (read datasets that another project shares with yours) and `mlflow` (log to MLflow from a step).
Check it with `kaosctl --version`.

## The 5-minute path

Run these inside your app folder, so `kaosctl` knows your project.

```bash
kaosctl login                                                     # opens your browser once
kaosctl dataset create cats --layout yolo --classes cat,kitten    # dataset-cats (without --layout it is empty)
kaosctl dataset push ./dataset-cats dataset-cats -m "first images"   # checks your files, opens a pull request
kaosctl dataset release dataset-cats                              # after the pull request is merged: v1
```

```python
from kaos_lib import datasets, outputs

data = datasets.materialize(datasets.DatasetRef.parse("dataset-cats@v1"))   # downloads it once, returns the path
with outputs.run("myapp", "exp1", "run-7") as r:                            # your results, one commit per run
    r.save("./ckpt")
    r.finish({"dataset_ref": "dataset-cats@v1"})
```

The command is `kaosctl`.

## Check your pipeline

`kaosctl lint` reads `pipeline.py` and the files around it and reports problems before you open a pull request. It
never runs your code and needs no login: see the [guide](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/lint.html).

## Try a step on your machine

`kaosctl dev` makes a Python environment for each step, `kaosctl step run <step>` runs one step the way the platform runs
it, and `kaosctl build [step]` builds its image with the container engine you already have (it tells you what to install if
you have none; it never installs anything). No cluster and no login. Guides:
[set up](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/dev.html),
[run a step](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/step-run.html),
[build an image](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/build.html).

## Contributing

```bash
pip install -e ".[test]" && pytest                          # no network needed
pip install -r docs/requirements.txt -e . && mkdocs serve    # the documentation site
```

The CLI reference is generated from the code on every docs build (never edit `docs/generated/`), and the site must
build with `mkdocs build --strict`. The build also runs `docs_check.py` (words, removed names, links across this
site and both pipeline templates): see [Develop](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/develop.html).

License: Apache-2.0.
