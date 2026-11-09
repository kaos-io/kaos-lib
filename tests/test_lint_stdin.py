"""`kaosctl lint --stdin-path`: lint an editor's unsaved text. Same report as the saved file, nothing else read from
stdin, never executed."""
import io
import json
import sys

from kaos_lib import cli
from lint_corpus import CASES, repo, write_repo


def run(monkeypatch, capsys, stdin_text, *argv):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin_text.encode("utf-8"))))
    code = cli.main(["lint", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_the_saved_text_on_stdin_gives_byte_identical_output(tmp_path, monkeypatch, capsys):
    files = CASES["L-E06"][0]
    root = write_repo(tmp_path, files)
    _, from_disk, _ = run(monkeypatch, capsys, "", str(root), "--format", "json")
    code, from_stdin, _ = run(monkeypatch, capsys, files["pipeline.py"], str(root), "--format", "json",
                              "--stdin-path", "pipeline.py")
    assert code == 2 and from_stdin == from_disk


def test_the_buffer_wins_over_the_file_on_disk(tmp_path, monkeypatch, capsys):
    root = write_repo(tmp_path, CASES["L-E06"][0])           # disk has an error
    clean = repo('    step("a")\n')["pipeline.py"]
    code, out, _ = run(monkeypatch, capsys, clean, str(root), "--format", "json", "--stdin-path", "pipeline.py")
    assert code == 0 and json.loads(out)["summary"]["errors"] == 0


def test_an_unsaved_error_is_found_though_the_disk_is_clean(tmp_path, monkeypatch, capsys):
    root = write_repo(tmp_path, repo('    step("a")\n'))
    bad = repo('    step("a", walltime="1h")\n')["pipeline.py"]
    code, out, _ = run(monkeypatch, capsys, bad, str(root), "--format", "json", "--stdin-path", "pipeline.py")
    assert code == 2 and [f["rule"] for f in json.loads(out)["findings"]] == ["L-E06"]


def test_other_files_still_come_from_disk(tmp_path, monkeypatch, capsys):
    root = write_repo(tmp_path, repo('    step("a", reads=["nope"])\n'))
    text = (root / "pipeline.py").read_text()
    _, out, _ = run(monkeypatch, capsys, text, str(root), "--format", "json", "--stdin-path", "pipeline.py")
    assert "L-E05" in out                                     # sections come from config/ on disk


def test_a_file_that_is_not_the_pipeline_is_refused(tmp_path, monkeypatch, capsys):
    root = write_repo(tmp_path, repo('    step("a")\n'))
    code, out, err = run(monkeypatch, capsys, "x", str(root), "--stdin-path", "config/train.yaml")
    assert code == 1 and out == "" and "must name the pipeline file" in err


def test_an_oversized_or_invalid_buffer_becomes_a_finding_not_a_crash(tmp_path, monkeypatch, capsys):
    root = write_repo(tmp_path, repo('    step("a")\n'))
    _, out, _ = run(monkeypatch, capsys, "def broken(:\n", str(root), "--format", "json", "--stdin-path", "pipeline.py")
    assert json.loads(out)["findings"][0]["rule"] == "L-E00"
    _, out, _ = run(monkeypatch, capsys, "#" * (1024 * 1024 + 10), str(root), "--format", "json",
                    "--stdin-path", "pipeline.py")
    assert json.loads(out)["findings"][0]["rule"] == "L-E00"


def test_the_buffer_is_never_executed(tmp_path, monkeypatch, capsys):
    marker = tmp_path / "ran"
    root = write_repo(tmp_path / "r", repo('    step("a")\n'))
    code_text = f'open({str(marker)!r}, "w").write("x")\n' + repo('    step("a")\n')["pipeline.py"]
    run(monkeypatch, capsys, code_text, str(root), "--stdin-path", "pipeline.py")
    run(monkeypatch, capsys, code_text, str(root), "--graph", "--stdin-path", "pipeline.py")
    assert not marker.exists()


def test_the_graph_reads_the_buffer(tmp_path, monkeypatch, capsys):
    root = write_repo(tmp_path, repo('    step("a")\n'))
    text = repo('    a = step("a")\n    step("b", needs=[a])\n')["pipeline.py"]
    _, out, _ = run(monkeypatch, capsys, text, str(root), "--graph", "--stdin-path", "pipeline.py")
    assert len(json.loads(out)["pipelines"][0]["edges"]) == 1
