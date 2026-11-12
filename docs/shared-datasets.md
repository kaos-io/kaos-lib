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

- **Where**: kaos-lib finds the other projects through your own project, and reads the dataset from the owner's
  storage: the same code works in a pipeline step and on a laptop.
- **Who**: the owner never sees your project's access key. In a pipeline step kaos-lib uses a short-lived token of
  the step (this needs `kaos-lib[zitadel]`); on a laptop it uses your `kaosctl login` session. The owner grants
  read on exactly the datasets it shares with your project.
- **Cache**: `<cache>/<owner>/<repo>/<commit>` (your own: `<cache>/<repo>/<commit>`); the copy's marker records
  the owner, so your `dataset-x` and the owner's `dataset-x` never mix, even at the same commit id. A staged copy
  (a folder under `$KAOS_STAGED_ROOT`) is used only when its `.kaos-ready` record names the same repository and owner
  and says it holds the whole commit.
- **Read-only**: `release`, `push` and `create` of a `<owner>/...` name are refused before anything is sent.
- **Errors**: an owner that is not a project of your organisation, or a lakeFS too old to serve
  `/kaos/v1/peers`, is a one-line error. In `list --shared`, a peer that answers 401 shares nothing with you; a
  peer too old or unreachable is skipped with a `NOTE:` on stderr.

## Share a dataset (the owning project)

The admins of the project that owns the dataset do this. Everyone else sees the list but cannot change it.

1. Open the KAOS console → **Datasets** → the dataset.
2. Open the **Sharing** tab, choose **Share with project** → **Add a project…**, and **Save sharing**.

lakeFS shows on the dataset's page which projects it is shared with. Removing a project from the list stops its
reads within a couple of minutes. In the other project, the run form's `dataset` dropdown offers the dataset as
`<owner-project>/dataset-<name>@<version>` once that project's pipeline has been refreshed (any release of a dataset
in that project refreshes it).
