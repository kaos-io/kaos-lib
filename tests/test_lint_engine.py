"""Engine behaviour of the pipeline linter beyond single rules: skipped rules, the report, the catalogue, limits."""
import json
import pathlib

import pytest

from kaos_lib.lint import (MixedRulesetVersions, RULESET_VERSION, Report, empty_catalogue,
                           from_context, lint_project, merge_reports, read_context)
from lint_corpus import CASES, repo, write_repo

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "lint"


def lint(tmp_path, files, catalogue=None):
    return lint_project(write_repo(tmp_path, files), catalogue)


def test_should_skip_rules_that_need_the_catalogue_when_there_is_none(tmp_path):
    """AC-29: with no catalogue the L-E03 fixture is reported skipped, never passed."""
    report = lint(tmp_path, CASES["L-E03"][0], empty_catalogue())
    assert not [f for f in report.findings if f.rule == "L-E03"]
    assert "L-E03" in {s.rule for s in report.skipped}
    assert all(s.reason for s in report.skipped)


def test_should_skip_the_class_rule_with_the_built_in_default_catalogue(tmp_path):
    report = lint(tmp_path, CASES["L-E03"][0])
    assert "L-E03" in {s.rule for s in report.skipped} 


def test_every_finding_has_a_level_a_fix_and_a_doc_link_that_resolves(tmp_path):
    """AC-27: report schema plus a link check (each link is a page of the docs)."""
    seen = 0
    for rule_id, (failing, _, catalogue, _) in CASES.items():
        report = lint(tmp_path / rule_id, failing, catalogue)
        for f in report.findings:
            seen += 1
            assert f.level in ("error", "warning", "info") and f.fix and f.message
            assert (DOCS / f.doc.rsplit("/", 1)[1].replace(".html", ".md")).is_file(), f.doc
        for s in report.skipped:
            assert (DOCS / s.doc.rsplit("/", 1)[1].replace(".html", ".md")).is_file()
    assert seen >= len(CASES)


def test_the_json_report_has_the_documented_shape(tmp_path):
    data = json.loads(lint(tmp_path, CASES["L-E06"][0]).to_json())
    assert list(data) == ["ruleset_version", "catalogue", "summary", "findings", "skipped"]
    assert data["ruleset_version"] == RULESET_VERSION
    f = data["findings"][0]
    assert list(f) == ["rule", "name", "level", "file", "range", "message", "fix", "doc"]
    assert list(f["range"]) == ["start", "end"] and list(f["range"]["start"]) == ["line", "column"]
    assert data["summary"] == {"errors": 1, "warnings": 0, "infos": 0, "skipped": 2}


def test_the_report_round_trips_through_json(tmp_path):
    report = lint(tmp_path, CASES["L-E05"][0])
    assert Report.from_json(report.to_json()).to_json() == report.to_json()


def test_the_same_input_gives_byte_identical_json(tmp_path):
    a = lint(tmp_path / "a", CASES["L-E05"][0]).to_json()
    b = lint(tmp_path / "b", CASES["L-E05"][0]).to_json()
    assert a == b


def test_should_refuse_to_mix_rule_set_versions():
    a, b = Report("1.0.0", {}), Report("1.1.0", {})
    with pytest.raises(MixedRulesetVersions):
        merge_reports([a, b])
    with pytest.raises(MixedRulesetVersions):
        merge_reports([a], ruleset_version="2.0.0")
    assert merge_reports([a, Report("1.0.0", {})]).ruleset_version == "1.0.0"


# --- the catalogue -----------------------------------------------------------------------------------------------

CONTEXT = """
computeClasses:
  all:
    - {name: cpu-standard, tier: cpu}
    - {name: gpu-t4, tier: gpu}
hpc:
  enabled: true
  limits: {maxTimeLimitMinutes: 600}
  classes:
    - {name: slurm-gpu, tier: gpu, maxTimeLimitMinutes: 1440}
"""


def test_the_catalogue_from_a_context_lists_the_classes():
    cat = from_context(__import__("yaml").safe_load(CONTEXT))
    assert cat.classes == ("cpu-standard", "gpu-t4", "slurm-gpu")
    assert cat.to_dict()["source"] == "platform context"


def test_the_context_may_be_a_configmap(tmp_path):
    cm = {"kind": "ConfigMap", "data": {"context.yaml": CONTEXT}}
    p = tmp_path / "cm.yaml"
    p.write_text(__import__("yaml").safe_dump(cm))
    assert read_context(str(p)).classes == ("cpu-standard", "gpu-t4", "slurm-gpu")


# --- limits and unreadable input ---------------------------------------------------------------------------------

def test_a_missing_pipeline_is_an_error_finding_not_an_exception(tmp_path):
    report = lint(tmp_path, {"README.md": "x"})
    assert [f.rule for f in report.findings] == ["L-E00"] and "not found" in report.findings[0].message


def test_a_syntax_error_is_an_error_finding(tmp_path):
    report = lint(tmp_path, {"pipeline.py": "with pipeline('p') as p\n    pass\n"})
    assert [f.rule for f in report.findings] == ["L-E00"] and "not valid Python" in report.findings[0].message


def test_a_file_over_the_size_limit_is_an_error_finding(tmp_path):
    report = lint(tmp_path, {"pipeline.py": "x = 1\n" + "# " + "a" * (1024 * 1024) + "\n"})
    assert [f.rule for f in report.findings] == ["L-E00"] and "larger than" in report.findings[0].message


def test_deep_nesting_fails_with_a_finding_not_a_crash(tmp_path):
    report = lint(tmp_path, {"pipeline.py": "x = " + "(" * 20000 + "1" + ")" * 20000 + "\n"})
    assert [f.rule for f in report.findings] == ["L-E00"]


def test_step_folders_that_are_symbolic_links_are_not_read(tmp_path):
    secret = tmp_path / "outside"
    secret.mkdir()
    (secret / "x.py").write_text("import mlflow\nfrom kaos_lib import checkpoint\n")
    files = repo('    t = step("train-x", kind="evaluate", gpu=True, reads=["train"])\n')
    root = write_repo(tmp_path / "repo", files)
    (root / "steps").mkdir()
    (root / "steps" / "train_x").symlink_to(secret)
    report = lint_project(root)
    assert not [f for f in report.findings if f.rule == "L-W04"]   # an unread folder is not judged


def test_a_template_shaped_pipeline_has_no_errors(tmp_path):
    body = ('    prepare = step("prepare-data", kind="transform", reads=["dataset"], inputs=["dataset"],\n'
            '                   produces=[dataset("clean")])\n'
            '    hello = step("hello-world", kind="evaluate", reads=["experiment"], needs=[prepare],\n'
            '                 produces=[artifact("report")])\n')
    code = "from kaos_lib import step\nstep.start()\nstep.result()\n"
    report = lint(tmp_path, repo(body, {"prepare-data": code, "hello-world": code}))
    assert report.errors == 0


def test_findings_are_sorted_by_position(tmp_path):
    report = lint(tmp_path, repo('    a = step("a", kind="evaluate", disk="1 GB")\n    b = step("b", kind="evaluate", disk="2 GB")\n'))
    lines = [f.span.line for f in report.findings]
    assert lines == sorted(lines)
