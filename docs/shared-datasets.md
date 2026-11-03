# Datasets shared with your project

Another project of your organisation can share its `dataset-*` repositories with yours (read-only; models are
not shared). Refer to one as `<owner-project>/dataset-<name>@<version>`; `dataset-<name>@<version>` keeps
meaning your own project, and `<your-project>/dataset-x@v1` is the same as `dataset-x@v1`.

```python
ref = datasets.DatasetRef.parse("team-a/dataset-cats@v3")   # ref.owner == "team-a"; also @latest, a branch or a commit
data_yaml = datasets.materialize(ref)                       # read from team-a's lakeFS, cached apart from your own
from kaos_lib import peers
for answer in peers.shared(client):                         # per peer: answer.datasets (DatasetInfo, owner set), answer.note
    ...
```

```
kaosctl dataset list --shared                # what other projects share with yours, with versions
kaosctl dataset versions team-a/dataset-cats # its versions, read from team-a's lakeFS
kaosctl dataset pull team-a/dataset-cats@v3  # read-only copy
```

- **Where**: your lakeFS lists the other projects (`GET /kaos/v1/peers`, read once per process).
  `LakeFS.for_owner(owner)` talks to the owner's in-cluster endpoint when your own lakeFS address is an
  in-cluster `.svc` one (pipeline steps), else to its public URL (laptops).
- **Who**: the owner sees a bearer token, never your project's `LAKEFS_ACCESS_KEY`/`LAKEFS_SECRET_KEY`
  (`credentials.resolve_peer`): `LAKEFS_BEARER_TOKEN`, else a short-lived Zitadel token minted from the step's
  machine key (`ZITADEL_MACHINE_KEY_FILE`, `ZITADEL_DOMAIN`, `ZITADEL_MLFLOW_PROJECT_ID`; needs
  `kaos-lib[zitadel]`), else your `kaosctl login` session. The owner grants read on exactly the datasets it
  shares with your project.
- **Cache**: `<cache>/<owner>/<repo>/<commit>` (your own: `<cache>/<repo>/<commit>`); the copy's marker records
  the owner, so your `dataset-x` and the owner's `dataset-x` never mix, even at the same commit id. A staged copy
  (`$KUBECORE_STAGED_DIR`) is used only when its `.kaos-ready` record names the same repository and owner.
- **Read-only**: `release`, `push` and `create` of a `<owner>/...` name are refused before anything is sent.
- **Errors**: an owner that is not a project of your organisation, or a lakeFS too old to serve
  `/kaos/v1/peers`, is a one-line error. In `list --shared`, a peer that answers 401 shares nothing with you; a
  peer too old or unreachable is skipped with a `NOTE:` on stderr.
