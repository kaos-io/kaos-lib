# Data flow scenarios

Each page below answers "how do I make data go from here to there?". Every scenario has the same four parts: when you
want it, the lines of `pipeline.py`, the step code, and what the run records. All the code is real: it is run when this
guide is built.

| you want to | scenario |
|---|---|
| read a dataset at a version you pick on the form | [Read a version chosen on the form](flow-datasets.md#read-a-version-chosen-on-the-form) |
| read two datasets, or two versions of one, in one step | [A step with two inputs](flow-datasets.md#a-step-with-two-inputs) |
| make a dataset and read exactly that version in a later step | [Make a dataset and read it in the same run](flow-datasets.md#make-a-dataset-and-read-it-in-the-same-run) |
| read a dataset that another pipeline makes | [A second pipeline reads the dataset](flow-datasets.md#a-second-pipeline-reads-the-dataset) |
| move `latest` to the version a run made | [Move `latest`](flow-datasets.md#move-latest) |
| hand numbers or text to the next step | [Values to the next step](flow-between-steps.md#values-to-the-next-step) |
| hand files to the next step | [Files to the next step](flow-between-steps.md#files-to-the-next-step) |
| skip a step by a choice on the form, and keep the steps after it working | [A step that may be skipped](flow-between-steps.md#a-step-that-may-be-skipped) |
| gather the work of several steps in one | [One step needs several steps](flow-between-steps.md#one-step-needs-several-steps) |
| train, write a model and continue after an interruption | [Train, checkpoint and resume](flow-training.md) |
| bring data in from outside | [Bring data in](bring-data-in.md) |
| read a dataset that another project shares | [Share a dataset](share-a-dataset.md) |
| log metrics and find the files and models of a run | [See your results](see-your-results.md) |

For the ideas behind them, read [Principles](principles.md) and
[Datasets, versions and hashes](datasets-versions-hashes.md).
