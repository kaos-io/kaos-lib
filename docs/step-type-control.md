# control

## What it is for

A `control` step steers the run and handles no data: it checks the settings, or decides something the next steps depend
on. It has no `inputs=` and no `produces=`.

## The contract

| | |
|---|---|
| **Must** | nothing about what it produces |
| **May** | read settings (`reads=`) and earlier steps (`needs=`); hand on values; set `walltime=` (the default of the run form's time limit), `when=`, `gpu=True` |
| **Must not** | take `inputs=`, or produce anything |

## Where it runs

On the platform's own machines, always. The run form offers a `control` step no HPC (Slurm) class.

## What the platform does

- Checks, when the pipeline is built, that the step has neither `inputs=` nor `produces=`.
- Runs the step on the platform's own machines, and never makes an HPC (Slurm) variant of it.
- When the step fails, the steps that name it in `needs=` do not start. Put `needs=[check]` on the steps that must not
  run when the check fails.
- Gives the steps that need it the values it hands on, with `step.upstream("check").values`.

## A complete minimal example

```python title="pipeline.py"
--8<-- "examples/flows/control/pipeline.py:6:8"
```

```python title="steps/check/app/entry.py"
--8<-- "examples/flows/control/steps/check/app/entry.py"
```

```python title="steps/work/app/entry.py (the step after it)"
--8<-- "examples/flows/control/steps/work/app/entry.py"
```

```yaml title="config/check.yaml"
--8<-- "examples/flows/control/config/check.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/control/config/config.yaml"
```

The step after it, `work`, has `needs=[check]` and reads the values with `step.upstream("check")`. A step that needs a
conditional step waits for it either way ([Between steps](flow-between-steps.md)).

## Common mistakes

| the mistake | what you get |
|---|---|
| `inputs=` or `produces=` on a `control` step | `kaosctl lint`: `L-E07`, `Step 'check' is a control step: it steers the run and handles no data, so it takes no inputs= and no produces=.` The platform's check says: `step 'check': a control step steers the run and handles no data, so it takes no inputs= and no produces=. Give the step the kind of the work it does (ingest, transform, train, evaluate, publish).` |
| the steps after it do not name it in `needs=` | they start without waiting for it, and a failed check does not stop them |
| an HPC (Slurm) class chosen on the run form | `step 'check' cannot run on class '...': a control step never runs on HPC (Slurm). Choose one of: ...` The run is refused before it starts |
| a value that does not fit in the result | `the result costs N; the limit is 8192.` Hand on a few small values |

## Related

[Step types](step-types.md) · [Conditions and skipping](conditions-and-skipping.md) ·
[Between steps](flow-between-steps.md) · [Your contract with the platform](contract.md)
