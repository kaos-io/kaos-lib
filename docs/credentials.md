# Credentials

One chain, and no secrets in the package.

1. `LAKEFS_ACCESS_KEY` + `LAKEFS_SECRET_KEY` (an app's key pair), endpoint `LAKEFS_ENDPOINT`
2. `LAKEFS_BEARER_TOKEN` (MeluXina jobs)
3. the browser login session of `kaosctl login` (a person's Zitadel token), cached in
   `~/.config/kubecore-ml/lakefs-session.json`

Another project's lakeFS gets its own chain (`credentials.resolve_peer`), without step 1; see
[Datasets shared with your project](shared-datasets.md).

The lakeFS URL comes from `--url`, `LAKEFS_ENDPOINT`/`LAKEFS_URL`, or `.kubecore/dataset-config.yaml`
(written into every app repo by the platform, which also carries the login settings).
