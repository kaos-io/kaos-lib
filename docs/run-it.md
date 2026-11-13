# 1. Run it

You have a project on the platform. In ten minutes you create a pipeline from the hera template, run it as it is,
and read its result. Nothing here needs code.

Three words, used on every page:

- an **app** is your pipeline project: its code repository, with `pipeline.py`, `config/` and `steps/`. Its name is the
  name you give the pipeline.
- a **run** is one start of the app, with the values you put on the run form.
- an **experiment** is a name you choose on the run form for a series of runs. The files of a run are kept under it.

The [glossary](glossary.md) has the rest.

## Install kaosctl

`kaosctl` is the command line of kaos-lib. You use it here to put a few files in a dataset.

--8<-- "generated/install.md"

## Create the pipeline

In the console, create a new pipeline. The form asks for a name, a template, your project and where the pipeline
runs. Pick the template Hera and create the pipeline. The platform makes a code repository for it and
starts it from the template. Clone that repository and work inside the folder: `kaosctl` reads your project's
address from it. The folder holds `pipeline.py`, a `config/` folder and one folder for each step
under `steps/`. Sign in once, inside the folder:

```bash
kaosctl login
```

`kaosctl login` opens your browser and signs you in.

`pipeline.py` lists the steps:

```python title="pipeline.py" hl_lines="19-21"
--8<-- "examples/first-pipeline/template/pipeline.py"
```

`prepare` keeps the files of a dataset that are not empty and writes them as a new dataset, `clean`. Its code is
`steps/prepare/app/entry.py`:

```python title="steps/prepare/app/entry.py"
--8<-- "examples/first-pipeline/template/steps/prepare/app/entry.py"
```

`hello-world` reads `clean` and writes a short report. The next pages change one line at a time.

What you are looking at in `pipeline.py`, one line for each keyword of `step(...)`:

- `kind=` says what the step does, one of six kinds, each with its own contract ([Step types](step-types.md)).
- `reads=` names the sections of `config/` the step gets as settings ([page 3](settings.md)).
- `inputs=` names the datasets the step reads ([page 4](read-data.md)).
- `needs=` names the steps that run before this one and whose results it can read ([page 5](pass-things-on.md)).
- `produces=` names what the step makes: a dataset, a model or an artifact ([page 5](pass-things-on.md), [page 6](produce-a-dataset.md)).

## Put a few files in a dataset

The run reads a dataset. Your project has one named `dataset-default`, and it holds no files yet. The third file
below is empty on purpose: `prepare` drops it.

```bash
mkdir toy && printf 'one\n' > toy/a.txt && printf 'two two\n' > toy/b.txt && : > toy/empty.txt
kaosctl dataset push ./toy dataset-default -m "first files"
```

`push` prints a link to a pull request in the data store, the place that keeps your project's datasets. Open the link in
your browser and merge the pull request there: you merge it yourself, with the merge button on that page. A dataset
changes only through a merged pull request.

## Run the pipeline

On your pipeline's row in the console, press the run button. A form opens with one field for each setting of the
pipeline, all with defaults. The field `dataset` offers your project's datasets and their versions; leave
`dataset-default` and submit.

To open the runs of a pipeline, use the first entry of the "⋯" menu on its row.

## Read the result

Open each step of the run and read its log:

```text
[prepare] kept 2 of 3 files
[hello-world] my-experiment-v1: 2 files in clean, 1 dropped by prepare
```

Each step also hands a result to the next one. `hello-world` wrote a file, `hello.txt`, as the artifact `report`.
Download it with the run's name from the run page:

```bash
kaosctl dataset pull outputs-<app>@main ./results --prefix report/my-experiment-v1/<run>/
```

The files of every artifact and model of an app are kept in one place, named `outputs-<app>` after your app. `@main` is
the newest state of that place, and `--prefix` takes only the folder of this artifact, `report`, under the experiment
`my-experiment-v1` and the run. You ran the template unchanged and read what it did.

Next: [Your first step](first-step.md) changes `hello-world`.
