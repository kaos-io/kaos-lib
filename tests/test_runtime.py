"""kaos_lib.runtime: where the step runs, from the step context and the environment; missing values are None."""
import dataclasses
import json
import pathlib

import pytest

from kaos_lib import __version__, runtime

FIXTURES = pathlib.Path(__file__).with_name("contract_fixtures")
STEP = (FIXTURES / "context-one-upstream.wire").read_text()
FULL = {
    "KAOS_STEP_CONTEXT": STEP,
    "LAKEFS_ENDPOINT": "http://lakefs.example:8000",
    "MLFLOW_TRACKING_URI": "http://mlflow.example:5000",
    "KAOS_LIB_SUPPORT": json.dumps({"version": __version__, "supported": ">=0.2", "deprecated": [],
                                    "breaking": False, "migration": ""}),
}


def test_full_environment():
    ctx = runtime.context(FULL)
    assert ctx == runtime.Context(
        run_id="hera-demo-x7k2p", app="hera-demo", project="vision", step="train", kind="train",
        experiment="baseline", lakefs_endpoint="http://lakefs.example:8000",
        mlflow_uri="http://mlflow.example:5000", support="current")
    assert ctx.outputs_repo == "outputs-hera-demo"
    assert runtime.in_step(FULL) and not runtime.in_step({})


def test_empty_environment_is_all_none():
    ctx = runtime.context({})
    assert all(getattr(ctx, f.name) is None for f in dataclasses.fields(ctx))
    assert runtime.run_id({}) is None and ctx.outputs_repo is None


@pytest.mark.parametrize("raw", ["{oops", "[1]", '{"run": 7, "app": ""}'])
def test_a_context_that_cannot_be_read_gives_none_and_never_raises(raw):
    ctx = runtime.context({"KAOS_STEP_CONTEXT": raw})
    assert (ctx.run_id, ctx.app, ctx.step) == (None, None, None)


def test_the_old_variables_are_not_read():
    ctx = runtime.context({"KUBECORE_RUN_ID": "r1", "KUBECORE_APP": "x", "STEP_NAME": "train",
                           "OUTPUTS_REPO": "outputs-y", "CHECKPOINT_BUCKET": "outputs-z", "DATASET": "dataset-x@v1"})
    assert (ctx.run_id, ctx.app, ctx.step, ctx.outputs_repo) == (None,) * 4
    assert not hasattr(ctx, "dataset_ref") and not hasattr(ctx, "dataset_commit") and not hasattr(ctx, "workflow")


def test_lakefs_url_is_the_second_name():
    assert runtime.context({"LAKEFS_URL": "https://lakefs-b"}).lakefs_endpoint == "https://lakefs-b"
    assert runtime.context({"LAKEFS_ENDPOINT": "http://a", "LAKEFS_URL": "https://b"}).lakefs_endpoint == "http://a"


@pytest.mark.parametrize("raw,verdict", [
    (json.dumps({"version": "99.0.0", "supported": ">=0.1", "deprecated": [], "breaking": False, "migration": ""}),
     "behind"),
    ("not json", "unknown"),
])
def test_support_verdict(raw, verdict):
    assert runtime.context({"KAOS_LIB_SUPPORT": raw}).support == verdict


def test_reads_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("KAOS_STEP_CONTEXT", STEP)
    assert runtime.context().run_id == runtime.run_id() == "hera-demo-x7k2p"


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
