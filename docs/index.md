# kaos-lib

kaos-lib is the Python library of the KAOS platform (`import kaos_lib`), and `kaosctl` is its command. They give
you one way to work with your project's data and results, from your laptop or from a pipeline step:

- **Datasets**: versioned collections of files, `dataset-<name>@v1`, `@v2`, … Create, fill, check, release and read them.
- **Outputs**: save checkpoints and results of a run, and resume after an interruption.
- **MLflow**: log to your project's MLflow with one call.
- **Data lock**: record which dataset versions a run read, and replay them.

--8<-- "generated/built.md"

This site is rebuilt with every prerelease, so it describes the newest published kaos-lib; it may be ahead of the
version you have installed (`kaosctl --version`).

## Where to start

| You want to… | Read |
| --- | --- |
| install it | [Install](install.md) |
| make a dataset and use it in a pipeline | [Quickstart](quickstart.md) |
| understand datasets, versions and layouts | [Datasets](datasets.md) |
| write a pipeline step, and know what the platform gives it | [How a step works](steps.md) |
| copy a complete step: data check, training, evaluation, export, registration | [Step examples](step-examples.md) |
| know which data every step of a run reads | [How steps use datasets](steps-and-datasets.md) |
| keep a long run alive through interruptions | [Long runs: checkpoints](checkpoint.md) |
| fix an error message | [Troubleshooting](troubleshooting.md) |
| look up a command or a function | [CLI](generated/cli.md), [Python API](api.md) |

Run `kaosctl` inside your app folder and it already knows your project: you never type a URL or a password, only
sign in once with `kaosctl login`.

The pipeline templates [hera](https://novelcore.github.io/hera-pipeline-template/) and
[yolo](https://novelcore.github.io/yolo-pipelines-template/) already use kaos-lib: start from one of them to build
a pipeline.
