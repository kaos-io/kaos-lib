# Principles

This page moved. The ten rules it listed are now stated where they apply:

| the rule | where |
|---|---|
| A step is a folder with one entry point | [What you write](contract.md#what-you-write) |
| A step declares what it reads and makes, and gets exactly that | [What a step receives and must return](contract.md#what-a-step-receives-and-must-return) |
| Settings live in `config/` and appear on the run form by themselves | [The run form](contract.md#the-run-form) |
| The version of a dataset is chosen on the run form, never in code | [What a run reads](data-reads.md) |
| When a run starts, every dataset choice becomes one exact version | [Fixed when the run starts](data-reads.md#fixed-when-the-run-starts) |
| A step ends by handing over one result | [What a step receives and must return](contract.md#what-a-step-receives-and-must-return) |
| Nothing is saved before every output has passed its checks | [What is saved, and when](data-writes.md#what-is-saved-and-when) |
| A version never changes after it is made | [What a version is](data-contract.md#what-a-version-is) |
| Only the app that declares a dataset writes it | [What a step writes](data-writes.md#what-a-step-writes) |
| A run records what it read and wrote | [What a run records](data-reads.md#what-a-run-records) |
