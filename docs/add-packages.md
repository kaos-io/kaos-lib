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

To build the image on your machine before you push, run `kaosctl build <step>`. It needs a container engine, and prints
the same findings as `kaosctl lint`.
