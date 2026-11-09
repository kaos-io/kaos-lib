"""The fixture corpus of the pipeline linter: for every rule one repository that must trigger it and a clean twin.

Repositories are written to disk by `write_repo` (a dict of relative path -> text), so a case reads as the files it
is, and a reviewer sees the construct each rule is about. Line numbers in EXPECT are those of the generated
pipeline.py (`pipeline(...)` is line 3, the first step line 4).
"""
from __future__ import annotations

import pathlib

from kaos_lib.lint import Catalogue, default_catalogue
from kaos_lib.lint.catalogue import HpcFacts

HEADER = "from kubecore.authoring import pipeline, step\n\nwith pipeline(\"p\") as p:\n"

CHECKPOINT_STEP = "from kaos_lib import checkpoint\nimport mlflow\n\ndef main():\n    checkpoint.save({}, 'x')\n    mlflow.log_metric('m', 1)\n"
PLAIN_STEP = "def main():\n    print('work')\n"
MLFLOW_STEP = "import mlflow\n\ndef main():\n    mlflow.log_metric('m', 1)\n    mlflow.register_model('runs:/x/model', 'm')\n"

CONFIG = {
    "config/config.yaml": "defaults:\n  - experiment\n  - dataset\n  - train\n  - platform: live\n",
    "config/experiment.yaml": "experiment:\n  name: demo\n",
    "config/dataset.yaml": "dataset: \"dataset-default@v1\"\n",
    "config/train.yaml": "train:\n  epochs: 3\n",
}


def repo(body: str, steps: dict = None, config: dict = None, extra: dict = None) -> dict:
    """A repository: pipeline.py is HEADER + body (indented by the caller), the default config tree and step folders."""
    files = {"pipeline.py": HEADER + body}
    files.update(CONFIG if config is None else config)
    for name, code in (steps or {}).items():
        files[f"steps/{name.replace('-', '_')}/app/entry.py"] = code
    files.update(extra or {})
    return files


def write_repo(root: pathlib.Path, files: dict) -> pathlib.Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def with_classes(*names: str) -> Catalogue:
    """The default catalogue plus a list of compute classes."""
    d = default_catalogue()
    return Catalogue(d.source, tuple(names), d.hpc, d.max_continuations)


def with_lane(minutes: int, cap: int = 5) -> Catalogue:
    return Catalogue("catalogue file", None, HpcFacts(minutes), cap)


# rule -> (failing repository, clean twin, catalogue or None for the default, expected (line, substring) of the finding)
CASES = {
    "L-E01": (
        repo('    t = step("train-x", gpu=True, hpc_time_limit="72h", reads=["train"])\n', {"train-x": PLAIN_STEP}),
        repo('    t = step("train-x", gpu=True, hpc_time_limit="24h", reads=["train"])\n', {"train-x": PLAIN_STEP}),
        None, (4, "3 days")),
    "L-E02": (
        repo('    t = step("train-x", gpu=True, hpc_time_limit="400h", resumable=True, reads=["train"])\n',
             {"train-x": CHECKPOINT_STEP}),
        repo('    t = step("train-x", gpu=True, hpc_time_limit="100h", resumable=True, reads=["train"])\n',
             {"train-x": CHECKPOINT_STEP}),
        None, (4, "9 runs")),
    "L-E03": (
        repo('    c = Container(name="c", annotations={"platform.kubecore.io/compute-class": "gpu-xx"})\n'),
        repo('    c = Container(name="c", annotations={"platform.kubecore.io/compute-class": "gpu-a"})\n'),
        with_classes("gpu-a", "cpu-a"), (4, "gpu-xx")),
    "L-E04": (
        repo('    c = Container(name="c", service_account_name="admin")\n'),
        repo('    c = Container(name="c")\n'),
        None, (4, "service account")),
    "L-E05": (
        repo('    a = step("a", needs=[b])\n    b = step("b")\n'),
        repo('    b = step("b")\n    a = step("a", needs=[b])\n'),
        None, (4, "defined after it")),
    "L-E06": (
        repo('    a = step("a", disk="20 GB")\n'),
        repo('    a = step("a", disk="20Gi")\n'),
        None, (4, "disk=")),
    "L-W01": (
        repo('    t = step("work", gpu=True, hpc_time_limit="6h")\n', {"work": PLAIN_STEP}),
        repo('    t = step("work", gpu=True, hpc_time_limit="6h", resumable=True)\n', {"work": PLAIN_STEP}),
        None, (4, "6 hours")),
    "L-W02": (
        repo('    t = step("work", gpu=True, idle_timeout=0)\n'),
        repo('    t = step("work", gpu=True, idle_timeout="40m")\n'),
        None, (4, "idle limit")),
    "L-W03": (
        repo('    a = step("a", reads=["dataset"])\n',
             config={**CONFIG, "config/dataset.yaml": "dataset: \"dataset-default@latest\"\n"}),
        repo('    a = step("a", reads=["dataset"])\n'),
        None, (1, "newest data")),
    "L-W04": (
        repo('    t = step("train-x", gpu=True, reads=["train"])\n', {"train-x": PLAIN_STEP}),
        repo('    t = step("train-x", gpu=True, reads=["train"])\n', {"train-x": MLFLOW_STEP}),
        None, (4, "no MLflow")),
    "L-I01": (
        repo('    t = step("work", gpu=True)\n'),
        repo('    t = step("work", gpu=True, hpc_time_limit="4h")\n'),
        None, (4, "no time limit")),
    "L-I02": (
        repo('    t = step("work", gpu=True, hpc_time_limit="90m")\n'),
        repo('    t = step("work", gpu=True, hpc_time_limit="3h")\n'),
        None, (4, "90 minutes")),
}
