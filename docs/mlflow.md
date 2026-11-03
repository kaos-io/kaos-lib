# MLflow

```python
from kaos_lib.mlflow import mlflow

client = mlflow()          # MLFLOW_TRACKING_URI, auth from the chain below; returns an MlflowClient
import mlflow as mlf       # the mlflow module is configured too: mlf.start_run(), mlf.log_metric(...)
```

`mlflow(tracking_uri=None, token=None)` sets the tracking URI and `MLFLOW_TRACKING_AUTH=zitadel`, and asks the chain
once, so a missing credential fails before the step does any work. The bearer is the first of:

1. an explicit token, `mlflow(token=...)`, else `$MLFLOW_TRACKING_TOKEN` (Slurm jobs get one);
2. the step's machine key: `ZITADEL_MACHINE_KEY_FILE`, `ZITADEL_DOMAIN` and `ZITADEL_MLFLOW_PROJECT_ID`, minted
   for the organisation's Zitadel project and minted again two minutes before it expires;
3. your `kaosctl login` session. Inside your app clone it carries the organisation project's audience; an expired
   session, or one without that audience, is a one-line error telling you to log in again. Outside a pipeline, set
   `MLFLOW_TRACKING_URI` yourself.

Project MLflow accepts only tokens audienced to the organisation's Zitadel project.

kaos-lib registers the MLflow request-auth provider `zitadel` (entry point `mlflow.request_auth_provider`). A step
whose environment has `MLFLOW_TRACKING_AUTH=zitadel` (the platform injects it) is authenticated with no code and no
copied plugin file. MLflow asks the provider on every request, so long runs never send an expired token.
`kaos_lib.mlflow.token()` returns the current bearer.

Needs the `mlflow` extra: `pip install "kaos-lib[mlflow]==<version>"` ([Install](install.md)).
