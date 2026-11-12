# kaos-lib

kaos-lib is the Python library of the platform (`import kaos_lib`), and `kaosctl` is its command. You write ML
pipelines with it: each step is a small Python program that reads data, does work and hands a result on.

--8<-- "generated/built.md"

This guide is one path. Each page adds one idea to the app you have, and ends with something you ran. Start at the
first page and stop wherever you have what you need. The app is the one the hera template creates.

| | page | what you do |
|---|---|---|
| 1 | [Run it](run-it.md) | create a pipeline from the template, run it as it is, read its result |
| 2 | [Your first step](first-step.md) | read the 17 lines of a step and change them |
| 3 | [Settings](settings.md) | a value in `config/` becomes a field on the run form |
| 4 | [Read data](read-data.md) | declare an input and pick its version on the form |
| 5 | [Pass things on](pass-things-on.md) | hand a value, then a file, to the next step |
| 6 | [Produce a dataset](produce-a-dataset.md) | seal a version, promote it, read it from another pipeline |
| 7 | [Bigger machines](bigger-machines.md) | pick a class; GPU steps |
| 8 | [Long jobs](long-jobs.md) | checkpoints and resume |
| 9 | [HPC (Slurm)](hpc.md) | the same step on a Slurm site |
| 10 | [Try it locally](try-it-locally.md) | run, test and check a step on your laptop |
| 11 | [A real pipeline](a-real-pipeline.md) | the yolo pipeline, read with what you know |
| 12 | [Reference](reference.md) | the step API, `pipeline.py`, limits, commands |

The code on every page is a file that is run and checked when this guide is built.
