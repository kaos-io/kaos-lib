"""The resumability judgement rests on evidence (PRD-CONSOLE-1682): the platform's record per step, the step's own
code, or nothing; with nothing the not-resumable rules stay silent. The gate and `kaosctl lint --context` print the same
bytes for the same evidence."""
import json

import pytest
import yaml

from kaos_lib.lint import from_context, lint_project
from kaos_lib.lint.catalogue import CatalogueError, from_dict
from lint_corpus import CHECKPOINT_STEP, NO_PROGRESS, PLAIN_STEP, repo, with_evidence, write_repo
from test_lint_cli import gate, kaosctl

LONG = '    t = step("work", gpu=True, hpc_time_limit="72h")\n'
SIX = '    t = step("work", gpu=True, hpc_time_limit="6h")\n'
DECLARED = '    t = step("work", gpu=True, hpc_time_limit="72h", resumable=True)\n'


def rules(tmp_path, body, steps, catalogue=None):
    report = lint_project(write_repo(tmp_path, repo(body, steps)), catalogue)
    return sorted(f.rule for f in report.findings if f.rule in ("L-E01", "L-E02", "L-W01", "L-W05"))


def test_should_count_a_step_the_platform_verified_as_resumable(tmp_path):
    assert rules(tmp_path, LONG, {"work": PLAIN_STEP}, with_evidence(("work", True))) == []


def test_should_count_a_step_whose_code_uses_checkpoints_as_resumable(tmp_path):
    assert rules(tmp_path, LONG, {"work": CHECKPOINT_STEP}) == []


@pytest.mark.parametrize("code", [
    "import os\ndir = os.environ['KAOS_CHECKPOINT_DIR']\n",
    "def main():\n    state = load_state()\n",
    "def main():\n    helper.save_state(model)\n",
    "from kaos_lib import checkpoint\n",
])
def test_should_take_each_static_sign_of_checkpoint_use_as_evidence(tmp_path, code):
    assert rules(tmp_path, LONG, {"work": code}) == []


def test_should_stay_silent_when_there_is_no_evidence_at_all(tmp_path):
    assert rules(tmp_path / "a", LONG, {"work": PLAIN_STEP}) == []
    assert rules(tmp_path / "b", SIX, {"work": PLAIN_STEP}) == []
    assert rules(tmp_path / "c", LONG, {}) == []
    assert rules(tmp_path / "d", LONG, {"work": PLAIN_STEP}, with_evidence(("other", True))) == []


def test_should_report_a_step_the_platform_recorded_as_not_resumable(tmp_path):
    cat = with_evidence(("work", False, NO_PROGRESS))
    assert rules(tmp_path / "a", LONG, {"work": PLAIN_STEP}, cat) == ["L-E01"]
    assert rules(tmp_path / "b", SIX, {"work": PLAIN_STEP}, cat) == ["L-W01"]


def test_the_platforms_record_beats_what_the_code_suggests(tmp_path):
    assert rules(tmp_path, LONG, {"work": CHECKPOINT_STEP}, with_evidence(("work", False, NO_PROGRESS))) == ["L-E01"]


def test_should_warn_when_a_declared_resumable_step_did_not_resume(tmp_path):
    root = write_repo(tmp_path, repo(DECLARED, {"work": CHECKPOINT_STEP}))
    report = lint_project(root, with_evidence(("work", False, NO_PROGRESS)))
    found = [f for f in report.findings if f.rule == "L-W05"]
    assert len(found) == 1 and found[0].level == "warning"
    assert "NoProgress" in found[0].message and "2026-11-09T12:00:00Z" in found[0].message
    assert found[0].span.line == 4
    assert not [f for f in report.findings if f.rule in ("L-E01", "L-W01")]


def test_should_not_warn_when_the_declared_step_resumed_or_has_no_record(tmp_path):
    assert rules(tmp_path / "a", DECLARED, {"work": CHECKPOINT_STEP}, with_evidence(("work", True))) == []
    assert rules(tmp_path / "b", DECLARED, {"work": CHECKPOINT_STEP}) == []


def test_a_declaration_in_pipeline_py_decides_before_any_evidence(tmp_path):
    off = '    t = step("work", gpu=True, hpc_time_limit="72h", resumable=False)\n'
    assert rules(tmp_path, off, {"work": CHECKPOINT_STEP}, with_evidence(("work", True))) == ["L-E01"]


def test_the_context_carries_the_record_and_the_report_shows_it():
    cat = from_context({"hpc": {"enabled": True, "resumableSteps": [
        {"name": "b", "verified": False, "since": "2026-11-09T10:00:00Z", "reason": NO_PROGRESS},
        {"name": "a", "verified": True, "since": "2026-11-09T11:00:00Z", "reason": "ok"},
        {"name": "a", "verified": False, "since": "2026-11-09T09:00:00Z", "reason": "older"},
        {"name": 3, "verified": True}, {"verified": True}, "junk"]}})
    assert [(e.name, e.verified) for e in cat.steps] == [("a", True), ("b", False)]
    assert [e["name"] for e in cat.to_dict()["resumableSteps"]] == ["a", "b"]


def test_a_context_without_the_list_gives_no_evidence_and_a_bad_catalogue_file_is_refused():
    assert from_context({"hpc": {"enabled": True}}).steps is None
    assert from_context({"hpc": {"enabled": True, "resumableSteps": "x"}}).steps is None
    with pytest.raises(CatalogueError):
        from_dict({"resumableSteps": [{"name": "a"}]})


def test_the_platforms_reason_is_bounded():
    cat = from_context({"hpc": {"enabled": True, "resumableSteps": [{"name": "a", "verified": False,
                                                                     "reason": "x" * 5000}]}})
    assert len(cat.steps[0].reason) == 300


CONTEXT = {"computeClasses": {"all": [{"name": "gpu-a"}]},
           "hpc": {"enabled": True, "resumableSteps": [
               {"name": "work", "verified": False, "since": "2026-11-09T10:00:00Z", "reason": NO_PROGRESS}]}}


@pytest.mark.parametrize("body", [LONG, DECLARED, SIX])
def test_the_gate_and_the_local_command_give_byte_identical_json_with_evidence(tmp_path, capsys, body):
    """The gate exports the catalogue from the context and lints with that file; a laptop lints with the context."""
    root = write_repo(tmp_path / "r", repo(body, {"work": CHECKPOINT_STEP}))
    ctx = tmp_path / "ctx.yaml"
    ctx.write_text(yaml.safe_dump(CONTEXT))
    cat = tmp_path / "catalogue.json"
    assert gate(tmp_path, "--context", str(ctx), "--export-catalogue", str(cat))[0] == 0
    local = kaosctl(capsys, str(root), "--format", "json", "--context", str(ctx))
    via_gate_file = gate(tmp_path, str(root), "--format", "json", "--catalogue", str(cat))
    direct = gate(tmp_path, str(root), "--format", "json", "--context", str(ctx))
    assert local[1] == via_gate_file[1] == direct[1] and local[0] == via_gate_file[0] == direct[0]
    assert json.loads(local[1])["catalogue"]["resumableSteps"][0]["name"] == "work"
