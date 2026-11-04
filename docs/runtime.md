# Run context

```python
from kaos_lib import runtime
ctx = runtime.context()    # frozen dataclass, read from the environment; missing values are None
runtime.run_id()           # $KUBECORE_RUN_ID, or None
runtime.usable_cpus()      # the cores to size worker pools by (see "A shared Slurm node" below)
```

| field | variables (first non-empty wins) |
| --- | --- |
| `run_id` | `KUBECORE_RUN_ID` |
| `workflow` | `KUBECORE_WORKFLOW_NAME` |
| `app` | `KUBECORE_APP`, else `<app>` of `outputs_repo` = `outputs-<app>` |
| `project` | `KUBECORE_PROJECT` |
| `step` | `KUBECORE_STEP`, `STEP_NAME` |
| `outputs_repo` | `OUTPUTS_REPO`, `CHECKPOINT_BUCKET` |
| `lakefs_endpoint` | `LAKEFS_ENDPOINT`, `LAKEFS_URL` |
| `mlflow_uri` | `MLFLOW_TRACKING_URI` |
| `dataset_ref` | `KUBECORE_DATASET_REF`, `DATASET`, `DATASET_REPO@DATASET_REF` |
| `dataset_commit` | `KUBECORE_DATASET_COMMIT`, `DATASET_COMMIT` |
| `support` | the `kaos_lib.support` verdict for `$KAOS_LIB_SUPPORT` |
| `slot` | `KUBECORE_SLOT_GPUS`, `KUBECORE_SLOT_CPUS`, `KUBECORE_SLOT_MEM_GIB`, `KUBECORE_SLOT_SHARED` (a `Slot`, or None) |

Every step gets the run id, workflow name, results repository and endpoints; a value the step does not have is
`None` (`KUBECORE_APP`, `KUBECORE_PROJECT` and `KUBECORE_STEP` are not set yet; in a Slurm job the step comes from
`STEP_NAME`).

## A shared Slurm node

On Slurm, steps of one project can share a node: each gets one slot, a GPU with its cores and its memory share
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

`usable_cpus()` is the slot's cores, else the CPUs this process may run on, else the machine's. Outside a shared
node `slot` is None.
