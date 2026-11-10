# Support policy and upgrades

Every release states which kaos-lib versions are supported (`release.json`, packaged as `kaos_lib/_release.json`):

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
  the step only when unsupported. A step's image is built by the platform, so the log never tells you to
  `pip install`: older but supported is one neutral line ("Nothing to do: a platform update brings the newer
  version"); deprecated and unsupported say that the image must be rebuilt and who does it (the platform when
  the Dockerfile declares `ARG KAOS_LIB_PACKAGE`, you when the Dockerfile pins kaos-lib itself).
- `kaosctl`: reads the policy from the project lakeFS (`/kaos/v1/ui`, key `kaos_lib_support`), else the newest
  public `release.json` of its channel, else the packaged `_release.json`. Reads warn; `create`, `release` and `push` are refused when the platform says unsupported.
  Offline or without platform metadata nothing is refused.

## Upgrade

```bash
kaosctl --version         # the installed version, its channel, and the version the platform recommends
kaosctl upgrade --dry-run # print the pip command
kaosctl upgrade           # run it
```
