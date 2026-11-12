import importlib.util
from pathlib import Path

from kaos_lib import testing


def load(step_folder):
    path = Path(__file__).parents[1] / "steps" / step_folder / "app" / "entry.py"
    spec = importlib.util.spec_from_file_location(step_folder, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prepare_drops_the_files_that_are_too_small(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "big.txt").write_text("some text")
    (data / "empty.txt").write_text("")
    with testing.running(tmp_path, kind="transform", params={"prepare": {"min_bytes": 1}}, inputs={"dataset": data},
                         produces=[("dataset", "clean"), ("artifact", "dropped-files")]) as run:
        load("prepare").main()
    assert [p.name for p in run.output("clean").iterdir()] == ["big.txt"]
    assert run.result["values"] == {"files": 1, "dropped": 1}
