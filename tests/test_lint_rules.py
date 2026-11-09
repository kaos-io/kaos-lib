"""Every rule of the pipeline linter fires on its own fixture and stays silent on its clean twin (PRD-CONSOLE-1682
AC-23), with the expected level, range, fix hint and a documentation page that exists."""
import pathlib

import pytest

from kaos_lib.lint import ALL_RULES, lint_project
from lint_corpus import CASES, write_repo

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "lint"
LEVELS = {"E": "error", "W": "warning", "I": "info"}


def run(tmp_path, files, catalogue):
    return lint_project(write_repo(tmp_path, files), catalogue)


@pytest.mark.parametrize("rule_id", sorted(CASES))
def test_should_fire_on_its_fixture_and_stay_silent_on_the_clean_twin(rule_id, tmp_path):
    failing, clean, catalogue, (line, text) = CASES[rule_id]
    hit = [f for f in run(tmp_path / "fail", failing, catalogue).findings if f.rule == rule_id]
    assert hit, f"{rule_id} did not fire"
    finding = hit[0]
    assert finding.level == LEVELS[rule_id[2]]
    assert finding.span.line == line and text in finding.message
    assert finding.fix and finding.doc.endswith(f"/{rule_id}.html")
    assert not [f for f in run(tmp_path / "pass", clean, catalogue).findings if f.rule == rule_id]


def test_should_report_l_i03_as_skipped_because_schedules_do_not_exist_yet(tmp_path):
    report = run(tmp_path, CASES["L-E06"][1], None)
    assert [s.rule for s in report.skipped if s.rule == "L-I03"] == ["L-I03"]
    assert not [f for f in report.findings if f.rule == "L-I03"]


def test_every_rule_has_a_documentation_page():
    for rule in ALL_RULES:
        page = DOCS / f"{rule.id}.md"
        assert page.is_file(), rule.id
        text = page.read_text()
        assert rule.name in text and rule.level in text.lower()


def test_every_rule_is_in_the_corpus_or_documented_as_inactive():
    ids = {r.id for r in ALL_RULES if not r.id.startswith("L-D")}   # the L-D rules have their own corpus
    assert ids - set(CASES) == {"L-E00", "L-I03"}


# --- the variants of the rules that have several ways to fire ------------------------------------------------

def messages(tmp_path, body, steps=None, catalogue=None, rule=None):
    from lint_corpus import repo
    report = run(tmp_path, repo(body, steps), catalogue)
    return [f.message for f in report.findings if rule is None or f.rule == rule]


@pytest.mark.parametrize("body,expect", [
    ('    a = step("a", needs=[ghost])\n', "not defined anywhere"),
    ('    a = step("a", needs=["b"])\n    b = step("b")\n', "as text"),
    ('    a = step("a")\n    b = step("a")\n', "Two steps are named 'a'"),
    ('    a = step("Bad_Name")\n', "not valid"),
    ('    a = step("a", reads=["nope"])\n', "does not exist in config/"),
    ('    a = step("a")\n    a2 = step("c", needs=[a2])\n', "defined after it"),
])
def test_should_report_each_dependency_or_producer_problem(tmp_path, body, expect):
    assert any(expect in m for m in messages(tmp_path, body, rule="L-E05")), body


def test_should_not_report_a_dependency_it_cannot_resolve_statically(tmp_path):
    body = '    a = step("a")\n    prev = [a]\n    b = step("b", needs=prev)\n    c = step("c", needs=[a])\n'
    assert not messages(tmp_path, body, rule="L-E05")


def test_should_report_a_cycle_in_raw_hera_depends(tmp_path):
    body = '    x = Task(name="x", depends="y")\n    y = Task(name="y", depends="x.Succeeded")\n'
    assert any("depends on itself" in m for m in messages(tmp_path, body, rule="L-E05"))


@pytest.mark.parametrize("body,expect", [
    ('    a = step("a", walltime="2h", gpu=True)\n', "no argument 'walltime'"),
    ('    a = step("a", hpc_time_limit="2 hours", gpu=True)\n', "must be minutes or hours"),
    ('    a = step("a", hpc_time_limit="2h")\n', "only applies to gpu=True"),
    ('    a = step("a", resumable="soon", gpu=True)\n', "resumable='soon'"),
    ('    a = step("a", resumable=True)\n', "only applies to gpu=True"),
    ('    a = step("a", checkpoint_every=0, gpu=True)\n', "checkpoint_every=0"),
    ('    a = step("a", idle_timeout="never", gpu=True)\n', "idle_timeout='never'"),
    ('    a = step()\n', "without a name"),
])
def test_should_report_each_argument_step_refuses(tmp_path, body, expect):
    assert any(expect in m for m in messages(tmp_path, body, rule="L-E06")), body


def test_should_accept_the_arguments_step_accepts(tmp_path):
    body = ('    a = step("a", gpu=True, hpc_time_limit="12h", resumable="20m", checkpoint_every="1h", '
            'idle_timeout=0, disk="20Gi", when="x")\n    b = step("b", resumable=False, checkpoint_every=False)\n')
    assert not messages(tmp_path, body, rule="L-E06")


@pytest.mark.parametrize("body,expect", [
    ('    c = Container(name="c", pod_spec_patch="{}")\n', "patches a pod"),
    ('    c = Container(name="c", executor=Executor(service_account_name="x"))\n', "service account"),
    ('    c = {"serviceAccountName": "x"}\n', "service account"),
    ('    c = Container(name="hpc-follower")\n', "reserves"),
    ('    c = step("meluxina-run")\n', "reserves"),
])
def test_should_report_each_client_identity_form(tmp_path, body, expect):
    assert any(expect in m for m in messages(tmp_path, body, rule="L-E04")), body


def test_should_not_flag_the_same_reserved_name_twice(tmp_path):
    assert len(messages(tmp_path, '    c = step(name="hpc-follower")\n', rule="L-E04")) == 1


def test_l_e01_does_not_fire_when_the_step_is_resumable_or_its_code_uses_checkpoints(tmp_path):
    from lint_corpus import CHECKPOINT_STEP, NO_PROGRESS, with_evidence
    body = '    t = step("work", gpu=True, hpc_time_limit="72h")\n'
    failing = with_evidence(("work", False, NO_PROGRESS))
    assert messages(tmp_path / "a", body, {"work": "def f(): pass\n"}, failing, rule="L-E01")
    assert not messages(tmp_path / "b", body, {"work": CHECKPOINT_STEP}, rule="L-E01")
    assert not messages(tmp_path / "c", '    t = step("work", gpu=True, hpc_time_limit="72h", resumable=True)\n',
                        {"work": "def f(): pass\n"}, failing, rule="L-E01")


def test_l_e01_follows_the_catalogues_lane_maximum(tmp_path):
    from lint_corpus import with_lane
    body = '    t = step("work", gpu=True, hpc_time_limit="72h", resumable=False)\n'
    assert not messages(tmp_path / "a", body, {"work": "x = 1\n"}, with_lane(5 * 1440), rule="L-E01")
    assert messages(tmp_path / "b", body, {"work": "x = 1\n"}, with_lane(60), rule="L-E01")


def test_w01_stays_quiet_when_l_e01_already_reports_the_step(tmp_path):
    body = '    t = step("work", gpu=True, hpc_time_limit="72h", resumable=False)\n'
    assert not messages(tmp_path, body, {"work": "x = 1\n"}, rule="L-W01")


def test_w04_reports_a_pipeline_that_never_registers_a_model(tmp_path):
    from lint_corpus import CHECKPOINT_STEP
    out = messages(tmp_path, '    t = step("train-x", gpu=True, reads=["train"])\n', {"train-x": CHECKPOINT_STEP},
                   rule="L-W04")
    assert any("registers a model" in m for m in out)


def test_w03_reports_latest_in_step_code(tmp_path):
    code = "REF = 'dataset-default@latest'\n"
    assert any("@latest" in m for m in messages(tmp_path, '    a = step("a")\n', {"a": code}, rule="L-W03"))
