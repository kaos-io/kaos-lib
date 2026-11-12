import importlib.util
from pathlib import Path

from kaos_lib import testing


def load(step_folder):
    path = Path(__file__).parents[1] / "steps" / step_folder / "app" / "entry.py"
    spec = importlib.util.spec_from_file_location(step_folder, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_final_copes_when_extra_was_skipped(tmp_path):
    with testing.running(tmp_path, kind="evaluate", name="final", upstream={"base": {"base": True}, "extra": None},
                         produces=[("artifact", "final-report")]) as run:  # None: the step did not run
        load("final").main()
    assert run.result["values"] == {"extra_ran": False}
    assert (run.output("final-report") / "final.txt").read_text() == "extra was skipped\n"


def test_final_uses_the_report_when_extra_ran(tmp_path):
    report = tmp_path / "extra-report"
    report.mkdir()
    (report / "extra.txt").write_text("extra ran\n")
    with testing.running(tmp_path / "ran", kind="evaluate", name="final",
                         upstream={"base": {"base": True}, "extra": {"score": 7}},
                         upstream_writes={"extra": {"extra-report": report}},
                         produces=[("artifact", "final-report")]) as run:
        load("final").main()
    assert run.result["values"] == {"extra_ran": True}
    assert (run.output("final-report") / "final.txt").read_text() == "extra ran, score 7: extra ran\n"
