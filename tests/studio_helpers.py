"""Shared builders for the studio tests: template-shaped repositories and a stub engine behind `proc.run`."""
from __future__ import annotations

import json
import os
import pathlib
import sys

from kaos_lib.studio import proc, pyenv

PIPELINE = '''from kubecore.authoring import artifact, dataset, model, pipeline, step

with pipeline("ml-pipeline") as p:
    load = step("dataset-loading", kind="transform", reads=["dataset"], inputs=["dataset"], produces=[dataset("clean")])
    summary = step("data-summary", kind="evaluate", reads=["data", "summary"], needs=[load],
                   produces=[artifact("summary")])
    train = step("model-training", kind="train", gpu=True, needs=[load], reads=["train"], produces=[model("model")])
'''
DOCKER_PLAIN = ('FROM python:3.11-slim\nWORKDIR /app\nRUN pip install --no-cache-dir PyYAML\nCOPY app/ ./app/\n'
                'ENTRYPOINT ["python", "-m", "app.entry"]\n')
DOCKER_LIB = ('FROM python:3.11-slim\nWORKDIR /app\nARG KAOS_LIB_PACKAGE="kaos-lib[zitadel]==0.4.0rc20"\n'
              'RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"\nCOPY app/ ./app/\n'
              'ENTRYPOINT ["python", "-m", "app.entry"]\n')
DOCKER_SUMMARY = DOCKER_LIB.replace('RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"',
                                    'RUN pip install --no-cache-dir PyYAML "${KAOS_LIB_PACKAGE}"')
DOCKER_POETRY = ('FROM python:3.12-slim\nWORKDIR /app\nRUN python -m venv /opt/poetry && /opt/poetry/bin/pip install --no-cache-dir poetry\n'
                 'COPY pyproject.toml poetry.lock* ./\nRUN /opt/poetry/bin/poetry export --only=main -f requirements.txt --output /tmp/r.txt '
                 '&& pip install --no-cache-dir -r /tmp/r.txt\nCOPY app/ ./app/\nENTRYPOINT ["python", "-m", "app.entry"]\n')
SUMMARY_ENTRY = '''"""data-summary: prints a one-line summary of the config and of what dataset-loading handed on."""
import json

from kaos_lib import step


def main():
    ctx = step.start()
    cfg = ctx.params
    load = step.upstream("dataset-loading", optional=True)
    print(f"{cfg['summary']['label']}: seed={cfg['data']['seed']} info={load.values if load else None}")
    (step.output("summary") / "summary.json").write_text(json.dumps({"seed": cfg["data"]["seed"]}))
    step.result(seed=cfg["data"]["seed"])


if __name__ == "__main__":
    main()
'''
LOADING_ENTRY = '''"""dataset-loading: copies its input into the dataset it produces and hands the file count on."""
import shutil

from kaos_lib import step


def main():
    step.start()
    data = step.input("dataset")
    files = [p for p in data.rglob("*") if p.is_file() and not p.name.startswith(".")]
    out = step.output("clean")
    for f in files:
        shutil.copy(f, out / f.name)
    print("loading", len(files), "files")
    step.result(files=len(files))


if __name__ == "__main__":
    main()
'''
COMPOSE = '''"""A stand-in for the platform's kubecore.compose: writes the composed params the steps receive."""
import argparse
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
parser.add_argument("overrides", nargs="*")
args = parser.parse_args()
text = "summary:\\n  label: Data summary\\ndata:\\n  seed: 42\\ndataset: dataset-default@v1\\n"
for token in args.overrides:
    text += token.replace("=", ": ", 1) + "\\n"
open(args.output, "w").write(text)
print("wrote", args.output)
'''
COMPOSE_DOCKER = ('FROM python:3.11-slim\nRUN pip install --no-cache-dir "PyYAML>=6,<7"\nCOPY kubecore/ ./kubecore/\n'
                  'ENTRYPOINT ["python", "-m", "kubecore.compose"]\n')


def write(root: pathlib.Path, files: dict) -> pathlib.Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def template_repo(root: pathlib.Path, extra: dict = None) -> pathlib.Path:
    """A repository shaped like the yolo and hera templates: data-summary needs only PyYAML, dataset-loading uses
    kaos-lib, model-training is a poetry step with a lock file, and compose-and-validate builds with the repo root."""
    files = {
        "pipeline.py": PIPELINE,
        "kubecore/__init__.py": "", "kubecore/compose.py": COMPOSE,
        "steps/compose_and_validate/Dockerfile": COMPOSE_DOCKER,
        "steps/dataset_loading/Dockerfile": DOCKER_LIB,
        "steps/dataset_loading/app/__init__.py": "",
        "steps/dataset_loading/app/entry.py": LOADING_ENTRY,
        "steps/data_summary/Dockerfile": DOCKER_SUMMARY,
        "steps/data_summary/app/__init__.py": "", "steps/data_summary/app/entry.py": SUMMARY_ENTRY,
        "steps/model_training/Dockerfile": DOCKER_POETRY,
        "steps/model_training/app/__init__.py": "", "steps/model_training/app/entry.py": "import torch\n",
        "steps/model_training/pyproject.toml": '[tool.poetry.dependencies]\npython = "^3.12"\ntorch = "^2.3"\nPyYAML = "^6.0"\n',
        "steps/model_training/poetry.lock": '[[package]]\nname = "torch"\nversion = "2.3.1"\ngroups = ["main"]\n\n'
                                           '[[package]]\nname = "pytest"\nversion = "8.0.0"\ngroups = ["dev"]\n',
    }
    files.update(extra or {})
    return write(root, files)


def fake_venv(step_dir: pathlib.Path) -> None:
    """Make `<step>/.venv/bin/python` run the Python that runs the tests, so a step 'runs in its environment' offline."""
    venv = pyenv.step_env(step_dir)
    py = pyenv.venv_python(venv)
    py.parent.mkdir(parents=True, exist_ok=True)
    if not py.exists():       # a wrapper, not a symlink: a symlinked interpreter loses its own site-packages
        py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        py.chmod(0o755)
    (venv / "pyvenv.cfg").write_text("home = test\n")


class StubEngine:
    """A stand-in for `proc.run` and `proc.stream` that answers like a container engine from recorded outputs.

    `answers` maps a command prefix (a tuple of words after the executable) to (returncode, text). Every call is kept
    in `calls`, so a test can assert what was started."""

    def __init__(self, answers: dict = None, default=(0, "")):
        self.answers, self.default, self.calls = answers or {}, default, []

    def _answer(self, argv):
        words = tuple(str(a) for a in argv[1:])
        for prefix, result in sorted(self.answers.items(), key=lambda kv: -len(kv[0])):
            if words[:len(prefix)] == prefix:
                return result
        return self.default

    def run(self, argv, env=None, cwd=None, timeout=None):
        self.calls.append([str(a) for a in argv])
        code, text = self._answer(argv)
        return proc.Result(code, text, "")

    def stream(self, argv, env=None, cwd=None, echo=print, tail=40):
        self.calls.append([str(a) for a in argv])
        code, text = self._answer(argv)
        for line in text.splitlines():
            echo(line)
        return proc.Result(code, text, "")


DOCKER_INFO = json.dumps({"ServerVersion": "27.1.1", "Architecture": "x86_64", "OperatingSystem": "Fedora Linux 44",
                          "Name": "dev", "DockerRootDir": "/"})
PODMAN_INFO = json.dumps({"host": {"arch": "amd64", "os": "linux"}, "version": {"Version": "5.8.4"},
                          "store": {"graphRoot": "/"}})


class VenvStub:
    """A stand-in for `proc.run` that behaves like `uv` / `python -m venv` / pip: it makes the environment's files and
    records every command, so `kaosctl dev` can be tested without a network or a package index."""

    def __init__(self, minor: str = "3.11"):
        self.calls, self.minor = [], minor

    def __call__(self, argv, env=None, cwd=None, timeout=None):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        joined = " ".join(argv)
        if "sys.version_info" in joined:
            return proc.Result(0, f"{self.minor}.9\n")
        if "python" in argv and "find" in argv:
            return proc.Result(1, "", "no interpreter found")
        if "venv" in argv:
            venv = pathlib.Path(argv[-1])
            py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("")
            (venv / "pyvenv.cfg").write_text("home = stub\n")
        return proc.Result(0)

    def installs(self):
        return [c for c in self.calls if "install" in c]
