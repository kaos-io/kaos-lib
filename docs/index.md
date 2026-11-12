# kaos-lib

kaos-lib is the Python library of the platform (`import kaos_lib`), and `kaosctl` is its command. You write ML
pipelines with it: each step is a small Python program that reads data, does work and hands a result on.

--8<-- "generated/built.md"

## The contract

The three pages to read first, and to come back to. They say what you write, what each step type must and may do, and what
the platform does with your data.

<div class="grid cards" markdown>

-   **[Your contract with the platform](contract.md)**

    What you write, what the platform does on every run, what a step receives and must return, the run form, what is
    refused, what is guaranteed and what is not promised.

-   **[Step types](step-types.md)**

    `ingest`, `transform`, `train`, `evaluate`, `publish`, `control`: one table that compares them, which one is
    your step, and a page with the contract of each.

-   **[The data contract](data-contract.md)**

    Datasets and versions, what a run reads, what it writes, when `latest` moves, and what is kept and for how long.

</div>

## The rest of the guide

| part | you want to | pages |
|---|---|---|
| **Start here** | learn, from a first run to a real pipeline, one idea a page | [1. Run it](run-it.md) to [11. A real pipeline](a-real-pipeline.md) |
| **The contract** | look up a rule | [Your contract with the platform](contract.md), [Step types](step-types.md), [The data contract](data-contract.md) |
| **How to** | do one thing, with code that runs | [Data flow scenarios](data-flow.md), [Test your steps](test-your-steps.md), [See your results](see-your-results.md), [Add packages](add-packages.md), [Bring data in](bring-data-in.md), [Share a dataset](share-a-dataset.md), [Make a dataset layout](make-a-layout.md), [When something goes wrong](when-something-goes-wrong.md) |
| **Reference** | look something up | [Cheat sheet](cheat-sheet.md), [Reference](reference.md), [Commands](generated/cli.md), [Python API](api.md), [Lint checks](lint.md), [Glossary](glossary.md) |

New here? Start at [Run it](run-it.md) and stop wherever you have what you need. The app is the one the hera template
creates. Page 11 ends with a pointer to [Your contract with the platform](contract.md), which states every rule.

The code on every page is a file that is run and checked when this guide is built.
