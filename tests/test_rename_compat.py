"""The kubecore -> kaos rename: KAOS_<X> and .kaos/ are the names; KUBECORE_<X> and .kubecore/ still work."""
from __future__ import annotations

import json

import pytest

from kaos_lib import _env, config, credentials, datasets, oidc, runtime
from kaos_lib.errors import ConfigError, DatasetError
from kaos_lib.layouts import local
from kaos_lib.transfer import IGNORED_NAMES

RUNTIME_FIELDS = {"RUN_ID": "run_id", "WORKFLOW_NAME": "workflow", "APP": "app", "PROJECT": "project",
                  "STEP": "step", "DATASET_REF": "dataset_ref", "DATASET_COMMIT": "dataset_commit"}


@pytest.mark.parametrize("suffix,field", sorted(RUNTIME_FIELDS.items()))
def test_runtime_old_name_still_works(suffix, field):
    assert getattr(runtime.context({"KUBECORE_" + suffix: "old"}), field) == "old"


@pytest.mark.parametrize("suffix,field", sorted(RUNTIME_FIELDS.items()))
def test_runtime_new_name_wins(suffix, field):
    env = {"KUBECORE_" + suffix: "old", "KAOS_" + suffix: "new"}
    assert getattr(runtime.context(env), field) == "new"


def test_runtime_empty_new_falls_back():
    assert runtime.context({"KAOS_RUN_ID": "", "KUBECORE_RUN_ID": "old"}).run_id == "old"
    assert runtime.run_id({"KUBECORE_RUN_ID": "old"}) == "old"


def test_slot_old_names_and_new_wins():
    old = {"KUBECORE_SLOT_GPUS": "1", "KUBECORE_SLOT_CPUS": "32", "KUBECORE_SLOT_MEM_GIB": "120",
           "KUBECORE_SLOT_SHARED": "1"}
    slot = runtime.context(old).slot
    assert (slot.gpus, slot.cpus, slot.mem_gib, slot.shared) == (1, 32, 120, True)
    assert runtime.context({**old, "KAOS_SLOT_CPUS": "8"}).slot.cpus == 8
    assert runtime.usable_cpus({"KAOS_SLOT_CPUS": "4", "KUBECORE_SLOT_CPUS": "32"}) == 4


def test_env_helper(monkeypatch):
    assert _env.get("X_UNSET", {}) is None and _env.get("X_UNSET", {}, default="d") == "d"
    assert _env.get("X", {"KUBECORE_X": "old"}) == "old"
    assert _env.get("X", {"KUBECORE_X": "old", "KAOS_X": "new"}) == "new"
    monkeypatch.setenv("KUBECORE_X", "old")
    assert _env.get("X") == "old"
    monkeypatch.setenv("KAOS_X", "new")
    assert _env.get("X") == "new"


def test_oidc_settings_both_names(monkeypatch):
    monkeypatch.setenv("KUBECORE_ML_OIDC_ISSUER", "https://old")
    monkeypatch.setenv("KUBECORE_ML_OIDC_CLIENT_ID", "old-client")
    monkeypatch.setenv("KUBECORE_ML_OIDC_PROJECT_ID", "1")
    assert config.oidc_settings() == ("https://old", "old-client", "1")
    monkeypatch.setenv("KAOS_ML_OIDC_ISSUER", "https://new")
    monkeypatch.setenv("KAOS_ML_OIDC_CLIENT_ID", "new-client")
    monkeypatch.setenv("KAOS_ML_OIDC_PROJECT_ID", "2")
    assert config.oidc_settings() == ("https://new", "new-client", "2")


def test_ml_home_both_names(tmp_path, monkeypatch):
    monkeypatch.delenv("KAOS_ML_HOME")
    monkeypatch.setenv("KUBECORE_ML_HOME", str(tmp_path / "old"))
    assert str(credentials.session_path()).startswith(str(tmp_path / "old"))
    monkeypatch.setenv("KAOS_ML_HOME", str(tmp_path / "new"))
    assert str(credentials.session_path()).startswith(str(tmp_path / "new"))


def test_login_timeout_names(monkeypatch):
    import importlib
    try:
        monkeypatch.setenv("KUBECORE_ML_LOGIN_TIMEOUT", "11")
        assert importlib.reload(oidc).LOGIN_TIMEOUT == 11
        monkeypatch.setenv("KAOS_ML_LOGIN_TIMEOUT", "22")
        assert importlib.reload(oidc).LOGIN_TIMEOUT == 22
    finally:
        monkeypatch.delenv("KUBECORE_ML_LOGIN_TIMEOUT")
        monkeypatch.delenv("KAOS_ML_LOGIN_TIMEOUT")
        importlib.reload(oidc)


def test_cache_and_staged_dir_names(tmp_path, monkeypatch):
    monkeypatch.delenv("KAOS_CACHE_DIR")
    monkeypatch.setenv("KUBECORE_CACHE_DIR", str(tmp_path / "old"))
    assert local.cache_root() == tmp_path / "old"
    monkeypatch.setenv("KAOS_CACHE_DIR", str(tmp_path / "new"))
    assert local.cache_root() == tmp_path / "new"
    old, new = tmp_path / "staged-old-abc123", tmp_path / "staged-new-abc123"
    old.mkdir(), new.mkdir()
    monkeypatch.setenv("KUBECORE_STAGED_DIR", str(old))
    assert local.staged_dir("abc123") == old
    monkeypatch.setenv("KAOS_STAGED_DIR", str(new))
    assert local.staged_dir("abc123") == new


def test_storage_namespace_base_names(monkeypatch):
    class NoPrefix:
        def storage_namespace_prefix(self):
            return None
    with pytest.raises(DatasetError, match="KAOS_STORAGE_NAMESPACE_BASE"):
        datasets._storage_namespace(NoPrefix(), "r")
    monkeypatch.setenv("KUBECORE_STORAGE_NAMESPACE_BASE", "gs://old/lake")
    assert datasets._storage_namespace(NoPrefix(), "r").startswith("gs://old/lake/r-")
    monkeypatch.setenv("KAOS_STORAGE_NAMESPACE_BASE", "gs://new/lake")
    assert datasets._storage_namespace(NoPrefix(), "r").startswith("gs://new/lake/r-")


def _write_config(root, folder, url):
    (root / folder).mkdir(parents=True, exist_ok=True)
    (root / folder / "dataset-config.yaml").write_text(f"lakefsUrl: {url}\n")


def test_config_file_new_folder(tmp_path):
    _write_config(tmp_path, ".kaos", "https://new")
    assert config.resolve_endpoint() == "https://new"


def test_config_file_old_folder_still_found(tmp_path):
    _write_config(tmp_path, ".kubecore", "https://old")
    assert config.resolve_endpoint() == "https://old"


def test_config_file_new_folder_wins_and_walks_up(tmp_path, monkeypatch):
    _write_config(tmp_path, ".kaos", "https://new")
    _write_config(tmp_path, ".kubecore", "https://old")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    config.load_config.cache_clear()
    assert config.resolve_endpoint() == "https://new"


def test_config_override_env_names(tmp_path, monkeypatch):
    for name, url in (("old.yaml", "https://old"), ("new.yaml", "https://new")):
        (tmp_path / name).write_text(f"lakefsUrl: {url}\n")
    monkeypatch.setenv("KUBECORE_DATASET_CONFIG", str(tmp_path / "old.yaml"))
    config.load_config.cache_clear()
    assert config.resolve_endpoint() == "https://old"
    monkeypatch.setenv("KAOS_DATASET_CONFIG", str(tmp_path / "new.yaml"))
    config.load_config.cache_clear()
    assert config.resolve_endpoint() == "https://new"


def test_missing_config_message_names_kaos_only():
    with pytest.raises(ConfigError) as exc:
        config.resolve_endpoint()
    assert ".kaos/dataset-config.yaml" in str(exc.value) and "kubecore" not in str(exc.value).lower()


def test_marker_names():
    assert local.MARKER == ".kaos-dataset.json"
    assert {".kaos-dataset.json", ".kubecore-dataset.json"} <= IGNORED_NAMES


def test_marker_old_name_is_recognised(tmp_path):
    marker = {"repo": "r", "commit": "c", "prefix": None, "owner": None}
    (tmp_path / ".kubecore-dataset.json").write_text(json.dumps(marker))
    assert local.marker_matches(tmp_path, "r", "c")
    assert not local.marker_matches(tmp_path, "r", "other")
    new = tmp_path / "new"
    new.mkdir()
    (new / ".kaos-dataset.json").write_text(json.dumps(marker))
    assert local.marker_matches(new, "r", "c")
