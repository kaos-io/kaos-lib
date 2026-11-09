"""`kaosctl lint --schema` and `--graph`: the editor's inputs. The schema must follow the library (names, shapes,
links), the graph must follow the file, both must be byte-stable, and nothing of the repository may run."""
import json
import pathlib
import re

from kaos_lib import cli
from kaos_lib.lint import ALL_RULES, RULESET_VERSION
from kaos_lib.lint.constants import DISK_PATTERN, STEP_PARAMS, TIME_PATTERN
from kaos_lib.lint.graph import build_graph
from kaos_lib.lint.schema import RENAMED_ARGUMENTS, SCHEMA_VERSION, build_schema, schema_json
from lint_corpus import repo, write_repo

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BUNDLED = REPO_ROOT / "editors" / "vscode" / "resources" / "step-schema.json"
DOCS = REPO_ROOT / "docs" / "lint"


def run(capsys, *argv):
    code = cli.main(["lint", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


# ---------------------------------------------------------------- schema
def test_schema_lists_every_step_argument_in_library_order():
    params = build_schema()["step"]["parameters"]
    assert [p["name"] for p in params] == list(STEP_PARAMS)
    assert [p["position"] for p in params] == list(range(len(STEP_PARAMS)))


def test_schema_is_versioned_with_the_rule_set():
    schema = build_schema()
    assert schema["schema_version"] == SCHEMA_VERSION and schema["ruleset_version"] == RULESET_VERSION


def test_schema_patterns_are_the_ones_the_rules_use():
    by_name = {p["name"]: p for p in build_schema()["step"]["parameters"]}
    assert by_name["disk"]["pattern"] == DISK_PATTERN
    assert by_name["hpc_time_limit"]["pattern"] == TIME_PATTERN


def test_every_argument_has_documentation_and_every_link_has_a_page():
    for p in build_schema()["step"]["parameters"]:
        assert len(p["doc"]) > 40, p["name"]
        for link in p["links"]:
            assert (DOCS / f"{link['title']}.md").is_file(), link


def test_schema_lists_every_rule_with_its_link():
    rules = {r["id"]: r for r in build_schema()["rules"]}
    assert set(rules) == {r.id for r in ALL_RULES}
    assert all(r["doc"].endswith(f"{r['id']}.html") and r["fix"] for r in rules.values())


def test_renamed_arguments_point_at_real_arguments():
    assert RENAMED_ARGUMENTS == {"walltime": "hpc_time_limit"}
    assert set(RENAMED_ARGUMENTS.values()) <= set(STEP_PARAMS)
    assert not set(RENAMED_ARGUMENTS) & set(STEP_PARAMS)


def test_allowed_values_match_what_the_library_accepts():
    by_name = {p["name"]: p for p in build_schema()["step"]["parameters"]}
    for name in ("hpc_time_limit", "disk", "resumable"):
        pattern = re.compile(by_name[name]["pattern"])
        for v in by_name[name]["values"]:
            text = v["insert"]
            if text.startswith('"'):
                assert pattern.match(text.strip('"')), (name, text)


def test_schema_command_prints_the_same_bytes_every_time(capsys):
    code, first, _ = run(capsys, "--schema")
    _, second, _ = run(capsys, "--schema")
    assert code == 0 and first == second == schema_json()
    assert json.loads(first)["step"]["function"] == "step"


def test_schema_output_goes_to_a_file_with_output(tmp_path, capsys):
    target = tmp_path / "schema.json"
    assert run(capsys, "--schema", "--output", str(target))[0] == 0
    assert target.read_text() == schema_json()


def test_the_extensions_bundled_fallback_equals_the_generated_schema():
    """Regenerate with: kaosctl lint --schema --output editors/vscode/resources/step-schema.json"""
    assert BUNDLED.read_text() == schema_json()


# ---------------------------------------------------------------- graph
BODY = ('    a = step("prepare")\n    b = step("train", needs=[a], gpu=True, hpc_time_limit="12h")\n'
        '    step("evaluate", needs=[a, b])\n')


def test_graph_has_the_steps_and_their_dependencies(tmp_path):
    graph = build_graph(write_repo(tmp_path, repo(BODY)))
    block = graph["pipelines"][0]
    assert graph["file"] == "pipeline.py" and block["name"] == "p" and block["line"] == 3
    assert [n["name"] for n in block["nodes"]] == ["prepare", "train", "evaluate"]
    assert [(e["from"], e["to"]) for e in block["edges"]] == [("s0", "s1"), ("s0", "s2"), ("s1", "s2")]
    train = block["nodes"][1]
    assert train["gpu"] is True and train["hpc_time_limit"] == "12h" and train["line"] == 5 and train["variable"] == "b"


def test_graph_marks_loop_steps_dynamic_and_wires_nothing(tmp_path):
    body = '    a = step("prepare")\n    for i in range(3):\n        step("w", needs=[a])\n'
    block = build_graph(write_repo(tmp_path, repo(body)))["pipelines"][0]
    assert [n["dynamic"] for n in block["nodes"]] == [False, True] and block["edges"] == []


def test_graph_lists_what_it_cannot_follow_instead_of_guessing(tmp_path):
    body = '    a = step("prepare")\n    step("x", needs=[a, missing])\n    step("y", needs=["prepare"])\n'
    block = build_graph(write_repo(tmp_path, repo(body)))["pipelines"][0]
    assert len(block["edges"]) == 1 and len(block["unresolved"]) == 2


def test_graph_command_fails_with_exit_1_on_a_missing_file(tmp_path, capsys):
    code, out, err = run(capsys, "--graph", str(tmp_path))
    assert code == 1 and out == "" and err.startswith("ERROR:")


def test_graph_command_is_byte_stable(tmp_path, capsys):
    root = write_repo(tmp_path, repo(BODY))
    _, first, _ = run(capsys, "--graph", str(root))
    _, second, _ = run(capsys, "--graph", str(root))
    assert first == second and json.loads(first)["graph_version"] == 1


def test_graph_never_runs_the_pipeline_file(tmp_path):
    marker = tmp_path / "ran"
    body = f'    open({str(marker)!r}, "w").write("x")\n    step("a")\n'
    root = write_repo(tmp_path / "r", repo(body))
    (root / "steps" / "a" / "app").mkdir(parents=True, exist_ok=True)
    build_graph(root)
    assert not marker.exists()
