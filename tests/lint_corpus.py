"""The fixture corpus of the pipeline linter: for every rule one repository that must trigger it and a clean twin.

Repositories are written to disk by `write_repo` (a dict of relative path -> text), so a case reads as the files it
is, and a reviewer sees the construct each rule is about. Line numbers in EXPECT are those of the generated
pipeline.py (`pipeline(...)` is line 3, the first step line 4).
"""
from __future__ import annotations

import pathlib

from kaos_lib.lint import Catalogue, default_catalogue

HEADER = "from kubecore.authoring import pipeline, step\n\nwith pipeline(\"p\") as p:\n"

START = "from kaos_lib import step\n\ndef main():\n    step.start()\n"
CHECKPOINT_STEP = "from kaos_lib import checkpoint\nimport mlflow\n" + START + "    checkpoint.save({}, 'x')\n    mlflow.log_metric('m', 1)\n    step.result()\n"
PLAIN_STEP = START + "    print('work')\n    step.result()\n"
MLFLOW_STEP = "import mlflow\n" + START + "    mlflow.log_metric('m', 1)\n    mlflow.register_model('runs:/x/model', 'm')\n    step.result()\n"
OLD_STEP = ("import argparse, os\n\ndef main():\n    p = argparse.ArgumentParser()\n    p.add_argument('--params')\n"
            "    run = os.environ.get('KUBECORE_RUN_ID')\n")

CONFIG = {
    "config/config.yaml": "defaults:\n  - experiment\n  - dataset\n  - train\n",
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
    return Catalogue(d.source, tuple(names))


# rule -> (failing repository, clean twin, catalogue or None for the default, expected (line, substring) of the finding)
CASES = {
    "L-E03": (
        repo('    c = Container(name="c", annotations={"platform.kubecore.io/compute-class": "gpu-xx"})\n'),
        repo('    c = Container(name="c", annotations={"platform.kubecore.io/compute-class": "gpu-a"})\n'),
        with_classes("gpu-a", "cpu-a"), (4, "gpu-xx")),
    "L-E04": (
        repo('    c = Container(name="c", service_account_name="admin")\n'),
        repo('    c = Container(name="c")\n'),
        None, (4, "service account")),
    "L-E05": (
        repo('    a = step("a", kind="evaluate", needs=[b])\n    b = step("b", kind="evaluate")\n'),
        repo('    b = step("b", kind="evaluate")\n    a = step("a", kind="evaluate", needs=[b])\n'),
        None, (4, "defined after it")),
    "L-E06": (
        repo('    a = step("a", kind="evaluate", walltime="12h")\n'),
        repo('    a = step("a", kind="evaluate")\n'),
        None, (4, "walltime= is gone")),
    "L-E07": (
        repo('    a = step("a", reads=["dataset"])\n'),
        repo('    a = step("a", kind="transform", reads=["dataset"], inputs=["dataset"], produces=[dataset("clean")])\n'),
        None, (4, "has no kind=")),
    "L-E08": (
        repo('    a = step("a", kind="evaluate")\n', {"a": OLD_STEP}),
        repo('    a = step("a", kind="evaluate")\n', {"a": PLAIN_STEP}),
        None, (5, "takes --params")),
    "L-E09": (
        repo('    a = step("a", kind="evaluate")\n',
             config={**CONFIG, "config/config.yaml": "defaults:\n  - experiment\n  - platform: live\n"}),
        repo('    a = step("a", kind="evaluate")\n'),
        None, (3, "names the `platform` config group")),
    "L-W07": (
        repo('    t = step("embed", kind="transform", gpu=True, produces=[dataset("embeddings")])\n', {"embed": PLAIN_STEP}),
        repo('    t = step("embed", kind="transform", gpu=True, produces=[artifact("vectors")])\n', {"embed": PLAIN_STEP}),
        None, (4, "produces a dataset")),
    "L-W08": (
        repo('    t = step("train", kind="train", matrix={"lr": [0.01, 0.001]}, matrix_allow_failed=True, produces=[model("m")])\n'
             '    s = step("scores", kind="evaluate", needs=[t], produces=[dataset("scores")])\n', {"train": PLAIN_STEP, "scores": PLAIN_STEP}),
        repo('    t = step("train", kind="train", matrix={"lr": [0.01, 0.001]}, produces=[model("m")])\n'
             '    s = step("scores", kind="evaluate", needs=[t], produces=[dataset("scores")])\n', {"train": PLAIN_STEP, "scores": PLAIN_STEP}),
        None, (4, "a step after it writes a dataset")),
    "L-I04": (
        repo('    for i in range(2):\n        step(f"trial-{i}", kind="evaluate")\n'),
        repo('    t = step("trial", kind="evaluate")\n'),
        None, (5, "built in a loop")),
    "L-W02": (
        repo('    t = step("work", kind="evaluate", gpu=True, idle_timeout=0)\n'),
        repo('    t = step("work", kind="evaluate", gpu=True, idle_timeout="40m")\n'),
        None, (4, "idle limit")),
    "L-W03": (
        repo('    a = step("a", kind="evaluate")\n', {"a": PLAIN_STEP + "REF = 'dataset-default@latest'\n"}),
        repo('    a = step("a", kind="evaluate")\n', {"a": PLAIN_STEP}),
        None, (7, "names a dataset and a version")),
    "L-W04": (
        repo('    t = step("train-x", kind="evaluate", gpu=True, reads=["train"])\n', {"train-x": PLAIN_STEP}),
        repo('    t = step("train-x", kind="evaluate", gpu=True, reads=["train"])\n', {"train-x": MLFLOW_STEP}),
        None, (4, "no MLflow")),
}
