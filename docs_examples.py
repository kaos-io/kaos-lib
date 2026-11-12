#!/usr/bin/env python3
"""The code of the guide is real: every example app under docs/examples is built, checked and run here.

    python3 docs_examples.py          check every example (what `mkdocs build` does through docs/hooks.py)

The guide's first ten pages follow one app. `docs/examples/first-pipeline/template` is the hera template as a
reader creates it; every other folder beside it holds the files one page changes. The state of the app after a
page is the template with the folders of the pages up to it laid over it, in the order of STATES. Each state is

  * linted with kaosctl's linter (no error),
  * run: every one of its steps is started with `kaos_lib.testing.running` on small data and must hand on the
    result its page describes.

`docs/examples/second-pipeline` is the pipeline of page 6, `docs/examples/yolo-pipeline` the pipeline file of
page 11 (compiled; its steps need a GPU and the full yolo template).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import pathlib
import re
import shutil
import sys
import tempfile
from typing import Optional

import yaml

HERE = pathlib.Path(__file__).resolve().parent
EXAMPLES = HERE / "docs" / "examples"
FIRST = EXAMPLES / "first-pipeline"
SECOND = EXAMPLES / "second-pipeline"
FLOWS = EXAMPLES / "flows"
# The folders of FIRST in the order the pages lay them over the template.
STATES = ("template", "first-step", "settings", "read-data", "pass-on", "gpu", "long-job", "hpc", "try-locally")
DOCKERFILE = '''FROM python:3.11-slim
WORKDIR /app
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel]==0.5.0"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
'''
STUB = '"""A stand-in for a step the guide does not show."""\nfrom kaos_lib import step\n\n\ndef main() -> None:\n' \
       '    step.start()\n    step.result()\n\n\nif __name__ == "__main__":\n    main()\n'


class ExampleError(AssertionError):
    """An example of the guide does not do what its page says."""


def assemble(state: str, dest: pathlib.Path, stubs: bool = True) -> pathlib.Path:
    """The app after the page `state`, built in `dest`: the template, the folders up to the state over it, and
    what an app also holds (an image file for every step; a stand-in for a step the guide does not show)."""
    if state not in STATES:
        raise ExampleError(f"unknown state {state!r}; the states are {', '.join(STATES)}")
    for name in STATES[: STATES.index(state) + 1]:
        shutil.copytree(FIRST / name, dest, dirs_exist_ok=True)
    if stubs:
        complete(dest)
    return dest


def step_names(app: pathlib.Path) -> list:
    return sorted(p.parent.name for p in (app / "steps").glob("*/app/entry.py"))


def complete(app: pathlib.Path) -> None:
    """A Dockerfile for every step folder, and a folder for every step that pipeline.py names."""
    text = (app / "pipeline.py").read_text(encoding="utf-8")
    for name in re.findall(r'step\(\s*"([a-z0-9-]+)"', text):
        folder = app / "steps" / name.replace("-", "_")
        if not (folder / "app" / "entry.py").is_file():
            (folder / "app").mkdir(parents=True, exist_ok=True)
            (folder / "app" / "entry.py").write_text(STUB, encoding="utf-8")
    for entry in (app / "steps").glob("*/app/entry.py"):
        (entry.parent / "__init__.py").touch()
        if not (entry.parent.parent / "Dockerfile").is_file():
            (entry.parent.parent / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")


def lint(app: pathlib.Path):
    from kaos_lib.lint import default_catalogue, lint_project
    return lint_project(app, default_catalogue())


def load(app: pathlib.Path, step_folder: str):
    path = app / "steps" / step_folder / "app" / "entry.py"
    spec = importlib.util.spec_from_file_location(f"docs_example_{step_folder}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(folder: pathlib.Path, **files: str) -> pathlib.Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


class Walk:
    """One state of the app, its steps run one after the other the way a run does. Nothing is uploaded."""

    def __init__(self, state: str, tmp: pathlib.Path):
        self.state, self.tmp = state, pathlib.Path(tmp)
        self.app = assemble(state, self.tmp / "app")
        self.later = STATES.index(state)
        self.results: dict = {}
        self.outputs: dict = {}
        self.params = {"prepare": {"min_bytes": 1}, "hello": {"title": "hello"}, "train": {"epochs": 5}}

    def has(self, state: str) -> bool:
        return self.later >= STATES.index(state)

    def _run(self, name: str, kind: str, produces: list, **kwargs) -> dict:
        from kaos_lib import testing
        work = self.tmp / f"run-{name}-{len(list(self.tmp.glob(f'run-{name}-*')))}"
        work.mkdir()
        with testing.running(work, kind=kind, name=name, app="myapp", experiment="my-experiment-v1",
                             params=self.params, produces=produces, **kwargs) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            load(self.app, name.replace("-", "_")).main()
        self.outputs[name] = {n: run.output(n) for _, n in produces}
        self.results[name] = run.result
        if run.result is None:
            raise ExampleError(f"the step {name} of the state {self.state} handed on no result")
        return run.result

    def prepare(self) -> dict:
        data = _tree(self.tmp / "data", **{"a.txt": "alpha\n", "b.txt": "bravo\n", "empty.txt": ""})
        produces = [("dataset", "clean")] + ([("artifact", "dropped-files")] if self.has("pass-on") else [])
        result = self._run("prepare", "transform", produces, inputs={"dataset": data})
        if result["values"] != {"files": 2, "dropped": 1}:
            raise ExampleError(f"prepare handed on {result['values']}")
        clean = self.outputs["prepare"]["clean"]
        if sorted(p.name for p in clean.iterdir()) != ["a.txt", "b.txt"]:
            raise ExampleError("prepare did not write the two files that are not empty into clean")
        if self.has("pass-on"):
            dropped = self.outputs["prepare"]["dropped-files"] / "dropped.txt"
            if dropped.read_text(encoding="utf-8") != "empty.txt\n":
                raise ExampleError("prepare did not name the file it dropped")
        return result

    def _upstream(self) -> dict:
        written = {"clean": self.outputs["prepare"]["clean"]}
        if self.has("pass-on"):
            written["dropped-files"] = self.outputs["prepare"]["dropped-files"]
        return {"upstream": {"prepare": self.results["prepare"]["values"]}, "upstream_writes": {"prepare": written}}

    def hello_world(self) -> dict:
        kwargs = self._upstream()
        if self.has("read-data"):
            kwargs["inputs"] = {"reference": _tree(self.tmp / "reference", **{"r1.txt": "1", "r2.txt": "2", "r3.txt": "3"})}
        result = self._run("hello-world", "evaluate", [("artifact", "report")], **kwargs)
        line = (self.outputs["hello-world"]["report"] / "hello.txt").read_text(encoding="utf-8")
        values = result["values"]
        expected = {"files": 2, "size": 12} if self.has("first-step") else {"files": 2}
        if self.has("read-data"):
            expected["reference"] = 3
        if values != expected:
            raise ExampleError(f"hello-world handed on {values}, not {expected}")
        for part in ("2 files", "1 dropped by prepare"):
            if part not in line:
                raise ExampleError(f"the report of hello-world does not say {part!r}: {line!r}")
        if self.has("settings") and not line.startswith("hello (my-experiment-v1): "):
            raise ExampleError(f"the report of hello-world does not start with the setting: {line!r}")
        if self.has("pass-on") and not line.strip().endswith("empty.txt"):
            raise ExampleError(f"the report of hello-world does not name the dropped file: {line!r}")
        return result

    def train(self, stop_after: Optional[int] = None) -> dict:
        """Run `train` once; with `stop_after`, the platform asks it to stop after that many epochs (it ends with
        exit code 85, as `checkpoint.exit_for_restart` ends a step); the checkpoint folder stays for the next call."""
        from kaos_lib import checkpoint
        folder = self.tmp / "checkpoints"
        saved = os.environ.get(checkpoint.CHECKPOINT_DIR_ENV)
        os.environ[checkpoint.CHECKPOINT_DIR_ENV] = str(folder)
        real = checkpoint.stop_requested
        if stop_after is not None:
            asked = []
            checkpoint.stop_requested = lambda: asked.append(1) or len(asked) >= stop_after  # looked at once per epoch
        try:
            return self._run("train", "train", [("model", "model")], **self._upstream())
        finally:
            checkpoint.stop_requested = real
            if saved is None:
                os.environ.pop(checkpoint.CHECKPOINT_DIR_ENV, None)
            else:
                os.environ[checkpoint.CHECKPOINT_DIR_ENV] = saved

    def second(self) -> dict:
        """The second pipeline: its step reads the dataset that the first one produced."""
        app = self.tmp / "second"
        shutil.copytree(SECOND, app)
        complete(app)
        clean = _tree(self.tmp / "clean-of-myapp", **{"a.txt": "a", "b.txt": "b", "c.txt": "c"})
        from kaos_lib import testing
        work = self.tmp / "run-evaluate"
        work.mkdir()
        with testing.running(work, kind="evaluate", name="evaluate", app="other", inputs={"clean": clean},
                             produces=[("artifact", "report")]) as run:
            load(app, "evaluate").main()
        if run.result["values"] != {"files": 3}:
            raise ExampleError(f"evaluate handed on {run.result['values']}")
        return run.result


def run_step(app: pathlib.Path, work: pathlib.Path, name: str, kind: str, produces: list = (), params=None, **kwargs):
    """One step of an example app, started with `kaos_lib.testing.running`; returns (result, run)."""
    from kaos_lib import testing
    work.mkdir(parents=True, exist_ok=True)
    with testing.running(work, kind=kind, name=name, app="myapp", experiment="my-experiment-v1", params=params or {},
                         produces=list(produces), **kwargs) as run, contextlib.redirect_stdout(io.StringIO()):
        load(app, name.replace("-", "_")).main()
    if run.result is None:
        raise ExampleError(f"the step {name} handed on no result")
    return run.result, run


def flow_app(name: str, tmp: pathlib.Path) -> pathlib.Path:
    """The example app `flows/<name>`, with an image file for every step; it must lint without an error."""
    app = tmp / name
    shutil.copytree(FLOWS / name, app)
    complete(app)
    report = lint(app)
    if report.errors:
        raise ExampleError(f"kaosctl lint finds errors in flows/{name}:\n{report.to_json()}")
    return app


def flow_two_inputs(tmp: pathlib.Path) -> dict:
    """A step with two inputs: two versions of one dataset, side by side."""
    app = flow_app("two-inputs", tmp)
    before = _tree(tmp / "before", **{"a.txt": "a", "b.txt": "b"})
    after = _tree(tmp / "after", **{"b.txt": "b", "c.txt": "c", "d.txt": "d"})
    result, run = run_step(app, tmp / "run", "compare", "evaluate", [("artifact", "changes")],
                           inputs={"before": before, "after": after})
    if result["values"] != {"added": 2, "removed": 1}:
        raise ExampleError(f"compare handed on {result['values']}")
    if sorted(r["name"] for r in result["reads"]) != ["after", "before"]:
        raise ExampleError("compare did not record both inputs as read")
    if (run.output("changes") / "changes.txt").read_text() != "added c.txt\nadded d.txt\nremoved a.txt\n":
        raise ExampleError("compare wrote another list of changes")
    return result


def flow_skip(tmp: pathlib.Path) -> dict:
    """A step that may be skipped, and the step after it that copes: run both ways."""
    app = flow_app("skip", tmp)
    summary = _tree(tmp / "summary", **{"summary.txt": "base ran\n"})
    base, _ = run_step(app, tmp / "base", "base", "transform", [("artifact", "summary")])
    if base["values"] != {"base": True}:
        raise ExampleError(f"base handed on {base['values']}")
    skipped, run = run_step(app, tmp / "final-1", "final", "evaluate", [("artifact", "final-report")],
                            upstream={"base": base["values"], "extra": None}, upstream_writes={"base": {"summary": summary}})
    if skipped["values"] != {"extra_ran": False}:
        raise ExampleError(f"final handed on {skipped['values']} after a skipped extra")
    extra, extra_run = run_step(app, tmp / "extra", "extra", "evaluate", [("artifact", "extra-report")],
                                upstream={"base": base["values"]}, upstream_writes={"base": {"summary": summary}})
    ran, run = run_step(app, tmp / "final-2", "final", "evaluate", [("artifact", "final-report")],
                        upstream={"base": base["values"], "extra": extra["values"]},
                        upstream_writes={"extra": {"extra-report": extra_run.output("extra-report")}})
    if ran["values"] != {"extra_ran": True} or "score 7" not in (run.output("final-report") / "final.txt").read_text():
        raise ExampleError("final did not use the result of extra")
    return ran


def flow_fan_in(tmp: pathlib.Path) -> dict:
    """One step that needs two others: it reads both results and the model of the better one."""
    app = flow_app("fan-in", tmp)
    params = {"train": {"small_epochs": 3, "large_epochs": 9}}
    trained = {}
    for size in ("small", "large"):
        trained[size] = run_step(app, tmp / size, f"train-{size}", "train", [("model", size)], params=params)
    result, run = run_step(
        app, tmp / "pick", "pick-best", "evaluate", [("artifact", "winner")],
        upstream={f"train-{s}": trained[s][0]["values"] for s in trained},
        upstream_writes={f"train-{s}": {s: {"folder": trained[s][1].output(s), "type": "model"}} for s in trained})
    if result["values"] != {"winner": "large", "score_small": 3, "score_large": 9}:
        raise ExampleError(f"pick-best handed on {result['values']}")
    if (run.output("winner") / "weights.txt").read_text() != "large model, 9 epochs\n":
        raise ExampleError("pick-best did not keep the model of the winner")
    return result


def ledger_example(tmp: pathlib.Path) -> dict:
    """The result of `hello-world` of the page 5 app when `prepare` wrote the dataset `clean` in this run: it names
    what the step read (the input `reference`, and `clean`) and what it wrote (the artifact `report`). The commits
    are fingerprints of the content here; on the platform they are the commits of the data store."""
    app = assemble("pass-on", tmp / "app")
    clean = _tree(tmp / "clean", **{"a.txt": "alpha\n", "b.txt": "bravo\n"})
    dropped = _tree(tmp / "dropped", **{"dropped.txt": "empty.txt\n"})
    reference = _tree(tmp / "reference", **{"r1.txt": "1", "r2.txt": "2", "r3.txt": "3"})
    result, _ = run_step(app, tmp / "run", "hello-world", "evaluate", [("artifact", "report")],
                         params={"hello": {"title": "hello"}}, inputs={"reference": reference},
                         upstream={"prepare": {"files": 2, "dropped": 1}},
                         upstream_writes={"prepare": {"clean": {"folder": clean, "type": "dataset"},
                                                      "dropped-files": dropped}})
    return result


def flow_metrics(tmp: pathlib.Path) -> dict:
    """A step that logs a parameter and a curve to MLflow (a local store stands in for the project's server) and
    saves a model: the metrics must be there, and the model folder holds the weights."""
    app = flow_app("metrics", tmp)
    store = tmp / "mlruns"
    env = {"MLFLOW_TRACKING_URI": f"file://{store}", "MLFLOW_TRACKING_TOKEN": "a-token", "MLFLOW_ALLOW_FILE_STORE": "true"}
    saved = {key: os.environ.get(key) for key in (*env, "MLFLOW_TRACKING_AUTH")}   # the call sets the last one
    had = {name for name in sys.modules if name.split(".")[0] == "mlflow"}
    try:
        os.environ.update(env)
        result, run = run_step(app, tmp / "run", "train", "train", [("model", "model")], params={"train": {"epochs": 3}})
        from mlflow.tracking import MlflowClient
        client = MlflowClient()
        found = client.search_runs([client.get_experiment_by_name("my-experiment-v1").experiment_id])
        curve = [m.value for m in client.get_metric_history(found[0].info.run_id, "loss")]
    finally:
        for name in [m for m in sys.modules if m.split(".")[0] == "mlflow" and m not in had]:
            del sys.modules[name]          # the package keeps the store it was pointed at: leave no import behind
        for key, value in saved.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)
    if curve != [1.0, 0.5, 1 / 3] or found[0].data.params != {"epochs": "3"}:
        raise ExampleError(f"train logged {curve} and {found[0].data.params} to MLflow")
    if (run.output("model") / "weights.txt").read_text() != "trained for 3 epochs\n" or result["values"] != {"final_loss": 1 / 3}:
        raise ExampleError(f"train handed on {result['values']}")
    return result


def flow_ingest(tmp: pathlib.Path) -> dict:
    """An `ingest` step that reads a folder standing in for the outside source, and a source with no file."""
    app = flow_app("ingest", tmp)
    source = _tree(tmp / "source", **{"a.csv": "1,2\n", "b.csv": "3,4\n", "notes.txt": "not data\n"})
    result, run = run_step(app, tmp / "run", "fetch", "ingest", [("dataset", "raw")],
                           params={"source": {"folder": str(source)}})
    if result["values"] != {"files": 2} or sorted(p.name for p in run.output("raw").iterdir()) != ["a.csv", "b.csv"]:
        raise ExampleError(f"fetch handed on {result['values']}")
    from kaos_lib.errors import StepError
    try:
        run_step(app, tmp / "empty", "fetch", "ingest", [("dataset", "raw")],
                 params={"source": {"folder": str(_tree(tmp / "nothing", **{"notes.txt": "x"}))}})
    except StepError:
        return result
    raise ExampleError("fetch did not fail when the source gave no file")


def flow_publish(tmp: pathlib.Path) -> dict:
    """A `publish` step delivers the model the step before it wrote and produces nothing of its own."""
    app = flow_app("publish", tmp)
    trained, run = run_step(app, tmp / "train", "train", "train", [("model", "model")])
    delivered, _ = run_step(app, tmp / "register", "register", "publish", [], params={"registry": {"name": "my-model"}},
                            upstream={"train": trained["values"]}, upstream_writes={"train": {"model": run.output("model")}})
    if delivered["values"] != {"delivered": "my-model"} or delivered["writes"]:
        raise ExampleError(f"register handed on {delivered}")
    return delivered


def flow_control(tmp: pathlib.Path) -> dict:
    """A `control` step lets a good run go on, hands its values to the next step, and ends a run with wrong settings."""
    app = flow_app("control", tmp)
    checked, _ = run_step(app, tmp / "check", "check", "control", [], params={"check": {"epochs": 5}})
    if checked["values"] != {"ok": True, "epochs": 5} or checked["writes"]:
        raise ExampleError(f"check handed on {checked}")
    worked, run = run_step(app, tmp / "work", "work", "evaluate", [("artifact", "report")], upstream={"check": checked["values"]})
    if (run.output("report") / "report.txt").read_text() != "checked for 5 epochs\n":
        raise ExampleError("work did not read the values of check")
    try:
        run_step(app, tmp / "bad", "check", "control", [], params={"check": {"epochs": 0}})
    except SystemExit as exc:
        if "must be at least 1" not in str(exc):
            raise ExampleError(f"check ended the run with {exc}") from None
        return worked
    raise ExampleError("check did not end a run with 0 epochs")


def _run_ending(app, work, name, kind, produces, **kwargs):
    """One step started with `kaos_lib.testing.running` that may end by itself (`step.skip`): (exit code or None, run)."""
    from kaos_lib import testing
    work.mkdir(parents=True, exist_ok=True)
    code = None
    with testing.running(work, kind=kind, name=name, app="myapp", experiment="my-experiment-v1",
                         produces=list(produces), **kwargs) as run, contextlib.redirect_stdout(io.StringIO()):
        try:
            load(app, name.replace("-", "_")).main()
        except SystemExit as exc:
            code = exc.code
    return code, run


def flow_conditions(tmp: pathlib.Path) -> dict:
    """`when=` on a value of a needed step and `step.skip()`: run the whole pipeline three ways (the model passes and
    publish delivers; it passes and publish skips itself; it does not pass and publish does not run)."""
    app = flow_app("conditions", tmp)
    summary = {}
    for case, epochs, name, line in (
            ("delivered", 5, "my-model", "score 0.5: published as my-model"),
            ("skipped", 5, "", "score 0.5: not published, no registry name is set in config/registry.yaml"),
            ("failed", 2, "my-model", "score 0.2: not published, the model did not pass")):
        base = tmp / case
        trained, trun = run_step(app, base / "train", "train", "train", [("model", "model")], params={"train": {"epochs": epochs}})
        evaluated, erun = run_step(app, base / "evaluate", "evaluate", "evaluate", [("artifact", "verdict")],
                                   params={"evaluate": {"threshold": 0.3}}, upstream={"train": trained["values"]},
                                   upstream_writes={"train": {"model": trun.output("model")}})
        if evaluated["values"] != {"passed": epochs / 10 >= 0.3, "score": epochs / 10}:
            raise ExampleError(f"evaluate handed on {evaluated['values']}")
        kwargs = {}
        if case == "failed":                      # the condition `evaluate.passed == true` is false: publish never starts
            publish_upstream = {"publish": None}
        else:
            code, prun = _run_ending(app, base / "publish", "publish", "publish", [], params={"registry": {"name": name}},
                                     upstream={"evaluate": evaluated["values"]})
            if case == "delivered" and (code is not None or prun.result["values"] != {"delivered": "my-model"}):
                raise ExampleError(f"publish ended with {code!r} and {prun.result}")
            if case == "skipped":
                reason = "no registry name is set in config/registry.yaml"
                if code != 0 or prun.result != {"version": 1, "status": "skipped", "reason": reason}:
                    raise ExampleError(f"publish did not skip itself cleanly: {code!r} {prun.result}")
                kwargs["upstream_skipped"] = {"publish": reason}
                publish_upstream = {}
            else:
                publish_upstream = {"publish": prun.result["values"]}
        result, run = run_step(app, base / "summary", "summary", "evaluate", [("artifact", "summary-report")],
                               upstream={"evaluate": evaluated["values"], **publish_upstream}, **kwargs)
        if (run.output("summary-report") / "summary.txt").read_text() != line + "\n":
            raise ExampleError(f"summary wrote another line in the case {case}")
        summary[case] = result["values"]
    if summary != {"delivered": {"published": True}, "skipped": {"published": False}, "failed": {"published": False}}:
        raise ExampleError(f"summary handed on {summary}")
    return summary


def flow_sweep(tmp: pathlib.Path) -> dict:
    """A sweep as a loop inside one step: it tries every rate of the setting and keeps the best."""
    app = flow_app("sweep", tmp)
    result, run = run_step(app, tmp / "run", "train", "train", [("model", "best-model")],
                           params={"train": {"epochs": 3, "learning_rates": "0.1,0.01,0.001"}})
    if result["values"]["best_learning_rate"] != 0.01 or result["values"]["tried"] != 3:
        raise ExampleError(f"train handed on {result['values']}")
    if (run.output("best-model") / "weights.txt").read_text() != "learning rate 0.01\n":
        raise ExampleError("train did not keep the best model")
    return result


def rerun_pin() -> None:
    """The setting of the page "Re-running" pins a version of a dataset of the same project."""
    from kaos_lib.datasets import DatasetRef
    value = yaml.safe_load((FLOWS / "rerun" / "config" / "dataset.yaml").read_text(encoding="utf-8"))["dataset"]
    ref = DatasetRef.parse(value)
    if (ref.repo, ref.version) != ("dataset-myapp-clean", "v3"):
        raise ExampleError(f"{value!r} parses as {ref}")


def packages_dockerfile(tmp: pathlib.Path) -> None:
    """The Dockerfile of the page "Add packages", in a one-step app: no error or warning of the Dockerfile rules (L-D*);
    L-D07 (the image runs as root) is an info for every Dockerfile of the template too."""
    app = tmp / "app"
    shutil.copytree(FLOWS / "metrics", app)
    (app / "steps" / "train" / "app" / "__init__.py").touch()
    shutil.copy(FLOWS / "packages" / "Dockerfile", app / "steps" / "train" / "Dockerfile")
    findings = [f for f in lint(app).findings if f.rule.startswith("L-D") and f.level != "info"]
    if findings:
        raise ExampleError(f"the Dockerfile of the page Add packages has findings: {[f.rule for f in findings]}")


def shared_reference() -> None:
    """The setting of the page "Share a dataset" holds a reference to a dataset of another project."""
    from kaos_lib.datasets import DatasetRef
    value = yaml.safe_load((FLOWS / "shared" / "config" / "dataset.yaml").read_text(encoding="utf-8"))["dataset"]
    ref = DatasetRef.parse(value)
    if (ref.owner, ref.repo, ref.version) != ("acme-vision", "dataset-cats", "v1"):
        raise ExampleError(f"{value!r} parses as {ref}")


KINDS_EXAMPLES = EXAMPLES / "kinds"
# The mistakes the step type pages show: (kind, lines of pipeline.py, the rule, the sentence `kaosctl lint` gives).
# The page of the type must hold each sentence word for word.
KIND_MISTAKES = (
    ("ingest", 'fetch = step("fetch", kind="ingest", produces=[artifact("files")])', "L-E07",
     "Step 'fetch': an ingest step brings data in, so it produces a dataset. Add produces=[dataset(\"name\")]."),
    ("transform", 'clean = step("clean", kind="transform", inputs=["dataset"])', "L-E07",
     "Step 'clean': a transform step turns data into something. Add produces=[...] with a dataset, a model or an artifact."),
    ("train", 'train = step("train", kind="train", produces=[artifact("log")])', "L-E07",
     "Step 'train': a train step produces a model. Add produces=[model(\"name\")], or give the step the kind of the "
     "work it does (ingest, transform, evaluate, publish, control)."),
    ("evaluate", 'score = step("score", kind="evaluate", produces=[dataset("scores")])', "L-E07",
     "Step 'score': an evaluate step writes reports only, so it may not produce a dataset or a model. Use "
     "kind=\"transform\" for a step that makes a dataset, kind=\"train\" for one that makes a model."),
    ("publish", 'register = step("register", kind="publish", produces=[artifact("receipt")])', "L-E07",
     "Step 'register': a publish step delivers a result and produces nothing here. Remove produces=, or give the step "
     "the kind of the work it does."),
    ("control", 'check = step("check", kind="control", inputs=["dataset"])', "L-E07",
     "Step 'check' is a control step: it steers the run and handles no data, so it takes no inputs= and no produces=."),
)


# Warnings the train page shows: (the lines of pipeline.py, the rule, the message `kaosctl lint` gives).
TRAIN_WARNINGS = (
    ('train = step("train", kind="train", walltime="12h", produces=[model("model")])', "L-W06",
     "Step 'train' is a training step with a time limit (the default on the run form) and is not resumable: a run cut by "
     "its time limit starts over. Add resumable=True and save checkpoints."),
    ('train = step("train", kind="train", gpu=True, walltime="12h", resumable=False, produces=[model("model")])', "L-W01",
     "Step 'train' has a default time limit of 12 hours and is not resumable (set not resumable). An interruption (a lost "
     "machine, the time limit) loses all its work."),
)


def _lint_text(tmp: pathlib.Path, body: str):
    """The findings for a pipeline with the line `body`, and the config and the folders a step needs."""
    app = tmp / "mistake"
    (app / "config").mkdir(parents=True)
    (app / "steps").mkdir()
    (app / "config" / "config.yaml").write_text("defaults:\n  - _self_\n  - dataset\n", encoding="utf-8")
    (app / "config" / "dataset.yaml").write_text('dataset: "dataset-default"\n', encoding="utf-8")
    (app / "pipeline.py").write_text("from kubecore.authoring import artifact, dataset, model, pipeline, step\n"
                                     "with pipeline('p') as p:\n    " + body + "\n", encoding="utf-8")
    complete(app)
    return lint(app).findings


def _kind_app(kind: str, tmp: pathlib.Path) -> pathlib.Path:
    """The example app `kinds/<kind>` with an image file for every step; it must lint without an error."""
    app = tmp / "app"
    shutil.copytree(KINDS_EXAMPLES / kind, app)
    complete(app)
    report = lint(app)
    if report.errors:
        raise ExampleError(f"kaosctl lint finds errors in kinds/{kind}:\n{report.to_json()}")
    return app


def kind_examples(tmp: pathlib.Path) -> None:
    """The minimal example of each step type: it lints without an error and its steps run. Ingest, publish and
    control use the apps of docs/examples/flows, which the pages of the guide that need them show too."""
    for number, flow in enumerate((flow_ingest, flow_publish, flow_control)):
        flow(tmp / f"flow{number}")
    from kaos_lib import checkpoint
    data = _tree(tmp / "data", **{"a.txt": "alpha\n", "empty.txt": ""})
    app = _kind_app("transform", tmp / "transform")
    result, run = run_step(app, tmp / "transform" / "run", "filter", "transform", [("dataset", "filtered")],
                           params={"filter": {"min_bytes": 1}}, inputs={"dataset": data})
    if result["values"] != {"kept": 1} or [p.name for p in run.output("filtered").iterdir()] != ["a.txt"]:
        raise ExampleError(f"filter handed on {result['values']}")
    app = _kind_app("train", tmp / "train")
    saved = os.environ.get(checkpoint.CHECKPOINT_DIR_ENV)
    os.environ[checkpoint.CHECKPOINT_DIR_ENV] = str(tmp / "train" / "checkpoints")
    try:
        result, run = run_step(app, tmp / "train" / "run", "train", "train", [("model", "model")],
                               params={"train": {"epochs": 3}}, inputs={"dataset": data})
    finally:
        if saved is None:
            os.environ.pop(checkpoint.CHECKPOINT_DIR_ENV, None)
        else:
            os.environ[checkpoint.CHECKPOINT_DIR_ENV] = saved
    if result["values"] != {"epochs": 3} or (run.output("model") / "weights.txt").read_text() != "trained for 3 epochs\n":
        raise ExampleError(f"train handed on {result['values']}")
    app = _kind_app("evaluate", tmp / "evaluate")
    trained, trun = run_step(app, tmp / "evaluate" / "train", "train", "train", [("model", "model")])
    result, run = run_step(app, tmp / "evaluate" / "run", "evaluate", "evaluate", [("artifact", "report")],
                           params={"evaluate": {"threshold": 0.5}}, upstream={"train": trained["values"]},
                           upstream_writes={"train": {"model": trun.output("model")}})
    if result["values"] != {"score": 0.8, "passed": True} or result["writes"][0]["type"] != "artifact":
        raise ExampleError(f"evaluate handed on {result}")


def kind_mistakes(tmp: pathlib.Path) -> None:
    """Each mistake of KIND_MISTAKES is an error of its rule with the sentence that the page of its type shows."""
    for number, (kind, body, rule, sentence) in enumerate(KIND_MISTAKES):
        found = [f for f in _lint_text(tmp / str(number), body) if f.rule == rule and sentence in f.message]
        if not found or found[0].level != "error":
            raise ExampleError(f"the {kind} mistake is not an error {rule} with the sentence on its page: {sentence!r}")
        page = (HERE / "docs" / f"step-type-{kind}.md").read_text(encoding="utf-8")
        if sentence not in page:
            raise ExampleError(f"docs/step-type-{kind}.md does not show the sentence of kaosctl lint: {sentence!r}")
    train = (HERE / "docs" / "step-type-train.md").read_text(encoding="utf-8")
    for number, (body, rule, sentence) in enumerate(TRAIN_WARNINGS):
        found = [f for f in _lint_text(tmp / f"warning{number}", body) if f.rule == rule and sentence in f.message]
        if not found:
            raise ExampleError(f"the train warning is not {rule} with the sentence on its page: {sentence!r}")
        if sentence not in train:
            raise ExampleError(f"docs/step-type-train.md does not show the sentence of kaosctl lint: {sentence!r}")


def flow_gpus(tmp: pathlib.Path) -> None:
    """The step of the page "GPUs on HPC (Slurm)": the app lints, and the sizes it picks follow the count it is told
    (torch is the step's own package, so the decision is a function the test calls without it)."""
    app = flow_app("gpus", tmp)
    step_module = load(app, "train")
    one, four = step_module.plan(1, 8, 64), step_module.plan(4, 32, 64)
    if one != {"gpus": 1, "batch": 64, "workers": 8, "parallel": False} or \
            four != {"gpus": 4, "batch": 256, "workers": 32, "parallel": True}:
        raise ExampleError(f"the step of flows/gpus plans {one} and {four}")
    from kaos_lib import runtime
    shared = runtime.context({"KUBECORE_SLOT_GPUS": "1", "KUBECORE_SLOT_CPUS": "8", "KUBECORE_SLOT_SHARED": "1"}).slot
    alone = runtime.context({"KUBECORE_SLOT_GPUS": "4"}).slot
    if (shared.gpus, shared.shared, alone.gpus, alone.shared) != (1, True, 4, False):
        raise ExampleError(f"the slot of a shared step and of a step alone: {shared} {alone}")


def check_all() -> None:
    """Every example: raises ExampleError (or the error of the step) on the first one that is wrong."""
    for state in STATES:
        with tempfile.TemporaryDirectory() as tmp:
            walk = Walk(state, pathlib.Path(tmp))
            report = lint(walk.app)
            if report.errors:
                raise ExampleError(f"kaosctl lint finds errors in the state {state!r} of the example app:\n"
                                   f"{report.to_json()}")
            walk.prepare()
            walk.hello_world()
            if walk.has("long-job"):
                ended = None
                try:
                    walk.train(stop_after=2)
                except SystemExit as exc:
                    ended = exc.code
                if ended != 85:
                    raise ExampleError(f"train asked to stop ended with {ended!r}, not exit code 85")
                result = walk.train()
                if result["values"] != {"epochs": 5}:
                    raise ExampleError(f"train handed on {result['values']}")
                if (walk.outputs["train"]["model"] / "weights.txt").read_text(encoding="utf-8") != "60\n":
                    raise ExampleError("train did not count five epochs of the 12 bytes of clean across the stop")
    with tempfile.TemporaryDirectory() as tmp:
        Walk("template", pathlib.Path(tmp)).second()
    with tempfile.TemporaryDirectory() as tmp:
        ledger_example(pathlib.Path(tmp))
    for flow in (flow_two_inputs, flow_skip, flow_fan_in, flow_metrics, flow_ingest, flow_publish, flow_control,
                 flow_conditions, flow_sweep, flow_gpus, packages_dockerfile):
        with tempfile.TemporaryDirectory() as tmp:
            flow(pathlib.Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        kind_examples(pathlib.Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        kind_mistakes(pathlib.Path(tmp))
    shared_reference()
    rerun_pin()
    for path in sorted(EXAMPLES.rglob("*.py")):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    for path in sorted(EXAMPLES.rglob("*.yaml")):
        yaml.safe_load(path.read_text(encoding="utf-8"))
    page = (HERE / "docs" / "flow-datasets.md").read_text(encoding="utf-8")
    if "promote-clean" not in page or "plan:" in page:
        raise ExampleError("flow-datasets.md does not name the run-form field `promote-clean`, or still shows `plan:`")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE / "src"))
    check_all()
    print(f"docs examples: {len(STATES)} states of the first app, the second pipeline and the yolo pipeline file are right")
