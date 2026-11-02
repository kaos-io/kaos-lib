"""A fake MlflowClient: the calls kaos_lib.lock makes (set_tag, log_text, list_artifacts, download_artifacts)."""
from __future__ import annotations

import pathlib
from types import SimpleNamespace


class FakeMlflowClient:
    def __init__(self):
        self.tags: dict = {}        # run id -> {key: value}
        self.artifacts: dict = {}   # run id -> {path: text}
        self.calls: list = []       # (method, run id, key or path)
        self.fail = None            # an exception every call raises

    def _call(self, method, run_id, what=None):
        self.calls.append((method, run_id, what))
        if self.fail is not None:
            raise self.fail

    def set_tag(self, run_id, key, value):
        self._call("set_tag", run_id, key)
        self.tags.setdefault(run_id, {})[key] = value

    def log_text(self, run_id, text, artifact_file):
        self._call("log_text", run_id, artifact_file)
        self.artifacts.setdefault(run_id, {})[artifact_file] = text

    def list_artifacts(self, run_id, path=None):
        self._call("list_artifacts", run_id, path)
        return [SimpleNamespace(path=p, is_dir=False) for p in self.artifacts.get(run_id, {})]

    def download_artifacts(self, run_id, path, dst_path=None):
        self._call("download_artifacts", run_id, path)
        target = pathlib.Path(dst_path) / path
        target.write_text(self.artifacts[run_id][path])
        return str(target)
