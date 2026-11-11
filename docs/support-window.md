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

## In a pipeline: who picks the version

**The platform does.** Every time it builds your step images, the platform's build passes the version it chose to
each step Dockerfile:

```dockerfile
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/<commit>.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
```

The value in the `ARG` line is only the default for a build on your own computer. In the platform's build it is
replaced, so changing it does not change what your pipeline runs. Keep the name `KAOS_LIB_PACKAGE` in every step
that installs the package: a step without it keeps its default forever.

The value is a whole pip requirement: the package's name and extras, then the version. In the platform's build it
is the requirement of the newest kaos-lib release on the platform's channel, for example
`kaos-lib[zitadel] @ https://<registry>/kaos_lib-X.Y.Z-py3-none-any.whl#sha256=<hex>`, with no change in your
repository.

## Your range: `.kaos/compat.yaml`

```yaml
kaos-lib: ">=0.4.0rc15,<0.5"
```

This file says which released versions your code works with. The platform only moves your app to a released
version inside this range. You can edit it like any other file in your app. While the package is installed from a
commit (the `@ https://…` form), every commit counts as inside your range; so does every version when the file is
missing.

## How a new version arrives

- **Inside your range** (for example 0.4.1 → 0.4.2): the platform rebuilds your step images with the new version
  and updates your pipeline. Nothing is committed to your repository and you do nothing.
- **Outside your range** (for example 0.4.2 → 0.5.0): your images stay on the version they have, and the platform
  opens a **bump pull request**. Until you merge it, every build of your app keeps the version it already runs.

The bump pull request is on the branch `kaos-lib/bump-<version>`, for example `kaos-lib/bump-0.5.0`. It changes
`.kaos/compat.yaml` to the new range (and any code the release needs changed, if it names one), and its description
has the release notes of that version.

- **Merge it** when you are ready: the push builds your images with the new version, the same way any push does.
  Check your next run.
- **Close it** if you are not ready: the platform does not open a second pull request for the same version, and
  your app keeps the version it runs now. When a newer version comes out, you get a new pull request for that one,
  and the platform closes the older one.

## Hold a version

- **From your repository**: narrow the range. `kaos-lib: "==0.4.2"` keeps exactly 0.4.2; a newer released version
  arrives as a bump pull request instead of a rebuild.
- **Through your KAOS contact**: ask to pin your app to one version. A pinned app is never moved when the
  platform's default changes, and gets no bump pull requests.

## Which version a pipeline runs

- The first line of a step's log, when the step prints it (the template steps do): `kaos-lib 0.4.0rc20`.
- The MLflow tag `kaos_lib.version`, on a run whose step sets it.
- Each step image carries the label `io.kaos.lib` with the exact requirement it was built with.

To work on your computer with the package your steps use, [install](install.md) that version.

## Where you see the verdict

- **`kaosctl`** prints a `WARNING:` line with the fix, and refuses the commands that change data when the version
  is unsupported.
- **Pull requests and builds** of your app get a `kaos-lib/support` check. It is green when current, green with
  "warning:" when behind or deprecated, and red when unsupported. It never fails the render or the build itself.
