"""`kaosctl lint` and the standalone entry the PR gate runs: output forms, exit codes, byte-identical JSON,
and that nothing of the repository is executed."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

from kaos_lib import cli
from lint_corpus import CASES, repo, write_repo

LINT_DIR = pathlib.Path(cli.__file__).resolve().parent / "lint"
STANDALONE = LINT_DIR / "standalone.py"
BLOCK_HEAVY = ("import sys\nfor m in ('requests', 'packaging'):\n    sys.modules[m] = None\n"
               "import runpy\nsys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name='__main__')\n")


def kaosctl(capsys, *argv):
    code = cli.main(["lint", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def gate(tmp_path, *argv):
    """The gate's command: the standalone script, isolated, with the packages the rest of kaos-lib needs blocked."""
    wrapper = tmp_path / "block.py"
    wrapper.write_text(BLOCK_HEAVY)
    proc = subprocess.run([sys.executable, "-I", str(wrapper), str(STANDALONE), *argv], cwd=str(tmp_path),
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def test_exit_code_is_non_zero_only_on_errors(tmp_path, capsys):
    bad = write_repo(tmp_path / "bad", CASES["L-E06"][0])
    warn = write_repo(tmp_path / "warn", CASES["L-W02"][0])
    assert kaosctl(capsys, str(bad))[0] == 2
    assert kaosctl(capsys, str(warn))[0] == 0


def test_exit_code_1_when_it_cannot_run(tmp_path, capsys):
    code, _, err = kaosctl(capsys, str(tmp_path / "nowhere"))
    assert code == 1 and err.startswith("ERROR:")


def test_text_json_and_markdown_forms(tmp_path, capsys):
    root = write_repo(tmp_path / "r", CASES["L-E05"][0])
    _, text, _ = kaosctl(capsys, str(root))
    assert "pipeline.py:4:" in text and "fix:" in text and "docs:" in text and "Rule set" in text
    _, js, _ = kaosctl(capsys, str(root), "--format", "json")
    assert json.loads(js)["summary"]["errors"] == 1
    _, md, _ = kaosctl(capsys, str(root), "--format", "markdown", "--file-link-base", "https://x/blob/abc/")
    assert "[`pipeline.py:4`](https://x/blob/abc/pipeline.py#L4)" in md and "Pipeline lint: 1 error" in md


def test_status_form_is_one_line_with_the_counts_and_the_rule_set(tmp_path, capsys):
    root = write_repo(tmp_path / "r", CASES["L-E06"][0])
    code, out, _ = kaosctl(capsys, str(root), "--format", "status")
    assert code == 2 and out == "1 error, 0 warnings, 0 infos; 2 rules skipped (rule set 2.0.0)\n"


def test_markdown_lists_skipped_rules_and_caps_long_lists(tmp_path, capsys):
    many = "".join(f'    a{i} = step("a{i}", kind="train", disk="x")\n' for i in range(60))
    root = write_repo(tmp_path / "r", repo(many))
    _, md, _ = kaosctl(capsys, str(root), "--format", "markdown")
    assert "and 10 more" in md and "Rules that did not run" in md


def test_a_saved_report_renders_without_linting_again(tmp_path, capsys):
    root = write_repo(tmp_path / "r", CASES["L-E06"][0])
    out = tmp_path / "report.json"
    kaosctl(capsys, str(root), "--format", "json", "--output", str(out))
    _, md, _ = kaosctl(capsys, "--from-report", str(out), "--format", "markdown")
    assert "L-E06" in md


def test_the_catalogue_round_trips_through_a_file(tmp_path, capsys):
    ctx = tmp_path / "ctx.yaml"
    ctx.write_text("computeClasses:\n  all: [{name: gpu-a}]\nhpc: {enabled: true, limits: {maxTimeLimitMinutes: 60}}\n")
    cat = tmp_path / "cat.json"
    assert kaosctl(capsys, "--context", str(ctx), "--export-catalogue", str(cat))[0] == 0
    assert json.loads(cat.read_text())["classes"] == ["gpu-a"]
    root = write_repo(tmp_path / "r", CASES["L-E03"][0])
    via_context = kaosctl(capsys, str(root), "--format", "json", "--context", str(ctx))[1]
    via_file = kaosctl(capsys, str(root), "--format", "json", "--catalogue", str(cat))[1]
    assert json.loads(via_context)["findings"] == json.loads(via_file)["findings"]
    assert [f["rule"] for f in json.loads(via_file)["findings"] if f["rule"] == "L-E03"] == ["L-E03"]


def test_should_refuse_a_different_rule_set(tmp_path, capsys):
    code, _, err = kaosctl(capsys, str(tmp_path), "--expect-ruleset", "9.9.9")
    assert code == 1 and "9.9.9" in err


@pytest.mark.parametrize("case", ["L-E01", "L-E05", "L-W03", "L-I01"])
@pytest.mark.parametrize("with_context", [False, True])
def test_the_gate_and_the_local_command_give_byte_identical_json(tmp_path, capsys, case, with_context):
    """AC-24: the same files and catalogue give the same bytes from the gate's standalone entry (run isolated, with
    requests and packaging unimportable) and from `kaosctl lint`."""
    root = write_repo(tmp_path / "r", CASES[case][0])
    extra = []
    if with_context:
        ctx = tmp_path / "ctx.yaml"
        ctx.write_text("computeClasses:\n  all: [{name: gpu-a}]\nhpc: {enabled: true}\n")
        extra = ["--context", str(ctx)]
    local = kaosctl(capsys, str(root), "--format", "json", *extra)
    remote = gate(tmp_path, str(root), "--format", "json", *extra)
    assert remote[0] == local[0] and remote[1] == local[1] and remote[1].startswith("{")
    assert remote[2] == ""


def test_the_standalone_entry_imports_nothing_but_the_standard_library_and_yaml(tmp_path):
    root = write_repo(tmp_path / "r", CASES["L-E06"][0])
    code, out, err = gate(tmp_path, str(root))
    assert code == 2 and "L-E06" in out, err


# --- AC-25: no client code is executed ------------------------------------------------------------------------

HOSTILE_PIPELINE = '''import os, socket, subprocess, urllib.request
open(os.environ.get("LINT_MARKER", "/tmp/never") + ".pipeline", "w").write("ran")
os.environ["LEAK"] = open("/etc/hostname").read()
urllib.request.urlopen("http://127.0.0.1:9/x")
subprocess.run(["touch", os.environ.get("LINT_MARKER", "/tmp/never") + ".sub"])
from kubecore.authoring import pipeline, step
with pipeline("p") as p:
    a = step("evil", kind="train", gpu=True, reads=["dataset"])
'''
HOSTILE_STEP = ('import os\nopen(os.environ.get("LINT_MARKER", "/tmp/never") + ".step", "w").write("ran")\n'
                'raise SystemExit("step code ran")\n')
HOSTILE_RUNNER = '''
import audit_guard, sys
from kaos_lib.lint import lint_project, default_catalogue
audit_guard.install(sys.argv[1])
report = lint_project(sys.argv[1], default_catalogue())
print(len(report.findings))
'''
AUDIT_GUARD = '''
import sys

FORBIDDEN = {"socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"}


def install(root):
    root = str(root)

    def hook(event, args):
        if event in FORBIDDEN:
            raise RuntimeError("forbidden event " + event)
        if event == "exec" and getattr(args[0], "co_filename", "").startswith(root):
            raise RuntimeError("client code executed: " + args[0].co_filename)
        if event == "import" and args[0] in ("pipeline", "kubecore", "entry", "app"):
            raise RuntimeError("client module imported: " + args[0])
        if event == "open" and isinstance(args[0], str) and args[0].startswith(root) and "w" in str(args[1]):
            raise RuntimeError("write inside the repository: " + args[0])
    sys.addaudithook(hook)
'''


def test_should_never_execute_client_code(tmp_path):
    """AC-25: a pipeline.py and a step with import-time side effects leave no trace; the run completes with the
    interpreter's exec, import, network, subprocess and write hooks denied for client code."""
    root = write_repo(tmp_path / "repo", {"pipeline.py": HOSTILE_PIPELINE,
                                          "steps/evil/app/entry.py": HOSTILE_STEP,
                                          "config/dataset.yaml": "dataset: x@latest\n"})
    (tmp_path / "audit_guard.py").write_text(AUDIT_GUARD)
    runner = tmp_path / "runner.py"
    runner.write_text(HOSTILE_RUNNER)
    marker = tmp_path / "marker"
    env = dict(os.environ, LINT_MARKER=str(marker), PYTHONPATH=str(pathlib.Path(cli.__file__).parent.parent)
               + os.pathsep + str(tmp_path))
    proc = subprocess.run([sys.executable, str(runner), str(root)], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    assert int(proc.stdout) >= 1
    assert not list(tmp_path.glob("marker*")) and "LEAK" not in os.environ
