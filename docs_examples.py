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
# The folders of FIRST in the order the pages lay them over the template.
STATES = ("template", "first-step", "settings", "read-data", "pass-on", "produce", "gpu", "long-job", "hpc", "try-locally")
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
    for path in sorted(EXAMPLES.rglob("*.py")):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    for path in sorted(EXAMPLES.rglob("*.yaml")):
        yaml.safe_load(path.read_text(encoding="utf-8"))
    promote = yaml.safe_load((FIRST / "produce" / "runs" / "promote.yaml").read_text(encoding="utf-8"))
    if promote != {"plan": {"promote": {"clean": True}}}:
        raise ExampleError("runs/promote.yaml is not the run's request to move the newest version of `clean`")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE / "src"))
    check_all()
    print(f"docs examples: {len(STATES)} states of the first app, the second pipeline and the yolo pipeline file are right")
