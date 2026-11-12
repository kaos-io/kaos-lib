# Principles

Ten rules. Everything else in the guide follows from them. Each rule has a small example. The pages
[What you must and what you can](must-and-can.md) and [Datasets, versions and hashes](datasets-versions-hashes.md)
build on this page.

## 1. A step is a folder with one entry point

A step lives in `steps/<name>/`. The platform starts it as `python -m app.entry`, with no arguments. Your code reads
no environment variable: everything the step needs comes from one call, `step.start()`.

```python title="steps/prepare/app/entry.py"
--8<-- "examples/first-pipeline/template/steps/prepare/app/entry.py:6:7"
```

## 2. A step declares what it reads and what it makes, and gets exactly that

`pipeline.py` lists the settings (`reads=`), the datasets (`inputs=`), the earlier steps (`needs=`) and the things the
step makes (`produces=`). The step can open those and nothing else. Asking for anything else fails with a message that
names what is declared.

```python title="pipeline.py"
--8<-- "examples/first-pipeline/template/pipeline.py:19:20"
```

## 3. Settings live in `config/` and appear on the run form by themselves

Every plain value under `config/` is a field on the run form, with the value in the file as its default. You never
write form code. [Settings](settings.md) shows it.

## 4. The version of a dataset is chosen on the run form, never in code

A step names an input (`step.input("dataset")`). It never names a version. Whoever starts the run picks the version.
`kaosctl lint` warns when step code writes a version (`L-W03`).

## 5. When a run starts, every dataset choice becomes one exact version

Before the first step starts, each dataset choice on the form is turned into one exact version, and every step of the
run reads that version. A colleague who adds files while your run is going changes nothing for it.
[Datasets, versions and hashes](datasets-versions-hashes.md#fixed-when-the-run-starts) has the details.

## 6. A step ends by handing over one result

The last call of a step is `step.result(...)`. It saves the step's outputs and hands small values to the steps that
need this one. A step that ends without it fails, so the next step never starts with nothing.

## 7. Nothing is saved before every output has passed its checks {#what-is-saved}

`step.result()` first checks every output: it was written, it is not empty, a dataset output holds no file under
`.kaos/`, and it passes its `step.check`. If one fails, it saves nothing. A step that fails before it calls
`step.result()` (an exception, `SystemExit`, a crash) saves nothing either: until then the output folders are only
files on the step's machine, and the step hands on no result.

Once the checks pass, `step.result()` saves in two stages, and a failure in a stage can leave something behind:

1. **Seal.** Every output is uploaded and checked, and no model, artifact or `latest` changes. A failure here changes
   nothing that anyone reads, except that a dataset version already sealed for an earlier output of the same step
   stays in its dataset, kept under a name that starts `k-<run>-<step>`. It is not `latest`.
2. **Promote.** Models and artifacts are saved first, then the datasets that the run asked to move `latest` for. When a
   promotion fails, a model or artifact that was already saved stays under its folder `<name>/<experiment>/<run>/`;
   no result refers to it. A dataset whose promotion failed keeps its sealed version, and `latest` does not move. If a
   step moves two datasets, the second can fail after the first has moved: that one case cannot be undone.

In every case the step fails and hands on no result, so the steps that need it do not start.
[When a step is run again](datasets-versions-hashes.md#when-a-step-is-run-again) says what a retry does with it.

## 8. A version never changes after it is made

Making a version never edits an older one. What moves is the name `latest`, and only when the run asks for it.

## 9. Only the app that declares a dataset writes it

`dataset("clean")` in `produces=` makes the app the one writer of the dataset `dataset-<app>-clean`. People and other
pipelines read it. A step that tries to write anything it did not declare is refused.

## 10. A run records what it read and wrote

Every step's result lists the exact version of each dataset it read and of everything it wrote. That list is how you
answer "which data made this model?". See [Datasets, versions and hashes](datasets-versions-hashes.md#which-data-made-this-model).

Next: [What you must and what you can](must-and-can.md).
