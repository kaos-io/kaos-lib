"""0.3.0 rename: the ``kubecore`` import shim, the ``kubecore`` command alias and ``kaos-cli --version``."""
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

import kaos_lib
from kaos_lib import cli

ROOT = pathlib.Path(__file__).resolve().parents[1]

SHIM_PROBE = r"""
import json, warnings
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    import kubecore
    import kubecore                                    # a second import warns no more
    from kubecore import datasets, outputs
    from kubecore.errors import DatasetError, KubecoreError
    from kubecore.layouts import load
    import kubecore.layouts.yolo
import kaos_lib, kaos_lib.datasets, kaos_lib.errors, kaos_lib.layouts.yolo
print(json.dumps({
    "deprecations": [str(w.message) for w in caught if w.category is DeprecationWarning],
    "where": [w.filename for w in caught if w.category is DeprecationWarning],
    "same_datasets": datasets is kaos_lib.datasets,
    "same_outputs": outputs is kaos_lib.outputs,
    "same_nested": kubecore.layouts.yolo is kaos_lib.layouts.yolo,
    "same_error": DatasetError is kaos_lib.errors.DatasetError,
    "old_base": KubecoreError is kaos_lib.errors.KaosLibError,
    "load": load is kaos_lib.layouts.load,
    "version": kubecore.__version__,
}))
"""


def _probe():
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "src"), os.environ.get("PYTHONPATH", "")]))
    out = subprocess.run([sys.executable, "-c", SHIM_PROBE], env=env, cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_kubecore_import_shim_works_and_warns_once():
    got = _probe()
    assert len(got["deprecations"]) == 1
    assert "kaos_lib" in got["deprecations"][0] and "pip install kaos-lib" in got["deprecations"][0]
    assert got["where"] == ["<string>"]                     # points at the importer, not at importlib
    assert got["same_datasets"] and got["same_outputs"] and got["same_nested"]
    assert got["same_error"] and got["old_base"] and got["load"]
    assert got["version"] == kaos_lib.__version__


def test_kaos_cli_version(capsys):
    with pytest.raises(SystemExit) as exit_:
        cli.main(["--version"])
    assert exit_.value.code == 0
    assert capsys.readouterr().out.strip() == f"kaos-cli {kaos_lib.__version__}"


def test_kubecore_command_alias_notes_the_rename_and_runs_kaos_cli(capsys, tmp_path):
    with pytest.raises(SystemExit):
        cli.kubecore_alias(["--version"])
    out, err = capsys.readouterr()
    assert out.strip() == f"kaos-cli {kaos_lib.__version__}"
    assert "`kubecore` is now `kaos-cli`" in err
    argv = ["dataset", "validate", str(tmp_path), "--layout", "yolo"]
    assert cli.kubecore_alias(argv) == cli.main(argv)


def test_console_scripts_and_version_match_pyproject():
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert re.search(r'^name = "kaos-lib"$', pyproject, re.M)
    assert re.search(r'^version = "(.+)"$', pyproject, re.M).group(1) == kaos_lib.__version__
    assert re.search(r'^kaos-cli = "kaos_lib\.cli:main"$', pyproject, re.M)
    assert re.search(r'^kubecore = "kaos_lib\.cli:kubecore_alias"', pyproject, re.M)
