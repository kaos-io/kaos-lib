# Support window

Every release ships `release.json` (in the package as `kaos_lib/_release.json`, and in the public release bucket
as `<channel>/<tag>/release.json`, plus `tag`, `channel`, `commit`, `recommended` and the files' sha256):

```json
{"version": "0.4.0", "supported": ">=0.3", "deprecated": [{"range": "<0.3", "unsupported_after": "YYYY-MM-DD"}],
 "breaking": false, "migration": "<url>"}
```

The newest release's file is the policy. `kaos_lib.support.check(installed, support_json)` returns
`{verdict, message, fix}`: `current`, `behind` (older, still supported), `deprecated` (outside `supported`, inside
a deprecated range whose `unsupported_after` has not passed, or that sets none), `unsupported` (outside
`supported` and past any deadline). Metadata that cannot be read is `unknown`: a warning, never a failure.

- Pipeline steps: when the platform sets `$KAOS_LIB_SUPPORT`, importing `kaos_lib` (or the `kubecore` shim) logs
  the verdict on stderr, tags the MLflow run `kaos_lib.support` (the active run, or `$MLFLOW_RUN_ID`), and stops
  the step only when unsupported.
- `kaosctl`: reads the policy from the project lakeFS (`/kaos/v1/ui`, key `kaos_lib_support`), else the newest
  public `release.json` of its channel, else the packaged `_release.json`. Reads warn; `create`, `release` and `push` are refused when the platform says unsupported.
  Offline or without platform metadata nothing is refused.
