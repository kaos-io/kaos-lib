# Add Python packages to a step

**You want** a step to import a package that the template's image does not have, for example `pandas` or the MLflow
client.

Each step has its own image, built from `steps/<name>/Dockerfile`. A package is installed there with one more `RUN`
line, between the two lines for kaos-lib and the `COPY`:

```dockerfile title="steps/<name>/Dockerfile"
--8<-- "examples/flows/packages/Dockerfile"
```

- Keep `ARG KAOS_LIB_PACKAGE` and the `pip install` that uses it. The platform builds your image with the kaos-lib
  version it chooses by replacing the value of the argument. `kaosctl lint` reports a step that loses them (`L-D01`,
  `L-D02`).
- Pin each package (`pandas==2.2.3`), so that two builds give the same image.
- For the MLflow client of [See your results](see-your-results.md), install `mlflow-skinny>=3,<4` the same way.
- A GPU step needs a CUDA-enabled `torch`: [Bigger machines](bigger-machines.md#when-the-gpu-is-not-there).

The image is built from the folder `steps/<name>/` alone, so `COPY` only files inside it (`L-D04`), keep data out of
the image and read it with a dataset instead (`L-D06`), and give the image no `--platform=` (`L-D03`). Every rule is on
its page in [Lint checks](lint.md). Only the step whose folder changed is built again when you send a change in
([page 2](first-step.md#send-the-change-in)).

## Add a system package

A system package such as `libgl1` is installed with `apt-get` in its own `RUN` line. Install without the recommended
extras, and remove the package lists in the same line, so that the layer stays small (`L-D06` warns otherwise):

```dockerfile title="steps/<name>/Dockerfile"
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 \
    && rm -rf /var/lib/apt/lists/*
```

Put it before the lines for the Python packages. Pin nothing here, and install only what the step uses.

## Share code between steps {#share-code-between-steps}

Each image is built from the folder of its step alone. So `COPY ../common ./common` is refused (`L-D04`): the build
cannot see the folder next to yours. Two ways to share a helper module:

1. **Copy it into each step.** Put `helpers.py` in `steps/a/app/` and in `steps/b/app/`, and import it as
   `from app import helpers`. It is simple. When you change it, change both.
2. **Make it a package.** Put it in its own repository, and install it in the `Dockerfile` of each step, pinned, like any
   other package: `RUN pip install --no-cache-dir "my-helpers==1.4.0"`. One change, then a new version, then a new pin.

Use the copy for a small file. Use a package once three steps share it.

To build the image on your machine before you push, run `kaosctl build <step>`. It needs a container engine, and prints
the same findings as `kaosctl lint`.
