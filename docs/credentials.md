# Credentials

One chain, and no secrets in the package.

1. `LAKEFS_ACCESS_KEY` + `LAKEFS_SECRET_KEY` (an app's key pair), endpoint `LAKEFS_ENDPOINT`
2. `LAKEFS_BEARER_TOKEN` (Slurm jobs)
3. the browser login session of `kaosctl login` (your own sign-in token), cached in
   `~/.config/kaos-ml/lakefs-session.json` (older installs keep using `~/.config/kubecore-ml`)

Another project's lakeFS gets its own chain (`credentials.resolve_peer`), without step 1; see
[Datasets shared with your project](shared-datasets.md).

The lakeFS URL comes from `--url`, `LAKEFS_ENDPOINT`/`LAKEFS_URL`, or `.kaos/dataset-config.yaml`
(present in every app repository, with the sign-in settings).
