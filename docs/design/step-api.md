# Design: `kaos_lib.step` (kaos-lib 0.5, PRD kaos#1911 F-02, F-11, F-12)

Status: implemented on branch `prd1911/step-api` (package W1). This page is not part of the published site
(`exclude_docs` in `mkdocs.yml`). The client pages are `docs/step.md` and `docs/results.md`. No app is moved to
this contract: every app is created again from the template, so kaos-lib has no migration guide and no
`lint --fix`.

The sections below are the design as it was reviewed. Where the implementation differs, this list wins:

| Topic | As built |
|---|---|
| Contract | `docs/step-contract.md` of kaos-hpc-operator (branch `prd1911/engine-contract` at `00f134f`); fixtures copied to `tests/contract_fixtures/` by `sync.py`, pinned by `SHA256SUMS` |
| Caps | Counted by cost (`lock.cost`: every quote and backslash counts twice). Context 96 KiB in `start()`; result 8 KiB in `result()` |
| Wire form | Also writes `&`, `<` and `>` inside strings as unicode escapes |
| Absent | `upstream(step, optional=True)` and `input(name, optional=True)` return `None`; without it both raise, naming the step. `start()` failures are one line on stderr and exit 1 |
| Reads | Every declared input is in the result's `reads`, opened or not, then every upstream dataset that was read |
| Saving outputs | `writer.py`, one code path for models, artifacts and datasets. `result()` works in phases: (a) validate everything local (values, cost with placeholder commits, every output written, `.kaos/` unused, checks); (b) **seal** every output without touching any `main`: start `run-<run>-<step>-<name>` from the head of `main`, mirror the folder below the output's path (a model or artifact below `<name>/<experiment>/<run>/`), check the branch, commit, check the commit, tag a dataset's commit `k-<run>-<step>-<12 characters of the commit>`; (c) only when all are sealed, **promote**: merge the sealed commit (not the branch name) into `main`, models and artifacts first, then the datasets whose `promote` is true, on `expected_head`, restaging on 412 up to three times; (d) write the result file atomically. A failure in (a) or (b) moves no `main` and deletes the run branches |
| Reusing a seal | Before staging, a dataset's earlier attempts are looked up by tag; a tag is a candidate only when it is exactly `k-<run>-<step>-<12 hex characters>`, those characters start the commit it points at, and that commit's metadata `kaos.run` and `kaos.step` are this run and this step (names have hyphens, so the tag alone does not say whose it is); one whose commit holds exactly the folder and whose parent is the head `main` has now is reused: no new commit, no new tag. A commit staged on an older head is never reused, because promoting it would mix in what the other run changed |
| What cannot be closed | Promoting two datasets is two merges in two repositories. The second can fail after the first moved `latest`. Models and artifacts are promoted first and datasets last to keep that case as narrow as it can be; a retry finds the first already done. Models and artifacts are merged into `main` of the outputs repository first, then the datasets, so when a later promotion fails, a model or artifact that is already merged stays on `main` under its run-unique path `<name>/<experiment>/<run>/` while the step fails; nothing refers to it, because the step publishes no result; a retry of the step replaces that folder with exactly what the retry wrote. Two live attempts of one step writing the same model or artifact are not guarded (no `expected_head` there); for a dataset the expected head guards them |
| `promote` | A boolean on a `dataset` entry of `produces`, set by the platform; absent means false |
| `input(name)` | An `inputs=` name resolves from `ledger.reads`; a dataset, model or artifact of a needed step from `upstream.<step>.writes`. Only dataset reads are recorded |
| Staged inputs | One folder per input under `$KAOS_STAGED_ROOT`, named after the input; its record is the sibling file `<name>.kaos-ready`, never a file in the folder (a step sees only the engineer's files). The record is a JSON object with this `repo`, this `commit`, this `owner` (absent or null for the own project) and `"full": true`; an optional `"layout"` lets the step read the copy without asking lakeFS. The cache of downloaded copies works the same way (`<folder>.kubecore-dataset.json` beside the folder). A marker kaos-lib writes (the cache, a folder given to `materialize`, a local run's `.kaos-ready`) also carries the folder's inode and device, its file count and its size in bytes, and counts only for the folder that has them now: a folder deleted and re-created is a folder without a marker, non-empty means refused as "not a kaos-lib copy". The platform's `.kaos-ready` has none of these fields; then the rule above alone applies. The one function is `layouts.local.staged_dir` |
| Outputs on disk | `/work/kaos/outputs/<name>/`, emptied the first time `output(name)` is asked for in an attempt |
| A declared output | Must be written: `result()` refuses a `produces=` entry whose folder was never asked for or is empty |
| Ending without a result | An exit hook (`sys.exit` and `sys.excepthook` wrapped, an `atexit` check). The code of the last `sys.exit(n)` of the main thread is kept and a step cannot tell whether that exit was the one that ended it (a caught `sys.exit(2)` followed by a normal end exits 2); a normal end, exit code 0, an exit in another thread and a bare `raise SystemExit(n)` (not seen: Python offers no way to read the pending exit status at exit) end with 1; an uncaught exception is Python's own exit 1. The code is kept to 8 bits as the process keeps it (`sys.exit(256)` is 0 to the operating system, so it ends with 1); a string or `None` is 1. The handler forces the exit with `os._exit`, so it first takes off the handlers registered after `start()` (they have run already) and runs the rest, those registered before `start()`. Out of reach: `os._exit`. The platform closes that gap: the step's result output has no default, so a pod that succeeds without the file fails the step |
| The ledger on MLflow | `ledger/<step>.json`, written when the step's MLflow run ends and again by `result()` once the writes are known |
| Local runs | `kaosctl step run` sets `KAOS_STEP_CONTEXT`, `KAOS_STAGED_ROOT` and `KAOS_LOCAL_WORK`; with `KAOS_LOCAL_WORK` set, `result()` keeps outputs under `$KAOS_STAGED_ROOT` and uploads nothing. The stand-in commit is `transfer.fingerprint`. `kaos_lib.testing.running` builds the same world in a test |
| Names | A produced dataset's repository comes from the context's `produces` entry. `datasets.produced_repo(app, name)` (`dataset-<app>-<name>`) is the one place that spells the rule, for local runs |
| Lint | `L-E07` (declaration, and what the engine refuses: control steps with data, reserved step names, more than sixteen readable datasets, a second writer of a dataset, an input that is not a text value in `config/`, more than ten `needs`), `L-E08` (step not moved), `L-E09` (the `platform` config group), `L-E06` (positional arguments after the name, a repeated keyword), `lint --fix`; rule set 2.0.0. `L-W03` now warns about a dataset version written in step code, not about the default in config. Lint reads only the repository's own files: never a virtualenv, `.kaos/`, a cache or what the folder's `.gitignore` names |
| Support policy | `support.check` is unchanged. A step on an unsupported line is told, when the newest release is `breaking`, that the app's code has to change, with the guide's address |
| Release policy | Unchanged on this branch; the move to 0.5 is one commit on `prd1911/release-policy-0.5` |

## 1. What the engineer writes

A step is `python -m app.entry` with no arguments. Everything the platform tells it arrives in one value,
`KAOS_STEP_CONTEXT`. Everything it hands on leaves through one call, `step.result()`.

```python
from kaos_lib import step

ctx   = step.start()               # read and check the context; nothing else in the step works before this
data  = step.input("raw")          # a folder: the dataset version picked on the submit form, at its exact commit
out   = step.output("embeddings")  # a folder to write into; saved when result() is called
prev  = step.upstream("prepare")   # the result of an earlier step: prev.values, prev.reads, prev.writes
step.check("embeddings", layout="raw", min_files=1)   # a condition the output must meet before it is sealed
step.result(rows=1200)             # save the outputs, write the result; the last call of the step
```

| Call | Returns | Notes |
|---|---|---|
| `start()` | `Step`: `run`, `app`, `project`, `step`, `kind`, `experiment`, `params` (the composed config, a dict) | Call once, first. A second call returns the same object |
| `input(name)` | `pathlib.Path`, always a folder | `name` is a name declared in `inputs=`, or the name of something an upstream step produced |
| `output(name)` | `pathlib.Path`, an empty local folder (for a dataset: see 6) | `name` is declared in `produces=` |
| `upstream(step, required=True)` | `Upstream(values, reads, writes)`; `None` when `required=False` and the step did not run | |
| `check(name, layout=None, min_files=1)` | nothing | Registers a check on an output; runs inside `result()`, before the seal |
| `result(**values)` | nothing | Saves every output, writes the result file, once |

The engineer never names a dataset version in code. `inputs=["raw"]` in `pipeline.py` says that the config value
`raw` holds a dataset reference; the form (or the config default) supplies `raw-images@latest`, a name or a
commit; the platform resolves it once when the run starts and puts the exact commit in the context. `input("raw")`
takes a name and nothing else: there is no `version=`, no `ref=`, no `commit=` argument.

## 2. The hera example step (13 lines; AC-06 allows 25)

```python
"""hello-world: count the files of the run's dataset and hand the count on."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    data = step.input("dataset")
    files = sum(1 for p in data.rglob("*") if p.is_file())
    report = step.output("report")
    (report / "hello.txt").write_text(f"{files} files, experiment {ctx.experiment}\n")
    step.result(files=files)


if __name__ == "__main__":
    main()
```

with, in `pipeline.py`: `step("hello-world", kind="transform", reads=["experiment"], inputs=["dataset"],
produces=[artifact("report")])`. No `argparse`, no `yaml`, no `os.environ`, no repository or run-path names.
Today's `steps/hello_world/app/entry.py` in the hera template is 107 lines for the same work.

## 3. The context

`start()` reads `os.environ["KAOS_STEP_CONTEXT"]`, the same on a pod and in a Slurm job.

Validation, in this order, each failing with the message in section 8:

1. The variable is set and not empty.
2. It is at most 96 KiB (98,304 bytes of UTF-8). The platform enforces the same cap when it builds the value;
   this check catches a hop that grew or cut it.
3. It is JSON and a JSON object.
4. `version` is `1`.
5. `run`, `app`, `project`, `step`, `experiment` are non-empty strings; `kind` is one of `ingest`, `transform`,
   `train`, `evaluate`, `publish`, `control`; `params` is an object.
6. `ledger` is a ledger at version 2 (section 4).
7. `produces` is a list of `{name, type, repo}` with `type` one of `model`, `artifact`, `dataset`; names are
   unique and none starts with `kaos-`.
8. `upstream` is an object; each value is a result (section 5): `version` 1 and `status` `ok` or `absent`.

Unknown keys are ignored at every level, so a later feature can add a field without breaking a step image built
today (CON-01). An unknown `version` is refused: that is the one signal that the shape changed.

**Built on `runtime.py`.** `runtime.Context` keeps what it is, "where this step runs", and changes its source:
`run_id`, `app`, `project`, `step` come from the step context; `kind` and `experiment` are added;
`lakefs_endpoint`, `mlflow_uri`, `support` and `slot` are still read from the environment, because the contract
does not put them in the context. `dataset_ref`, `dataset_commit` and their six variables are deleted (section 9).
`runtime.context()` outside a step (a laptop, `kaosctl`) still returns `None` fields and never raises;
`step.start()` is the call that raises.

The contract has one name for the run, `run`. `workflow` (today `KUBECORE_WORKFLOW_NAME`, used to name the MLflow
run) is deleted and `run` takes its place.

## 4. Ledger version 2 (`lock.py`)

One carrier for data references (D-08). The same shape appears in three places: `context.ledger` (what the
platform pinned for this step), each result's `reads` and `writes` (what the step actually opened and sealed),
and the run's ledger (the union of the results, built by the platform; kaos-lib never rewrites a shared file).

```json
{"version": 2,
 "reads":  [{"name": "raw", "repo": "dataset-raw-images", "owner": null, "ref": "latest", "commit": "1111…"}],
 "writes": [{"name": "embeddings", "type": "dataset", "repo": "dataset-embeddings", "commit": "3333…"}]}
```

- `Read` gains `name` (required) and `line` (optional). `Write` is new: `name`, `type`, `repo`, `commit`,
  optional `line`.
- `line` is reserved for derived datasets stored as a branch of their source (F-15, reference form
  `<dataset>.<variant>@<ref>`). 0.5 parses it, keeps it when it copies an entry, and never sets it.
- `DataLock.parse` accepts version 2, and version 1 **read-only** for `kaosctl run --lock` on a run made before
  the wave: a v1 read has no name and gets the repository's name without its `dataset-` prefix. `to_dict` and
  `to_json` write version 2 only. There is no version-1 writer left.
- `pinned(repo, ref, owner)` is unchanged; `pinned_by_name(name)` is added and is what `input()` uses.
- `start()` loads `context.ledger` plus every upstream result's `writes` as the replayed lock. So any
  `datasets.resolve` or `datasets.materialize` that step code or a framework hook still calls returns the pinned
  commit, with no lakeFS call, exactly as `$KAOS_LIB_LOCK` did. `$KAOS_LIB_LOCK` itself stays only as the
  hand-over of `kaosctl run --lock` to its child process.

**Choice:** inside a step (after `start()`), `datasets.resolve` of a repository that the ledger does not cover is
refused instead of resolved live. Resolving live inside a step is the engineer choosing a version in code, and it
is the silent path by which two steps of one run read different commits (CON-04, D-06).

**Choice (the MLflow copy; see OQ-09 below):** `DataLock.write`, which downloads `data.lock.json` from the MLflow
run, merges and uploads it again, is deleted: it is the rewritten shared file D-08 removes. In its place, when
the step has an MLflow run, `result()` logs the step's own reads and writes once as `ledger/<step>.json` and
sets the tags `kaos_lib.data.<repo>.commit` as today. `lock.load(run_id)` returns the union of `ledger/*.json`,
or the old `data.lock.json` when the run has only that. `kaosctl run --lock <mlflow run>` keeps working for old
and new runs.

## 5. The result

`result(**values)` writes one file, `/work/output/kaos-result.json`, atomically (a temporary file in the same
folder, then a rename), once. The file is in the contract's wire form: no whitespace, ASCII only, and `{`, `}` and `$` inside
strings written as `\u007b`, `\u007d` and `\u0024` (Kubernetes expands `$(NAME)` in an environment value). `lock.py` gets the one writer, `wire(obj) -> str`, tested
byte for byte against every `.wire` fixture. Shown here indented for reading:

```json
{"version": 1, "status": "ok", "values": {"rows": 1200},
 "reads":  [ …the inputs this step opened with input(), as ledger reads… ],
 "writes": [ …the outputs this step sealed, as ledger writes… ]}
```

- `values` are the keyword arguments. They must be JSON values (text, numbers, booleans, null, lists, objects);
  anything else is refused before any output is saved.
- The file is at most 32 KiB (32,768 bytes of the wire form). Larger is refused, naming the size and the largest
  value. A large hand-over is an artifact, not a value.
- The path is the same on a pod and in a Slurm job. kaos-lib writes nowhere else.
- **The "absent" sentinel.** kaos-lib never writes it. When a step wrote no result (it was skipped by `when=`,
  or it ended without calling `result()`), the platform hands its consumers `{"version": 1, "status": "absent"}`
  in `context.upstream[<step>]`. It is never `{}`. `upstream("x")` on an absent result raises, naming `x`
  (AC-03); `upstream("x", required=False)` returns `None`, for a consumer that can work without it.
- `reads` lists only what was opened. An input that is declared but never opened is not in the result; the
  run's ledger then shows that the step did not use it.

**Choice:** a process that called `start()` and exits with code 0 without `result()` is made to exit with code 1
and the message of section 8. The contract lets such a step end well and gives its consumers the sentinel;
failing the producer too puts the red mark on the step that has the bug, and is the stricter of the two. A step
with nothing to hand on calls `step.result()`.

**Order inside `result()`:** check the values; save each output in declaration order (models and artifacts with
`outputs.RunWriter`, datasets with the writer of section 7); write the ledger to MLflow when there is a run;
write the result file last. If anything fails, no result file exists, so no consumer can read a half result.
A retry repeats the saves, which are idempotent (`RunWriter` reuses its run branch; the dataset writer mirrors).

## 6. Inputs and outputs on disk

### `input(name)`

1. Find the read: a `context.ledger.reads` entry with this `name`; else a `writes` entry with this `name` in an
   upstream result. Neither: the message of section 8.
2. A dataset: `datasets.materialize(DatasetRef(owner, repo, ref, commit=commit))`, which already does the rest:
   a staged copy when one holds this commit, else the cache `<cache>/<repo>/<commit>`, else download once. The
   layout comes from the repository's label as today. The return value is the folder (for a layout whose entry
   point is a file, such as `data.yaml`, its folder).
3. A model or an artifact an upstream step produced: download `outputs-<app>` at the written commit, prefix
   `<name>/<experiment>/<run>/`, into `<cache>/outputs-<app>/<commit>/<name>/` (`transfer.download_prefixes`).
   **Contract:** the contract's reads are datasets only and a Slurm job stages datasets only, so this is a
   download inside the step and is not recorded as a read. To confirm, or to leave out of 0.5.
4. Record a dataset read, with its `name`, for the result.

### Staged folders, one per input

Today one variable (`KUBECORE_STAGED_DIR`) names one staged dataset. With several inputs there is one staged
folder per input, and kaos-lib trusts a folder only when its marker says so:

| Where | What happens |
|---|---|
| **Pod** | Nothing is staged. `input()` downloads into the cache volume once per commit; a second step on the same node, or a retry, finds it |
| **Slurm job** | Before the job starts, each entry of the job's `inputs[]` is staged into `<staged root>/<name>/`, with the marker `.kaos-ready` holding the repository, the commit and that the copy is complete. `input(name)` uses `<staged root>/<name>/` when the marker names the same repository and commit and says complete; otherwise it downloads in the job (the fallback OQ-02 keeps, unfiltered) and prints one line saying it did and why |

`layouts.local.staged_dir` changes from "the folder named by one variable" to "the folder for this input name
under the staged root", with the same marker checks it has today (`_staged_info`, `STAGED_COMMIT_FILES`). A
staged copy for another commit, or one without the "complete" flag (a copy staged by the old filter), is never
used: that is AC-05.

**Contract:** the name of the staged-root variable and the exact marker fields (Brief C adds the "complete"
flag or a new cache root). The contract at `dd2da46` defines `spec.inputs[]` and not where they land.

### `output(name)`

- `model` or `artifact`: an empty folder under the step's work folder. At `result()`, `outputs.RunWriter(app,
  experiment, run, kind=name)` saves it under `<name>/<experiment>/<run>/` in `outputs-<app>` (D-02: the name
  is the path segment, so yolo keeps `checkpoints/…`). The write records the merge commit on `main`.
- `dataset`: section 7.

## 7. The dataset writer (F-11, F-12)

A new class `datasets.DatasetWriter`, used only through `output()` and `result()`. For
`produces=[dataset("embeddings")]` the repository is `dataset-embeddings`, created by the platform, never here.

| Step | What | With |
|---|---|---|
| 1. Stage | Read `H0`, the head of `main` (the last version). Create the branch `run-<run>-<step>` from `H0`; when it exists (a retry) reuse it. `output()` returns the local folder; with `output(name, start="last")` the folder first receives the files of `H0`, for a step that changes a few files instead of writing all of them | `LakeFS.branch_commit`, `create_branch`; `layouts.local.fetch` |
| 2. Mirror | Make the branch's tree equal the local folder: upload what is new or changed, delete what is gone. Unchanged files are not uploaded (checksum compare), so a second run with one changed file uploads one file | `transfer.plan_mirror`, `transfer.apply_plan`, with a retry around each upload and `progress` lines |
| 3. Check | The registered `check()` conditions on the local folder (layout rules, minimum file count); then the branch's listing must equal the manifest: same paths, sizes and checksums. A failure stops here: nothing is committed | `layouts.rules`; `LakeFS.list_objects` |
| 4. Seal | Commit the branch. Metadata: `kaos.run`, `kaos.app`, `kaos.step`, `kaos.manifest` (the SHA-256 of the manifest) and one `kaos.read.<name>` per input opened. "No changes" is a success: the content equals the last version | `LakeFS.commit(tolerate_empty=True)` |
| 5. Verify | List the sealed commit and compare it with the manifest again. This is the check of CON-03: the version is exactly what the step wrote | `LakeFS.list_objects` on the commit id |
| 6. Keep | Tag the sealed commit `k-<run>-<step>`, so the version outlives its branch | `LakeFS.create_tag` |
| 7. Promote, only when the run asks | Merge the branch into `main` with `expected_head=H0`. Success: verify the merge commit against the manifest; that commit is the version | `LakeFS.merge(expected_head=)` (new argument) |
| 8. On 412 | `main` moved since step 1. Delete the branch, go to step 1 with the new head, at most three times, then fail | |
| 9. Clean up | Delete the run branch. Record the write: `{name, type: "dataset", repo, commit}` | `LakeFS.delete_branch` |

The manifest is the list of `(path, size, md5)` of the local folder, sorted, without any run identifier, so two
runs that write the same content produce the same manifest and no new commit.

Why each step is there, with what the real server showed (`tests/test_real_server.py`):

- **Stage from the last version**, not from an empty branch: the branch shares every unchanged file with `main`,
  so storage grows by the difference and lakeFS's diff between two versions is the real change (3.4).
- **Expected head.** Two branches that change *different* files both merge into `main` without any refusal and
  `main` then holds files of both runs
  (`test_two_merges_of_different_files_both_land_and_main_holds_a_mix`). Only when both change the *same* file
  does the server refuse (HTTP 409, body `{"reference": ""}`). The precondition makes the first case a 412.
- **A killed step leaves no version** (AC-09): uploads are uncommitted changes on the run branch. The retry
  lists the branch, which includes them, uploads only what is missing, and seals once.
- **`main` is protected.** A direct upload to a protected branch is refused (HTTP 403, "cannot write to
  protected branch") while a merge into it is accepted
  (`test_a_protected_branch_refuses_a_direct_write_and_accepts_a_merge`); the writer never writes to `main`
  directly.

Uploads are HTTP `POST`, which the client's session does not retry today (`lakefs.py:40-41` retries `HEAD`,
`GET`, `PUT`, `DELETE`). The mirror retries each failed upload up to four times with a growing pause; an upload
is safe to repeat because it replaces the same path.

**Contract:** how "this run promotes" reaches the step (D-06). The contract at `dd2da46` does not say. This note
assumes a boolean `promote` on the `produces` entry of a dataset, default false.

**Choice:** the recorded commit is the merge commit on `main` when the run promotes, and the sealed commit on
the run branch (kept by its `k-` tag) when it does not. Both are verified against the manifest.

**Choice:** `check()` is not defined by the PRD beyond its name. The signature above (`layout=`, `min_files=`)
reuses the layout rules kaos-lib already has. A free-form assertion needs no API: step code raises.

## 8. What fails loudly

Every failure is a `StepError` (a new subclass of `KaosLibError`), exits non-zero, and writes no result file.
`<…>` is filled in.

| When | Message |
|---|---|
| `KAOS_STEP_CONTEXT` is not set | `this is not a pipeline step: KAOS_STEP_CONTEXT is not set. Run the step with: kaosctl step run <step>` |
| The value is over 96 KiB | `the step context is <n> bytes; the limit is 98304. Move large values out of the config into a dataset or an artifact.` |
| Not JSON, or not an object | `the step context is not a JSON object (<parser error>). The platform built it wrongly: report this with the run id.` |
| `version` is not 1 | `the step context has version <v>; this kaos-lib reads version 1. Upgrade kaos-lib in the step image.` |
| A required field is missing or has the wrong type | `the step context has no <field> (<what was found>).` |
| `kind` is not one of the six | `the step context has kind '<k>'; a step is one of ingest, transform, train, evaluate, publish, control.` |
| `input()`, `output()`, `upstream()`, `check()` or `result()` before `start()` | `call step.start() first.` |
| `input(name)` not declared and not produced upstream | `'<name>' is not an input of step '<step>'. Its inputs are: <names>. Add it to inputs=[…] in pipeline.py.` |
| `input(name, version=…)` or any extra argument | A `TypeError` from Python: the function takes one argument |
| `datasets.resolve` inside a step for a repository the ledger does not cover | `<repo> is not an input of step '<step>': a step reads only the versions the run pinned. Add the config value that names it to inputs=[…] in pipeline.py.` |
| The pinned commit does not exist | `input '<name>': commit <commit> of <repo> does not exist any more.` |
| A staged folder holds another commit or is not complete (Slurm job) | Not a failure: one line `input '<name>': the staged copy is <reason>; downloading <repo>@<commit>.` and the download |
| The input holds no files | `EmptyDataset` as today: `<repo>@<ref> holds no files.` |
| `output(name)` not declared | `'<name>' is not produced by step '<step>'. It produces: <names>. Add it to produces=[…] in pipeline.py.` |
| `upstream(x)` and `x` is not upstream | `step '<x>' is not upstream of '<step>'. Add needs=['<x>'] in pipeline.py.` |
| `upstream(x)` and its result is absent | `step '<x>' wrote no result: it was skipped, or it ended without step.result(). '<step>' needs it. Use upstream('<x>', required=False) if this step can run without it.` |
| A value passed to `result()` is not JSON | `result value '<key>' is a <type>; values are text, numbers, booleans, lists and objects.` |
| The result is over 32 KiB | `the result is <n> bytes; the limit is 32768. The largest value is '<key>' (<m> bytes): save it with step.output() instead.` |
| `result()` called twice | `step.result() was already called.` |
| A declared output folder is empty at `result()` | `output '<name>' is empty: the step wrote no files into <path>.` |
| A registered check fails | `output '<name>' failed its check: <problems, one per line>. Nothing was saved.` |
| The branch listing differs from the manifest | `output '<name>': <n> files differ between what the step wrote and what lakeFS holds (first: <path>). Nothing was sealed.` |
| The sealed commit differs from the manifest | `output '<name>': the sealed version <commit> is not what the step wrote (first: <path>). It was not promoted.` |
| Not allowed to write the dataset (403) | `this app may not write <repo>: it is not a dataset '<app>' declares. Add dataset("<name>") to produces=[…] in pipeline.py.` |
| Promotion refused three times (412) | `output '<name>': <repo> main changed three times while this step was promoting. Another run is writing the same dataset. The sealed version is kept as k-<run>-<step>.` |
| The process exits 0 after `start()` without `result()` | `step '<step>' ended without step.result(): the next step would get nothing. Call step.result() as the last line.` and exit code 1 |

## 9. What the wave deletes in this repository

Line numbers are on `main` at `6ccbc96`. "Rewrite" means the file stays and the named lines go.

### Files deleted whole

| File | Why |
|---|---|
| `src/kubecore/__init__.py` (21 lines) | The `kubecore` import shim (8.3) |
| `tests/test_rename.py` (100 lines) | Tests of the shim and of both command aliases |
| `docs/formerly-kubecore.md` (14 lines) and `mkdocs.yml:142` (its navigation line) | The page about the shim and the aliases |
| `tests/test_lock_written_with_the_run.py` (123 lines) | Tests `frameworks.write_data_lock`, replaced by the ledger write in `result()` |

### Code

| Where | What goes |
|---|---|
| `pyproject.toml:33-34` | The `kaos-cli` and `kubecore` script entries |
| `src/kaos_lib/cli.py:587-598`, and the first line of its docstring (`:1`) | `kubecore_alias`, `kaos_cli_alias` |
| `src/kaos_lib/errors.py:9` | `KubecoreError`, "removed together with the shim" |
| `src/kaos_lib/_release.json:6` | The `migration` link to `README.md#formerly-kubecore`; it is empty: no app is moved |
| `src/kaos_lib/runtime.py:18-20`, `:46-47`, `:75-76`, `:136-138` | `dataset_ref`, `dataset_commit` and their variables `KUBECORE_DATASET_REF`, `DATASET`, `DATASET_REPO`, `DATASET_REF`, `KUBECORE_DATASET_COMMIT`, `DATASET_COMMIT` (8.3: unused dataset fields) |
| `src/kaos_lib/runtime.py:10-15`, `:38-43`, `:89-93`, `:135`, `:142-144` | The environment sources of `run_id`, `workflow`, `app`, `project`, `step`, `outputs_repo` (`KUBECORE_RUN_ID`, `KUBECORE_WORKFLOW_NAME`, `KUBECORE_APP`, `KUBECORE_PROJECT`, `KUBECORE_STEP`, `STEP_NAME`, `OUTPUTS_REPO`, `CHECKPOINT_BUCKET`), `_app_of`, and `run_id()`'s own read: the step context is the one source (`outputs_repo` is `outputs-<app>`). To execute only once the contract document confirms the platform stops setting them |
| `src/kaos_lib/__init__.py:26`, `src/kaos_lib/studio/run.py:98`, `src/kaos_lib/studio/constants.py:36-37` | Direct uses of `KUBECORE_RUN_ID`, `CHECKPOINT_BUCKET`, `OUTPUTS_REPO`, `KUBECORE_WORKFLOW_NAME` outside `runtime.py` |
| `src/kaos_lib/lock.py:32` | `VERSION = 1` becomes 2 |
| `src/kaos_lib/lock.py:47-48`, `:85-89` | The version-1 writers `Read.as_dict`, `DataLock.to_dict`, `to_json` (rewritten for version 2; the v1 shape is only parsed) |
| `src/kaos_lib/lock.py:133-148`, `:173-175` | `DataLock.write` and `lock.write`: the merge into the shared `data.lock.json` |
| `src/kaos_lib/frameworks.py:320-344`, `:355` | `_lock_written`, `write_data_lock` and its call |
| `src/kaos_lib/layouts/local.py:24`, `:66-86` | `KUBECORE_STAGED_DIR` and the single staged folder; replaced by one folder per input (section 6) |
| `src/kaos_lib/outputs.py:3-4` | The sentence "Pipelines never write to a `dataset-*` repository" (D-04 amends it) |
| `src/kaos_lib/lakefs.py:22` | `USER_AGENT = "kaos-lib/0.4"` becomes 0.5 |
| `src/kaos_lib/lint/constants.py:26` | `outputs` and `hpc_time_limit` leave `STEP_PARAMS`; `kind`, `inputs`, `produces`, `walltime` enter |
| `src/kaos_lib/lint/schema.py:24` | `RENAMED_ARGUMENTS = {"walltime": "hpc_time_limit"}`: today the linter tells people to rename `walltime` to `hpc_time_limit`. It is reversed, and it is a rule with a fix, not an alias |
| `src/kaos_lib/lint/schema.py:57-61`, `:73-80` | The `outputs` entry; the `hpc_time_limit` entry is renamed |
| `src/kaos_lib/lint/rules_errors.py:31-58`, `:223-225`, `:239-247`; `rules_warnings.py:18-27`; `rules_infos.py:16-31`; `graph.py:41` | Every `hpc_time_limit` reference becomes `walltime`; the rule text that recommends `hpc_time_limit` goes |
| `src/kaos_lib/studio/run.py:4`, `:47-59`, `:80`, `:139-145`; `studio/cli.py:39-43`; `studio/steps.py:68` | `kaosctl step run` passing `--params` and one `--<output> <json>` argument per upstream output, and reading back per-output result files. It sets `KAOS_STEP_CONTEXT` and reads the one result file instead |
| `src/kaos_lib/studio/build.py:164` | The hint `… run --rm <image> --params '<params>'` |
| `editors/vscode/resources/step-schema.json` (regenerated), `editors/vscode/src/report.ts:35`, `:137`, `editors/vscode/src/graphHtml.ts:72` | `outputs`, `hpc_time_limit` in the bundled schema and the graph view |

### Tests

| Where | What goes |
|---|---|
| `tests/test_lock.py:88-161`, `:250-258`, `:300-313` | The `write` tests, the fixture and the two round trips that go through `write` (rewritten on the per-step ledger file); the version-1 `to_json` at `:222` |
| `tests/test_runtime.py` | The cases for the deleted fields and variables (the file is rewritten around the step context) |
| `tests/conftest.py:11`, `:15-18` | `KUBECORE_STAGED_DIR` and the run-context variables in `ENV_VARS` |
| `tests/test_docs_gen.py:31` | The assertion on the `kaos-cli` sentence |
| `tests/lint_corpus.py`, `tests/test_lint_*.py`, `tests/test_studio_run.py`, `tests/studio_helpers.py` | Cases for `outputs=`, `hpc_time_limit=`, `--params` and per-output files |

### Docs

| Where | What goes |
|---|---|
| `README.md:45-47`, `docs/install.md:48`, `docs_gen.py:53-54`, `docs/develop.md:38`, `:42`, `docs/support-window.md:15` | The alias and shim sentences |
| `docs/data-lock.md` (42 lines) | Rewritten as the ledger page; the `lock.write()` instructions go |
| `docs/runtime.md:20-21`, `:31-33`, and the variable column of its table | The dataset fields and the list of environment variables |
| `docs/steps.md`, `docs/step-examples.md`, `docs/steps-and-datasets.md`, `docs/step-run.md` | Rewritten for the new contract (plan G4): `--params`, `write_output`, `cfg["dataset"]`, `DatasetRef.parse`, `outputs.run(app, …)`, `context().dataset_ref` all go |
| `docs/outputs.md:13`, `docs/quickstart.md:82`, `README.md:42` | `r.finish({"dataset_ref": …})`: the result carries the reads |
| `docs/lint.md`, `docs/lint/L-*.md` | Every `hpc_time_limit` and `outputs=` mention |

### Not deleted, and why

- `from kubecore.authoring import pipeline, step` (in `docs/steps.md:27`, `docs/step-examples.md:911`,
  `tests/lint_corpus.py:14`, `editors/vscode/src/detect.ts:17`, `src/kaos_lib/studio/pipeline_engine.py:217`)
  is the platform's authoring module, not this repository's shim. Its name is the contract's to decide.
- `src/kaos_lib/formats/` (the 0.3 `get_format` API) and `tests/test_legacy_id.py` (the `ultralytics` label on
  existing repositories) are not in section 8.3 of the PRD. They are older leftovers; mentioned, not touched.
- `KUBECORE_ML_HOME`, `KUBECORE_CACHE_DIR`, `KUBECORE_DATASET_CONFIG`, `KUBECORE_ML_OIDC_*`,
  `KUBECORE_SLOT_*`, `KAOS_LIB_SUPPORT`: not part of the step contract.
- `DataLock.parse` for version 1, `lock.load`, `kaosctl run --lock`: kept read-only (D-08).

## 10. OQ-09: who else reads the data lock on the MLflow run?

Nobody outside kaos-lib. Searched on 2026-11-12 for `data.lock`, `kaos_lib.data.`, `data_lock`, `DataLock`,
`KAOS_LIB_LOCK` at the trunk heads of kaos-hpc-operator (`main` fd730c0), charts (`main` 0c6a819),
kubecore-operator (`dev` 7dcde84e), hera template (`dev` 292db45), yolo template (`dev` 3de6f72), kaos (`prod`
7768077f) and kaos-lake (`kaos/1.86` b2b2597f).

| Who | Touches the MLflow copy how | Evidence |
|---|---|---|
| kaos-lib | Reads it: `lock.load` → `kaosctl run --lock`; and `DataLock.write` reads it to merge | `src/kaos_lib/cli.py:324-329`, `lock.py:140-141`, `:178-184` |
| kaos-lib | Writes it: automatically when a tracked run ends | `src/kaos_lib/frameworks.py:325-338`, `:355` |
| yolo template | Writes it, never reads it: `lock.record` + `lock.write` | `steps/model_training/app/entry.py:138-151`, `steps/model_registration/app/entry.py:89-100`; shape asserted in `step_tests/test_mlflow_auth_entry.py:117-153` |
| hera template | Neither; documents it | `docs/results.md:70-82`, `docs/cookbook/8-results-and-weights.md:49-50`, `:81`, `docs/glossary.md:15` |
| kaos e2e | Does not read it. Its only MLflow tag check is `kaos_lib.version` | `scripts/e2e/kaose2e/delivery.py:81`, `:620` |
| kubecore-operator, charts, kaos-lake | Nothing | No match |

So the MLflow copy can change shape freely: the only code that parses it is `DataLock.parse`, which keeps
reading version 1.

What does change shape for other readers is the **same JSON on its other carriers**, which the wave replaces
anyway (context and result): the platform's `data-lock` step output and `$KAOS_LIB_LOCK`
(`engine/kubecore/authoring.py:51-54`, `compose.py:336-412` in kaos-hpc-operator), the runner's
`settings.py:251-252` and `runner.py:210`, which build a version-1 lock for a Slurm job, and the e2e checks that
parse `reads[].commit` from the `data-lock` output (`scripts/e2e/kaose2e/mlrun.py:1016-1048`, with fakes in
`scripts/e2e/tests/ml_fakes.py:37`, `:167-169`). Those are packages W2, W3 and W6, not this repository.

## 11. Test plan for W1

- The contract fixtures are copied into `tests/contract_fixtures/` with their SHA-256 list by one script, from
  a checkout of kaos-hpc-operator, the way `tests/layout_fixtures/` is kept equal to kaos-lake today; a test
  fails when the list and the files differ. `start()` is tested on every `context-*.wire`; `result()` must
  produce `result-ok.wire` and `result-model.wire` byte for byte from the matching context.
- Every row of section 8 is one test asserting the message.
- The dataset writer is tested twice: on the fake, extended with `expected_head` (412) and nothing else; and on
  the real server (`KAOS_LIB_TEST_LAKEFS=real`) for what the fake cannot show. The 412 tests need the kaos-lake
  image (`kaos-lake:prd1911`); on upstream lakeFS they are skipped with that reason.
