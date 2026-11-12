# Run context

Where the step runs. Most steps need only `step.start()` ([The step API](step.md)); this module is for code that
is not the step's entry (a library, a helper) and for the step's share of a shared HPC node.

```python
from kaos_lib import runtime
ctx = runtime.context()    # frozen dataclass; a value that was not given is None, and it never raises
runtime.run_id()           # the run's name, or None outside a pipeline run
runtime.usable_cpus()      # the cores to size worker pools by (see "A shared HPC node" below)
```

| field | what it is |
| --- | --- |
| `run_id` | the run's name |
| `app`, `project` | the app and its project |
| `step`, `kind` | the step's name and its kind |
| `experiment` | the experiment the run belongs to |
| `outputs_repo` | the app's outputs repository, `outputs-<app>` |
| `lakefs_endpoint` | `LAKEFS_ENDPOINT`, else `LAKEFS_URL` |
| `mlflow_uri` | `MLFLOW_TRACKING_URI` |
| `support` | the `kaos_lib.support` verdict for `$KAOS_LIB_SUPPORT` |
| `slot` | the step's share of a shared HPC (Slurm) node (a `Slot`, or None) |

The first six come from what the platform hands a pipeline step and are `None` on your own machine. The step's
config, inputs and upstream results are not here: they are `step.start().params`, `step.input()` and
`step.upstream()`.

## A shared HPC node

On HPC (Slurm), steps of one project can share a node: each gets one slot, a GPU with its cores and its memory share
(the runner sets `KUBECORE_SLOT_*`, so `context().slot` is a `Slot(gpus, cpus, mem_gib, shared)`). The GPU is
already the only one the step sees. Cores and memory are not hidden: `os.cpu_count()` still counts every core of
the node, and a step that uses more memory than its share is stopped. Size data loaders and caches by the slot:

```python
from kaos_lib import runtime
workers = min(configured_workers, runtime.usable_cpus())
slot = runtime.context().slot
if slot and slot.shared and slot.mem_gib:
    ...   # keep in-memory caches well under slot.mem_gib
```

`usable_cpus()` is the slot's cores, else the CPUs this process may run on, else the machine's.

A GPU step that runs alone on its node also gets `slot.gpus` (the GPU count of its class, from `KUBECORE_SLOT_GPUS`),
with `slot.shared` false and `cpus` and `mem_gib` None, so `context().slot.gpus` works the same alone and shared.
`CUDA_VISIBLE_DEVICES` (and `NVIDIA_VISIBLE_DEVICES`) reach the step as a clean comma list, for example `0,1,2,3`, with
no blanks around it. A CPU-only step on a node of its own has no slot: `slot` is None.
