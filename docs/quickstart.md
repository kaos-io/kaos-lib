# Quickstart

From nothing to a dataset version that a pipeline step reads. Run the commands inside your app folder: its
`.kubecore/dataset-config.yaml` tells `kaosctl` where your project's lakeFS is.

## 1. Sign in

```bash
kaosctl login
```

Your browser opens once and asks you to sign in. The session is cached, and every later command uses it.

## 2. Create a dataset

```bash
kaosctl dataset create cats --layout yolo --classes cat,kitten
```

This makes the lakeFS repository `dataset-cats` with the starter files of the `yolo` layout: `data.yaml`,
`images/` and `labels/`, split into `train`, `val` and `test`. It prints the link to it.

!!! note "Not a YOLO dataset?"
    With no `--layout` (or `--layout none`), `kaosctl dataset create cats` makes an empty `dataset-cats` that
    accepts any files. Pick a layout with `kaosctl layout list`, or [make your own](make-your-own-layout.md).

## 3. Put your files in

```bash
kaosctl dataset pull dataset-cats@latest ./dataset-cats      # download main
# copy images into ./dataset-cats/images/train and images/val,
# and one label file per image into ./dataset-cats/labels/train and labels/val
kaosctl dataset validate ./dataset-cats                      # lists every problem it finds
kaosctl dataset push ./dataset-cats dataset-cats -m "first 200 images"
```

`push` validates with the dataset's layout, uploads to a draft branch and opens a **pull request**. Nothing reaches
`main` until someone merges it in the lakeFS UI.

## 4. Release a version

After the pull request is merged:

```bash
kaosctl dataset release dataset-cats      # tags main as the next version: prints v1
kaosctl dataset versions dataset-cats
```

A pipeline run picks a version (`dataset-cats@v1`), so a result always points back to the data it used. The
pipeline's run form lists every released version in its `dataset` dropdown.

## 5. Read it in a pipeline step

```python
from kaos_lib import datasets

ref = datasets.DatasetRef.parse("dataset-cats@v1")
data = datasets.materialize(ref)          # yolo: the path of data.yaml; raw: the folder
print("training on", datasets.resolve(ref), data)
```

`materialize` downloads that commit once and caches it. In a pipeline the platform injects the credentials, so the
same code runs unchanged in a step, on a laptop (after `kaosctl login`) and on MeluXina.

## 6. Save results

```python
from kaos_lib import outputs

with outputs.run("myapp", "exp1", "run-7") as r:   # in a step: app = $CHECKPOINT_BUCKET, run = $KUBECORE_RUN_ID
    r.save("./ckpt")                               # durable on the run's own branch, reused on a retry
    r.finish({"dataset_ref": "dataset-cats@v1"})   # one merge commit on main of outputs-myapp
```

Next: [Datasets](datasets.md) for versions, layouts and rights, [Outputs](outputs.md) for resuming a run, and the
[CLI reference](generated/cli.md) for every option.
