# Step types

Every step has a type. The type of a step is its `kind=` in `pipeline.py`. There are six types: `ingest`, `transform`,
`train`, `evaluate`, `publish` and `control`. The type is a contract. The platform checks it when it builds the pipeline,
and `kaosctl lint` checks it as you write. A step that breaks its type is refused with one sentence that names the step and
says what to add, or which type to use.

This page compares the six types and helps you pick one. Each type has a page with the same headings: what it is for, the
contract, where it runs, what the platform does, a complete example, and the mistakes with the exact messages.

## The six types side by side

| type | for | `inputs=` | must produce | may produce | must not | runs on | GPU | resumable | what the platform does for this type |
|---|---|---|---|---|---|---|---|---|---|
| [`ingest`](step-type-ingest.md) | bringing data in from outside | yes | a dataset | a model, an artifact | | the platform's own machines | `gpu=True` allowed | allowed | never offers an HPC (Slurm) class |
| [`transform`](step-type-transform.md) | turning data into other data | yes | something: a dataset, a model or an artifact | any of the three | | the platform's own machines or HPC (Slurm); a step that produces a dataset: the platform's own machines | `gpu=True` allowed | allowed | seals a version of each dataset it makes; offers HPC only when it makes no dataset |
| [`train`](step-type-train.md) | training a model | yes | a model | a dataset, an artifact | | the platform's own machines or HPC (Slurm); a step that produces a dataset: the platform's own machines | `gpu=True` allowed | allowed | keeps the model per run; `kaosctl lint` warns when a time limit has no way to continue (`L-W06`) |
| [`evaluate`](step-type-evaluate.md) | measuring a model or a dataset | yes | nothing | an artifact | a dataset, a model | the platform's own machines or HPC (Slurm) | `gpu=True` allowed | allowed | keeps reports per run; its values can decide later steps |
| [`publish`](step-type-publish.md) | delivering a result | yes | nothing | nothing | any `produces=` | the platform's own machines | `gpu=True` allowed | allowed | never offers an HPC (Slurm) class |
| [`control`](step-type-control.md) | steering the run | no | nothing | nothing | `inputs=`, any `produces=` | the platform's own machines | `gpu=True` allowed | allowed | never offers an HPC (Slurm) class; a failure stops the steps that need it |

Every type keeps to the rules that every step keeps to: a name and a folder, `step.start()` first and `step.result()`
last ([Your contract with the platform](contract.md#what-you-write)). Every type has a time limit that is chosen on the run form (`walltime=` only sets its default), can use `when=`, and can
end itself with `step.skip("reason")` ([Conditions and skipping](conditions-and-skipping.md)). A step that produces a
dataset runs on the platform's own machines, whatever its type ([Produce a dataset](produce-a-dataset.md#where-it-runs)).

What the type changes is small and the same everywhere: the check of what the step produces, the places it can run, and
the label the platform puts on the step. The step reads its own type with `step.start().kind`.

## A step that runs many times

Any step can run many times in one run, once for each combination of values. This changes nothing about its type or its
contract. The how-to is [Sweeps](sweeps.md); the field it adds to the run form is in
[the run form](contract.md#the-run-form).

## Which type is my step?

Answer in order. Stop at the first yes.

| the question | if yes |
|---|---|
| Does the step handle no data, only check the settings or decide something? | [`control`](step-type-control.md) |
| Does the step bring data in from outside the platform, and write it into a dataset? | [`ingest`](step-type-ingest.md) |
| Does the step make a model (weights you will keep)? | [`train`](step-type-train.md) |
| Does the step make a dataset, or turn data into other files? | [`transform`](step-type-transform.md) |
| Does the step only measure, and write reports? | [`evaluate`](step-type-evaluate.md) |
| Does the step deliver something out of the platform and make nothing to keep? | [`publish`](step-type-publish.md) |

When two answers fit, split the step. A step that makes a model and a dataset is a `train` that runs on the platform's own
machines; if the training should run on HPC (Slurm), make the model in one step and the dataset in a cheap second one
that reads it ([Produce a dataset](produce-a-dataset.md#where-it-runs)). A step that trains and then scores is two steps,
`train` and `evaluate`: the second can then be skipped, or run on a smaller machine.

Next: the page of your type. For the rules that are the same for every step, [Your contract with the
platform](contract.md).
