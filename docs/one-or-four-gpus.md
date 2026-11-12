# One GPU or four on HPC (Slurm)

**You want** a training step on HPC (Slurm) that is right with one GPU and with four, without a second version of the code.

## The two shapes

On HPC a GPU step runs in one of two shapes.

| shape | what the step sees | what it costs |
|---|---|---|
| **one GPU, in a shared slot** | one GPU, its share of the cores and its share of the memory. Up to four such steps of your project share one node | a quarter of the node |
| **four GPUs, alone on a whole node** | all four GPUs of the node. Nothing else of your project runs on it | the whole node, for the whole time of the step |

Two or three GPUs are not a shape. The platform never hands a step part of a node's GPUs except as one slot.

## How you get each one

You set two things, and neither is in the step's code.

- **`gpu=True` on the step**, so that the run form offers it the GPU classes. Without it the form offers the CPU classes
  only.
- **The class, on the run form.** The field `<step>-class` lists the HPC (Slurm) classes next to the platform's own, and
  each class names its machine in its description, for example `4x A100-40GB, 2x EPYC 7452, 512 GB`. Pick the class of the
  GPU partition for the step.

Which shape the step gets is decided by the platform when it places the step, from three things:

| the step runs as | when |
|---|---|
| one GPU in a shared slot | your project has node sharing on, and the step can share: it declares a time limit with `walltime=` (without one it cannot, and `kaosctl lint` says so: `L-I01`) |
| four GPUs alone | node sharing is not on for your project, or the step does not declare `walltime=` |

Ask your platform contact whether node sharing is on for your project. The run form does not show the shape. The step reads
it at run time, as the next section shows.

## What the step sees

| | one GPU in a shared slot | four GPUs alone |
|---|---|---|
| `kaos_lib.runtime.context().slot` | `Slot(gpus=1, cpus=..., mem_gib=..., shared=True)` | `Slot(gpus=4, ...)` with `shared=False`; the cores and memory are not set |
| the GPUs the framework sees | one, numbered `0` | four, numbered `0` to `3` |
| `kaos_lib.runtime.usable_cpus()` | the cores of the slot | the cores the step may run on |

On the platform's own machines `context().slot` is `None`: read the GPU count from the framework then. Size every worker
pool by `usable_cpus()`, not by `os.cpu_count()`: on a shared node `os.cpu_count()` counts the cores of the whole node.
Use only the GPU the step is given. A step that touches a GPU that is not its own is stopped (status `GPUViolation`).

## What changes in the code

One thing: the step reads the count instead of writing it. This step is right on one GPU and on four.

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
`checkpoint.load` and `checkpoint.save`, and `step.result(...)` are the same on one GPU and on four. A resumable step that
continues in a new job may get the other shape than the job before it, which is why the code reads the count each time
and keeps nothing about it in the checkpoint.

## What to set on the run form

- `<step>-class`: the class of the GPU partition.
- `<step>-walltime`: the time limit. Without `walltime=` in `pipeline.py` it is 4 hours, and the step cannot share a node.
- `<step>-checkpoint-every`, when the step declares it.

## What it costs

Your project's HPC allocation is counted in node hours. A step alone on a node uses the whole node for the whole time it
runs, whatever it does with the four GPUs. Steps that share a node are covered by one booking of it, so four one-GPU steps cost about what one step alone costs.
Use four GPUs when one step really uses all four; otherwise let steps share.

## Mistakes and what you see

| the mistake | what you see |
|---|---|
| a GPU class chosen for a step without `gpu=True` | the run is refused before it starts: `step 'train' cannot run on class 'gpu-t4': it is a GPU machine and the step does not declare gpu=True. Add gpu=True to the step in pipeline.py to run it on a GPU machine.` |
| an HPC class for a step that produces a dataset | `step 'x' cannot run on class '...': a step that produces a dataset runs on the cluster for now. Choose one of: ...` The step runs on the platform's own machines ([Where it runs](produce-a-dataset.md#where-it-runs)) |
| a GPU step that produces a dataset | `kaosctl lint` warns: `L-W07` |
| no `walltime=` on a GPU step | `kaosctl lint` says, as an info: `L-I01`. The step cannot share a node |
| the number of GPUs written in the code (`device_count()` replaced by `4`) | on a shared slot the step sees one GPU and fails or touches a GPU that is not its own |
| a data loader sized by `os.cpu_count()` | on a shared node it starts as many workers as the whole node has cores |
| a limit longer than the site allows, and the step cannot continue | `TooLongNotResumable` ([Long jobs](long-jobs.md)) |

Next: [HPC (Slurm)](hpc.md) and [Bigger machines](bigger-machines.md).
