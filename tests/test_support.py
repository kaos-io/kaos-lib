"""kaos_lib.support: verdicts, deadline edges, malformed metadata, step start and the kaosctl gate."""
import datetime as dt
import json
import sys
import types

import pytest

import kaos_lib
from kaos_lib import cli, support
from kaos_lib.errors import KaosLibError, UnsupportedVersion

TODAY = dt.date(2026, 11, 2)
POLICY = {"version": "0.4.0", "supported": ">=0.3",
          "deprecated": [{"range": ">=0.2,<0.3", "unsupported_after": "2026-11-02"}],
          "breaking": True, "migration": "https://example.test/migrate"}


def verdict(installed, meta=POLICY, today=TODAY):
    return support.check(installed, meta, today=today)


# ------------------------------------------------------------------ verdicts
@pytest.mark.parametrize("installed", ["0.4.0", "0.4.1", "0.5.0", "1.0.0"])
def test_current_at_or_above_the_newest_release(installed):
    got = verdict(installed)
    assert got == {"verdict": "current", "message": f"kaos-lib {installed} is current", "fix": ""}


def test_behind_when_older_but_supported():
    got = verdict("0.3.2")
    assert got["verdict"] == "behind" and "0.4.0 is available" in got["message"]
    assert "pip install --upgrade 'kaos-lib>=0.4.0'" in got["fix"] and "https://example.test/migrate" in got["fix"]


def test_prerelease_counts_as_its_version():
    assert verdict("0.4.0rc1")["verdict"] == "behind"
    assert verdict("0.5.0.dev3")["verdict"] == "current"


def test_deprecated_before_the_deadline():
    got = verdict("0.2.5", today=dt.date(2026, 10, 1))
    assert got["verdict"] == "deprecated" and "unsupported after 2026-11-02" in got["message"]
    assert got["fix"]


def test_deprecated_on_the_deadline_day_itself():
    assert verdict("0.2.5", today=dt.date(2026, 11, 2))["verdict"] == "deprecated"


def test_unsupported_the_day_after_the_deadline():
    got = verdict("0.2.5", today=dt.date(2026, 11, 3))
    assert got["verdict"] == "unsupported" and "since 2026-11-02" in got["message"] and got["fix"]


def test_deprecated_without_a_deadline_never_turns_unsupported():
    meta = dict(POLICY, deprecated=[{"range": "<0.3"}])
    got = verdict("0.1.0", meta, today=dt.date(2099, 1, 1))
    assert got["verdict"] == "deprecated" and "no removal date" in got["message"]


def test_an_empty_deadline_is_a_missing_deadline():
    meta = dict(POLICY, deprecated=[{"range": "<0.3", "unsupported_after": ""}])
    assert verdict("0.1.0", meta, today=dt.date(2099, 1, 1))["verdict"] == "deprecated"


def test_overlapping_ranges_use_the_latest_deadline():
    meta = dict(POLICY, deprecated=[{"range": "<0.3", "unsupported_after": "2026-11-01"},
                                    {"range": "<0.2.9", "unsupported_after": "2026-12-01"}])
    assert verdict("0.2.0", meta)["verdict"] == "deprecated"          # second range still running
    assert verdict("0.2.9", meta)["verdict"] == "unsupported"         # only the first range matches


def test_overlapping_ranges_one_without_deadline_wins():
    meta = dict(POLICY, deprecated=[{"range": "<0.3", "unsupported_after": "2020-01-01"}, {"range": "<0.3"}])
    assert verdict("0.2.0", meta)["verdict"] == "deprecated"


def test_unsupported_outside_supported_and_any_deprecated_range():
    got = verdict("0.1.0")
    assert got["verdict"] == "unsupported" and "(supported: >=0.3)" in got["message"]


def test_no_migration_link_keeps_the_fix_short():
    got = verdict("0.3.0", dict(POLICY, migration=""))
    assert got["fix"] == "pip install --upgrade 'kaos-lib>=0.4.0'"


def test_json_string_input_is_parsed():
    assert verdict("0.3.0", json.dumps(POLICY))["verdict"] == "behind"


def test_today_defaults_to_the_real_date():
    far = dict(POLICY, deprecated=[{"range": "<0.3", "unsupported_after": "2999-01-01"}])
    assert support.check("0.2.0", far)["verdict"] == "deprecated"


# ------------------------------------------------------------------ malformed metadata: warn, never fail
@pytest.mark.parametrize("meta", [
    "{not json",
    "",
    "[]",
    None,
    42,
    {},
    {"version": "0.4.0"},                                             # no supported
    {"supported": ">=0.3"},                                           # no version
    dict(POLICY, version="not a version"),
    dict(POLICY, supported="=>0.3"),
    dict(POLICY, deprecated=[{"range": "<<0.3"}]),
    dict(POLICY, deprecated=[{"unsupported_after": "2026-01-01"}]),   # no range
    dict(POLICY, deprecated=[{"range": "<0.3", "unsupported_after": "02/11/2026"}]),
    dict(POLICY, deprecated=[{"range": "<0.3", "unsupported_after": 20261102}]),
    dict(POLICY, deprecated=["<0.3"]),
    dict(POLICY, deprecated="<0.3"),
])
def test_malformed_metadata_is_unknown_never_an_exception(meta):
    got = support.check("0.2.0", meta, today=TODAY)
    assert got["verdict"] == "unknown" and "cannot tell whether kaos-lib 0.2.0 is supported" in got["message"]


def test_malformed_installed_version_is_unknown():
    assert support.check("dev-build", POLICY)["verdict"] == "unknown"


# ------------------------------------------------------------------ release.json
def test_packaged_release_json_is_valid_and_matches_this_version():
    meta = support.packaged()
    assert support.validate_release(meta) == []
    assert meta["version"] == kaos_lib.__version__
    assert meta["supported"] == ">=0.2" and meta["deprecated"] == [] and meta["breaking"] is False
    assert support.check(kaos_lib.__version__, meta)["verdict"] == "current"


def test_validate_release_accepts_the_contract_example():
    assert support.validate_release(POLICY) == []
    assert support.validate_release(dict(POLICY, deprecated=[{"range": "<0.3"}])) == []


@pytest.mark.parametrize("meta, problem", [
    ([], "JSON object"),
    ({k: v for k, v in POLICY.items() if k != "breaking"}, "breaking: required"),
    ({k: v for k, v in POLICY.items() if k != "migration"}, "migration: required"),
    (dict(POLICY, breaking="no"), "breaking: required"),
    (dict(POLICY, version="x.y"), "not a PEP 440 version"),
    (dict(POLICY, supported="=>1"), "not a PEP 440 specifier"),
    (dict(POLICY, deprecated=[{"range": "nope"}]), "deprecated[0].range"),
    (dict(POLICY, deprecated=[{}]), "deprecated[0]: needs a range"),
    (dict(POLICY, deprecated=[{"range": "<1", "unsupported_after": "tomorrow"}]), "not YYYY-MM-DD"),
])
def test_validate_release_names_each_problem(meta, problem):
    assert any(problem in e for e in support.validate_release(meta))


def test_packaged_missing_file_is_none(monkeypatch, tmp_path):
    monkeypatch.setattr(support, "PACKAGED", tmp_path / "nope.json")
    assert support.packaged() is None


# ------------------------------------------------------------------ step start
def env_with(meta):
    return {support.ENV: meta if isinstance(meta, str) else json.dumps(meta)}


def test_step_start_does_nothing_without_the_env(capsys):
    assert support.at_step_start("0.1.0", {}) is None
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("installed, expected", [("0.4.0", "current"), ("0.3.0", "behind")])
def test_step_start_logs_and_continues(capsys, installed, expected):
    assert support.at_step_start(installed, env_with(POLICY))["verdict"] == expected
    assert f"kaos-lib {installed}: {expected}:" in capsys.readouterr().err


def test_step_start_continues_when_deprecated(capsys):
    meta = dict(POLICY, deprecated=[{"range": "<0.3", "unsupported_after": "2999-01-01"}])
    assert support.at_step_start("0.2.0", env_with(meta))["verdict"] == "deprecated"
    assert "Fix: pip install --upgrade" in capsys.readouterr().err


def test_step_start_stops_only_when_unsupported(capsys):
    with pytest.raises(UnsupportedVersion, match="unsupported") as err:
        support.at_step_start("0.1.0", env_with(POLICY))
    assert isinstance(err.value, KaosLibError)
    assert "kaos-lib 0.1.0: unsupported:" in capsys.readouterr().err


def test_step_start_malformed_env_warns_and_continues(capsys):
    assert support.at_step_start("0.1.0", env_with("{broken"))["verdict"] == "unknown"
    assert "unknown" in capsys.readouterr().err


class FakeMlflow(types.ModuleType):
    def __init__(self, active):
        super().__init__("mlflow")
        self.active, self.tags = active, {}

    def active_run(self):
        return object() if self.active else None

    def set_tag(self, key, value):
        self.tags[key] = value


def test_step_start_tags_the_active_mlflow_run(monkeypatch):
    fake = FakeMlflow(active=True)
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    support.at_step_start("0.3.0", env_with(POLICY))
    assert fake.tags == {"kaos_lib.support": "behind"}


def test_step_start_tags_the_run_named_by_mlflow_run_id(monkeypatch):
    seen = {}

    class Client:
        def set_tag(self, run_id, key, value):
            seen[run_id] = (key, value)

    tracking = types.ModuleType("mlflow.tracking")
    tracking.MlflowClient = Client
    monkeypatch.setitem(sys.modules, "mlflow", FakeMlflow(active=False))
    monkeypatch.setitem(sys.modules, "mlflow.tracking", tracking)
    monkeypatch.setenv("MLFLOW_RUN_ID", "run-42")
    support.at_step_start("0.4.0", env_with(POLICY))
    assert seen == {"run-42": ("kaos_lib.support", "current")}


def test_step_start_never_fails_on_a_broken_mlflow(monkeypatch):
    class Broken(FakeMlflow):
        def set_tag(self, key, value):
            raise RuntimeError("tracking server down")

    monkeypatch.setitem(sys.modules, "mlflow", Broken(active=True))
    assert support.at_step_start("0.4.0", env_with(POLICY))["verdict"] == "current"


def test_step_start_without_mlflow_does_not_import_it(monkeypatch):
    monkeypatch.delitem(sys.modules, "mlflow", raising=False)
    monkeypatch.delenv("MLFLOW_RUN_ID", raising=False)
    support.at_step_start("0.4.0", env_with(POLICY))
    assert "mlflow" not in sys.modules


def test_importing_kaos_lib_runs_the_step_check(monkeypatch, capsys):
    import importlib
    monkeypatch.setenv(support.ENV, json.dumps(dict(POLICY, version="9.0.0", supported=">=9")))
    with pytest.raises(UnsupportedVersion):
        importlib.reload(kaos_lib)
    monkeypatch.delenv(support.ENV)
    importlib.reload(kaos_lib)                                         # leave the module as it was
    assert "unsupported" in capsys.readouterr().err


# ------------------------------------------------------------------ kaosctl gate
@pytest.fixture
def cli_on_fake(fake, monkeypatch):
    monkeypatch.setattr(cli.LakeFS, "connect", classmethod(lambda cls, url=None, start=None: fake.client()))
    monkeypatch.setattr(cli, "__version__", "0.2.0")
    return fake


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


UNSUPPORTED_FOR_020 = dict(POLICY, deprecated=[])


def test_cli_read_warns_when_unsupported(capsys, cli_on_fake):
    cli_on_fake.kaos[support.UI_PATH] = (200, {"kaos_lib_support": UNSUPPORTED_FOR_020})
    code, out, err = run(capsys, "dataset", "list")
    assert code == 0 and "dataset-default" in out
    assert "WARNING: kaos-lib 0.2.0 is unsupported" in err and "Fix: pip install --upgrade" in err


@pytest.mark.parametrize("argv", [
    ("dataset", "create", "cats", "--layout", "yolo", "--classes", "cat"),
    ("dataset", "release", "dataset-default"),
])
def test_cli_write_refused_when_unsupported(capsys, cli_on_fake, argv):
    cli_on_fake.kaos[support.UI_PATH] = (200, {"kaos_lib_support": json.dumps(UNSUPPORTED_FOR_020)})  # JSON string too
    code, _, err = run(capsys, *argv)
    assert code == 1 and "ERROR: kaos-lib 0.2.0 is unsupported" in err and "refused" in err
    assert "dataset-cats" not in cli_on_fake.repos and not cli_on_fake.repos["dataset-default"].get("tags")


def test_cli_push_refused_when_unsupported(capsys, cli_on_fake, tmp_path):
    from conftest import write_dataset
    cli_on_fake.kaos[support.UI_PATH] = (200, {"kaos_lib_support": UNSUPPORTED_FOR_020})
    code, _, err = run(capsys, "dataset", "push", str(write_dataset(tmp_path / "d")), "dataset-default", "-m", "x")
    assert code == 1 and "refused" in err


def test_cli_write_allowed_when_deprecated(capsys, cli_on_fake):
    meta = dict(POLICY, deprecated=[{"range": "<0.3", "unsupported_after": "2999-01-01"}])
    cli_on_fake.kaos[support.UI_PATH] = (200, {"kaos_lib_support": meta})
    code, _, err = run(capsys, "dataset", "create", "cats", "--layout", "yolo", "--classes", "cat")
    assert code == 0 and "dataset-cats" in cli_on_fake.repos and "WARNING: kaos-lib 0.2.0 is deprecated" in err


def test_cli_behind_warns_on_write_and_proceeds(capsys, cli_on_fake, monkeypatch):
    monkeypatch.setattr(cli, "__version__", "0.3.0")
    cli_on_fake.kaos[support.UI_PATH] = (200, {"kaos_lib_support": POLICY})
    code, _, err = run(capsys, "dataset", "create", "cats", "--layout", "yolo", "--classes", "cat")
    assert code == 0 and "WARNING: kaos-lib 0.3.0 is supported; 0.4.0 is available" in err


def test_cli_current_is_silent(capsys, cli_on_fake, monkeypatch):
    monkeypatch.setattr(cli, "__version__", "0.4.0")
    cli_on_fake.kaos[support.UI_PATH] = (200, {"kaos_lib_support": POLICY})
    code, _, err = run(capsys, "dataset", "list")
    assert code == 0 and err == ""


@pytest.mark.parametrize("ui", [
    None,                                                     # older kaos-lake: no /kaos/v1/ui (404 HTML)
    (200, {"other": 1}),                                      # /kaos/v1/ui without the key yet
    (500, {"message": "boom"}),
    (200, b"<html>not json</html>"),
])
def test_cli_without_platform_metadata_falls_back_to_packaged_and_never_refuses(capsys, cli_on_fake, monkeypatch, ui):
    monkeypatch.setattr(support, "packaged", lambda: dict(UNSUPPORTED_FOR_020))   # even a packaged "unsupported"
    if ui is not None:
        cli_on_fake.kaos[support.UI_PATH] = ui
    code, _, err = run(capsys, "dataset", "create", "cats", "--layout", "yolo", "--classes", "cat")
    assert code == 0 and "dataset-cats" in cli_on_fake.repos
    assert "WARNING: kaos-lib 0.2.0 is unsupported" in err


def test_cli_offline_metadata_fetch_is_quiet_for_the_packaged_release(capsys, cli_on_fake, monkeypatch):
    monkeypatch.setattr(cli, "__version__", kaos_lib.__version__)
    monkeypatch.setattr(support, "from_lakefs", lambda client: None)
    code, _, err = run(capsys, "dataset", "list")
    assert code == 0 and err == ""


def test_cli_malformed_platform_metadata_warns_and_proceeds(capsys, cli_on_fake):
    cli_on_fake.kaos[support.UI_PATH] = (200, {"kaos_lib_support": "{broken"})
    code, _, err = run(capsys, "dataset", "create", "cats", "--layout", "yolo", "--classes", "cat")
    assert code == 0 and "WARNING: cannot tell whether kaos-lib 0.2.0 is supported" in err


def test_from_lakefs_survives_a_network_error(fake):
    client = fake.client()

    class Down:
        def get(self, *a, **k):
            raise OSError("network unreachable")

    client.session = Down()
    assert support.from_lakefs(client) is None
