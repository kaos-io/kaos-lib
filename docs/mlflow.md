# MLflow

Use this in a pipeline step (or on a laptop after `kaosctl login`) to log to your project's MLflow with no plugin
file and no token handling.

```python
from kaos_lib.mlflow import mlflow

client = mlflow()          # MLFLOW_TRACKING_URI, auth from the chain below; returns an MlflowClient
import mlflow as mlf       # the mlflow module is configured too: mlf.start_run(), mlf.log_metric(...)
```

`mlflow(tracking_uri=None, token=None)` sets the tracking URI and the sign-in method, and asks the chain
once, so a missing credential fails before the step does any work. The bearer is the first of:

1. an explicit token, `mlflow(token=...)`, else `$MLFLOW_TRACKING_TOKEN` (HPC (Slurm) jobs get one);
2. the step's own credential, which the platform provides to pipeline steps and kaos-lib renews before it expires;
3. your `kaosctl login` session. Inside your app clone it carries the organisation project's audience; an expired
   session, or one without that audience, is a one-line error telling you to log in again. Outside a pipeline, set
   `MLFLOW_TRACKING_URI` yourself.

Your project's MLflow accepts only tokens issued for your organisation.

In a pipeline step MLflow is authenticated with no code and no plugin file: kaos-lib registers the request-auth
provider `zitadel` that MLflow selects through `MLFLOW_TRACKING_AUTH=zitadel`, which the step already has. MLflow asks the provider on every request, so long runs never send an expired token.
`kaos_lib.mlflow.token()` returns the current bearer.

Needs the `mlflow` extra: `pip install "kaos-lib[mlflow]==<version>"` ([Install](install.md)).

## Run tags kaos-lib writes

| tag | written by | holds |
| --- | --- | --- |
| `kaos_lib.data.<repo>.commit` | kaos-lib when the run ends in a pipeline step ([Results](results.md)) | the commit(s) of dataset `<repo>` the run read, comma-separated |
| `kaos_lib.data.<repo>.owner` | the same | the owning project, for a [shared dataset](shared-datasets.md) |
| `kaos_lib.support` | importing `kaos_lib` in a step whose `$KAOS_LIB_SUPPORT` is set | the [support verdict](support-window.md): `current`, `behind`, `deprecated` or `unsupported` |

The run also gets one artifact per step, `ledger/<step>.json`: what that step read and wrote. Filter on the tags in the MLflow UI to find every run that read a
dataset commit, or that ran an unsupported kaos-lib.

## A 401 from MLflow

Your `kaosctl login` session must have been created inside your app folder: a login from elsewhere does not carry
the access MLflow needs. Run `kaosctl login` again inside the app folder.
