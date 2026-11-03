# Run context

```python
from kaos_lib import runtime
ctx = runtime.context()    # frozen dataclass, read from the environment; missing values are None
runtime.run_id()           # $KUBECORE_RUN_ID, or None
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

Nothing is hardcoded: when the platform changes what it injects, the names above keep working. Today the enhancer
injects the run id, workflow name, outputs repository and endpoints into every step; `KUBECORE_APP`,
`KUBECORE_PROJECT` and `KUBECORE_STEP` are not injected yet (on MeluXina the step comes from `STEP_NAME`).
