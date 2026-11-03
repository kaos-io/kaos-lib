"""kaos_lib.runtime: the step context from the injected environment; missing values are None, never a crash."""
import dataclasses
import json

import pytest

from kaos_lib import __version__, runtime

FULL = {
    "KUBECORE_RUN_ID": "yolo-run-7x2k",
    "KUBECORE_WORKFLOW_NAME": "yolo-run-7x2k",
    "KUBECORE_APP": "yolo",
    "KUBECORE_PROJECT": "vision",
    "KUBECORE_STEP": "model-training",
    "OUTPUTS_REPO": "outputs-yolo",
    "LAKEFS_ENDPOINT": "http://vision-lakefs.ml-vision.svc:8000",
    "MLFLOW_TRACKING_URI": "http://vision-mlflow.ml-vision.svc:5000",
    "KUBECORE_DATASET_REF": "dataset-default@v2",
    "KUBECORE_DATASET_COMMIT": "c0001abcdef",
    "KAOS_LIB_SUPPORT": json.dumps({"version": __version__, "supported": ">=0.2", "deprecated": [],
                                    "breaking": False, "migration": ""}),
}


def test_full_environment():
    ctx = runtime.context(FULL)
    assert ctx == runtime.Context(
        run_id="yolo-run-7x2k", workflow="yolo-run-7x2k", app="yolo", project="vision", step="model-training",
        outputs_repo="outputs-yolo", lakefs_endpoint="http://vision-lakefs.ml-vision.svc:8000",
        mlflow_uri="http://vision-mlflow.ml-vision.svc:5000", dataset_ref="dataset-default@v2",
        dataset_commit="c0001abcdef", support="current")


def test_empty_environment_is_all_none():
    ctx = runtime.context({})
    assert all(getattr(ctx, f.name) is None for f in dataclasses.fields(ctx))
    assert runtime.run_id({}) is None


def test_what_the_enhancer_injects_today():
    """In-cluster steps get the run, workflow, outputs repository and endpoints; the app follows from outputs-<app>."""
    ctx = runtime.context({"KUBECORE_RUN_ID": "r1", "KUBECORE_WORKFLOW_NAME": "r1", "CHECKPOINT_BUCKET": "outputs-yolo",
                           "CHECKPOINT_PREFIX": "main/checkpoints", "LAKEFS_ENDPOINT": "http://l",
                           "MLFLOW_TRACKING_URI": "http://m"})
    assert (ctx.run_id, ctx.workflow, ctx.outputs_repo, ctx.app) == ("r1", "r1", "outputs-yolo", "yolo")
    assert (ctx.project, ctx.step, ctx.dataset_ref, ctx.dataset_commit, ctx.support) == (None,) * 5


def test_slurm_job_names():
    ctx = runtime.context({"STEP_NAME": "model-training", "DATASET_REPO": "dataset-default", "DATASET_REF": "v3",
                           "DATASET_COMMIT": "c9", "OUTPUTS_REPO": "outputs-yolo", "LAKEFS_URL": "https://lakefs-b"})
    assert (ctx.step, ctx.dataset_ref, ctx.dataset_commit) == ("model-training", "dataset-default@v3", "c9")
    assert ctx.lakefs_endpoint == "https://lakefs-b"


def test_first_non_empty_name_wins():
    ctx = runtime.context({"OUTPUTS_REPO": "outputs-a", "CHECKPOINT_BUCKET": "outputs-b", "KUBECORE_STEP": " ",
                           "STEP_NAME": "train", "KUBECORE_DATASET_REF": "", "DATASET": "dataset-x@latest",
                           "DATASET_REPO": "dataset-y", "DATASET_REF": "v1"})
    assert (ctx.outputs_repo, ctx.app, ctx.step, ctx.dataset_ref) == ("outputs-a", "a", "train", "dataset-x@latest")


def test_explicit_app_wins_and_odd_outputs_names_give_no_app():
    assert runtime.context({"KUBECORE_APP": "x", "OUTPUTS_REPO": "outputs-y"}).app == "x"
    assert runtime.context({"OUTPUTS_REPO": "results"}).app is None
    assert runtime.context({"OUTPUTS_REPO": "outputs-"}).app is None


@pytest.mark.parametrize("raw,verdict", [
    (json.dumps({"version": "99.0.0", "supported": ">=0.1", "deprecated": [], "breaking": False, "migration": ""}),
     "behind"),
    ("not json", "unknown"),
])
def test_support_verdict(raw, verdict):
    assert runtime.context({"KAOS_LIB_SUPPORT": raw}).support == verdict


def test_reads_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("KUBECORE_RUN_ID", "from-env")
    assert runtime.context().run_id == runtime.run_id() == "from-env"


def test_context_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        runtime.context({}).run_id = "x"


# ── PRD-HPC-1609: a step's slot on a shared Slurm node ──────────────────────────────────────

def test_no_slot_outside_a_shared_node():
    assert runtime.context({}).slot is None
    assert runtime.context({"KUBECORE_SLOT_SHARED": "1"}).slot is None, "no share without numbers"


def test_the_slot_the_runner_set():
    env = {"KUBECORE_SLOT_GPUS": "1", "KUBECORE_SLOT_CPUS": "32", "KUBECORE_SLOT_MEM_GIB": "120",
           "KUBECORE_SLOT_SHARED": "1"}
    assert runtime.context(env).slot == runtime.Slot(gpus=1, cpus=32, mem_gib=120, shared=True)


def test_a_malformed_slot_value_is_absent_not_an_error():
    slot = runtime.context({"KUBECORE_SLOT_CPUS": "lots", "KUBECORE_SLOT_GPUS": "1"}).slot
    assert slot.cpus is None and slot.gpus == 1


def test_usable_cpus_prefers_the_slot_then_the_binding():
    assert runtime.usable_cpus({"KUBECORE_SLOT_CPUS": "32"}) == 32
    import os
    bound = len(os.sched_getaffinity(0))
    assert runtime.usable_cpus({}) == bound, "the scheduler's CPU binding, never the whole machine"
    assert runtime.usable_cpus({}) >= 1
