# publish

## What it is for

A `publish` step delivers a result: registers a model, calls a service, copies files out. It writes nothing the platform
keeps, so it produces nothing. It reads what the step before it made, and hands on what it delivered.

## The contract

| | |
|---|---|
| **Must** | nothing about what it produces |
| **May** | read earlier steps (`needs=`) and datasets (`inputs=`); hand on values, such as the name it delivered under; set `walltime=` (the default of the run form's time limit), `when=`, `gpu=True` |
| **Must not** | produce anything: no `produces=` |

## Where it runs

On the platform's own machines, always. The run form offers a `publish` step no HPC (Slurm) class.

## What the platform does

- Checks, when the pipeline is built, that the step has no `produces=`.
- Runs the step on the platform's own machines, and never makes an HPC (Slurm) variant of it.
- Gives later steps the values it hands on. The record of the delivery (an address, an id) goes in
  `step.result(delivered=...)`, not in a file.
- Runs it only when its `when=` is true. A `publish` step is often run only when the evaluation passed:
  `when="evaluate.passed == true"` ([Conditions and skipping](conditions-and-skipping.md)).

## A complete minimal example

```python title="pipeline.py"
--8<-- "examples/flows/publish/pipeline.py:6:8"
```

```python title="steps/register/app/entry.py"
--8<-- "examples/flows/publish/steps/register/app/entry.py"
```

```yaml title="config/registry.yaml"
--8<-- "examples/flows/publish/config/registry.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/publish/config/config.yaml"
```

```python title="steps/train/app/entry.py (the step before it)"
--8<-- "examples/flows/publish/steps/train/app/entry.py"
```

`step.input("model")` is the model `train` wrote. `step.result(delivered=name)` is the whole record of the delivery.

## Common mistakes

| the mistake | what you get |
|---|---|
| a `produces=` on a `publish` step | `kaosctl lint`: `L-E07`, `Step 'register': a publish step delivers a result and produces nothing here. Remove produces=, or give the step the kind of the work it does.` The platform's check says the same with a small `s` |
| an HPC (Slurm) class chosen on the run form | `step 'register' cannot run on class '...': a publish step never runs on HPC (Slurm). Choose one of: ...` The run is refused before it starts |
| writing the record of the delivery into a file | nothing is saved for it. Put it in the values of `step.result(...)` |
| a delivery that must not repeat on a retry | the platform runs a step again when its machine is lost: make the call safe to repeat |

## Related

[Step types](step-types.md) · [Conditions and skipping](conditions-and-skipping.md) · [Pass things on](pass-things-on.md) ·
[Your contract with the platform](contract.md)
