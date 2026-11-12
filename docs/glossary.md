# Glossary

| word | meaning |
|---|---|
| app | your pipeline project: `pipeline.py`, `config/` and `steps/`. Its name is the name of the repository |
| step | one program of the pipeline, in `steps/<name>/`, started as `python -m app.entry` |
| kind | what a step does: `ingest`, `transform`, `train`, `evaluate`, `publish` or `control`; each has a contract ([Step types](step-types.md)) |
| run | one start of the pipeline, with the values on the run form. It has a name, and so does each of its steps' logs |
| experiment | a name you choose for a series of runs (the setting `experiment.name`). The files of a run are kept under it |
| run form | the form you fill in to start a run. Every plain value in `config/` is a field on it |
| class | a size of machine, picked for a step on the run form: `<step>-class` |
| setting | a value in `config/`. A step gets the sections it names in `reads=` |
| input | a dataset a step reads, named in `inputs=`. The setting of that name holds the dataset reference |
| upstream | an earlier step a step names in `needs=`. `step.upstream("x")` is its result |
| result | the one thing a step hands on with `step.result(...)`: small values, and the list of what it read and wrote |
| artifact | files of one run that are not a dataset or a model: a report, plots, a table |
| model | files of one run that are a trained model |
| dataset | a named set of files in your project, `dataset-<name>` or `dataset-<app>-<name>` |
| version | a snapshot of all the files of a dataset. Its exact name is the version id |
| version id | the long hex string that names one version, 64 characters |
| `vN` | a label for a version of an uploaded dataset: `v1`, `v2`, ... |
| `latest` | the name that points to a dataset's current version. For a produced dataset it moves only when a run asks, and only at the end of a run whose steps all went well |
| promote | ask a run to move `latest` to the version it made. All the datasets a run is asked to promote move together, or none does |
| ledger | the list of what a step read and wrote, with exact version ids |
| checkpoint | the state a long step saves so that it can continue after an interruption |

See [The data contract](data-contract.md) and [Your contract with the platform](contract.md).

Next: [Data flow scenarios](data-flow.md) shows how to do each thing in code.
