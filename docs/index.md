# kaos-lib

kaos-lib is the KAOS platform library, and `kaosctl` is its command. It gives pipeline steps and people one way to
work with the platform's data:

- **Datasets**: each dataset is its own lakeFS repository `dataset-<name>`, with versions `v1`, `v2`, … Create,
  fill, validate, release and read them, from a laptop or from a pipeline step.
- **Outputs**: every ML app writes its results to its own repository `outputs-<app>`, one commit per step per run.
- **MLflow**: one call configures MLflow with the right credential, with no plugin file to copy.
- **Run context** and **data lock**: what the platform injected into a step, and the exact dataset commits a run read,
  recorded on its MLflow run and replayable.

--8<-- "generated/built.md"

## Where to start

| You want to… | Read |
| --- | --- |
| install it | [Install](install.md) |
| make a dataset and use it in a pipeline | [Quickstart](quickstart.md) |
| understand datasets, versions and layouts | [Datasets](datasets.md) |
| look up a command | [CLI reference](generated/cli.md) |
| look up a function | [Python API](api.md) |

kaos-lib talks to **kaos-lake**, the platform's lakeFS. Every app repository the platform creates carries
`.kubecore/dataset-config.yaml`, which tells kaos-lib where your project's lakeFS is and how to sign in. Run
`kaosctl` inside your app folder and you never type a URL or a password.

The pipeline templates ([hera](https://novelcore.github.io/hera-pipeline-template/) and
[yolo](https://novelcore.github.io/yolo-pipelines-template/)) already use kaos-lib in their steps: start from one of
them to build a pipeline.
