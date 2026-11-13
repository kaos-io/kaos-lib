# GPUs on HPC (Slurm)

**You want** to know how many GPUs a GPU step gets on HPC (Slurm), what it costs, and what to write so the same step code
is right either way.

## What you get

Node sharing is a setting of your whole project. The platform sets it, not you and not the step. You do not pick one GPU or
four: there is no such choice in the code or on the run form.

| node sharing for your project | what every GPU step on HPC gets |
|---|---|
| **on** (the delivered setting) | **one GPU**. Up to four steps share one node. The step sees one device, and `kaos_lib.runtime.context().slot` says so. The first step on a node gets one GPU too. A step cannot ask for four |
| **off** (a platform setting, changed on request) | the whole node, alone: it sees all four GPUs |

To change the setting, ask your platform contact.

## What the step sees

| | sharing on | sharing off |
|---|---|---|
| `kaos_lib.runtime.context().slot` | `Slot(gpus=1, cpus=..., mem_gib=..., shared=True)` | `Slot(gpus=4, ...)` with `shared=False`; the cores and memory are not set |
| the GPUs the framework sees | one, numbered `0` | four, numbered `0` to `3` |
| `kaos_lib.runtime.usable_cpus()` | the cores of the slot | the cores the step may run on |

On the platform's own machines `context().slot` is `None`: read the GPU count from the framework then. Size every worker
pool by `usable_cpus()`, not by `os.cpu_count()`: on a shared node `os.cpu_count()` counts the cores of the whole node. Use
only the GPU the step is given. A step that touches a GPU that is not its own is stopped (status `GPUViolation`).

## What it costs

Your project's HPC allocation is charged by the whole node, for the time the node is held. Four steps that share a node cost
one node. A single step with nobody joining also costs one node, plus a short wait while the node waits for other steps to
join. With sharing on, start the steps of a pipeline together to use all four slots.

## What changes in the code

One thing: the step reads the count instead of writing it. This step is right with sharing on (one GPU) and off (four).

```python title="pipeline.py"
--8<-- "examples/flows/gpus/pipeline.py:6:8"
```

```python title="steps/train/app/entry.py"
--8<-- "examples/flows/gpus/steps/train/app/entry.py"
```

```yaml title="config/train.yaml"
--8<-- "examples/flows/gpus/config/train.yaml"
```

```yaml title="config/dataset.yaml"
--8<-- "examples/flows/gpus/config/dataset.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/gpus/config/config.yaml"
```

What the code does with the count:

- the batch is `batch_per_gpu` times the GPUs, so each GPU gets the same share on one or on four;
- the loader workers follow `usable_cpus()`;
- with more than one GPU the model is wrapped in `DataParallel`, which splits each batch over the GPUs the step sees. For
  larger models, start a process for each GPU with the launcher of your framework instead, and take the number of processes
  from the same count.

## What does not change

The inputs, the outputs, the checkpoints and the result. `step.input("dataset")`, `step.output("model")`,
`checkpoint.load` and `checkpoint.save`, and `step.result(...)` are the same with one GPU and with four. The code reads the
count each time and keeps nothing about it in the checkpoint.

## What to set

- `gpu=True` on the step, so that the run form offers it the GPU classes. Without it the form offers the CPU classes only.
- `<step>-class` on the run form: the class of the GPU partition. Each class names its machine in its description.
- `<step>-walltime` on the run form: the time limit. Every step has one. `walltime=` in `pipeline.py` is only the default of this field, and without it the default is 4 hours.

## Mistakes and what you see

| the mistake | what you see |
|---|---|
| a GPU class chosen for a step without `gpu=True` | the run is refused before it starts: `step 'train' cannot run on class 'gpu-t4': it is a GPU machine and the step does not declare gpu=True. Add gpu=True to the step in pipeline.py to run it on a GPU machine.` |
| an HPC class for a step that produces a dataset | `step 'x' cannot run on class '...': a step that produces a dataset runs on the cluster for now. Choose one of: ...` The step runs on the platform's own machines ([Where it runs](produce-a-dataset.md#where-it-runs)) |
| a GPU step that produces a dataset | `kaosctl lint` warns: `L-W07` |
| the number of GPUs written in the code (`device_count()` replaced by `4`) | with sharing on the step sees one GPU and fails, or touches a GPU that is not its own |
| a data loader sized by `os.cpu_count()` | on a shared node it starts as many workers as the whole node has cores |
| a limit longer than the site allows, and the step cannot continue | `TooLongNotResumable` ([Long jobs](long-jobs.md)) |

Next: [HPC (Slurm)](hpc.md) and [Bigger machines](bigger-machines.md).
