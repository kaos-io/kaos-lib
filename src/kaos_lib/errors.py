"""Error types. Everything the CLI shows as a one-line message derives from KaosLibError."""
from __future__ import annotations


class KaosLibError(Exception):
    """A user-facing failure: the message says what happened and what to do next."""


class ConfigError(KaosLibError):
    """A required setting (lakeFS URL, ...) could not be determined."""


class AuthError(KaosLibError):
    """No usable credential, or lakeFS rejected the one we carry."""


class LakeFSError(KaosLibError):
    """A lakeFS API call failed. ``status`` is the HTTP status."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class NotFoundError(LakeFSError):
    """The repository, ref, tag or object does not exist."""


class DatasetError(KaosLibError):
    """A dataset reference or operation is invalid (bad ref, nothing to release, ...)."""


class EmptyDataset(DatasetError):
    """The dataset commit holds no files (for instance a new project's ``dataset-default``)."""


class ValidationFailed(KaosLibError):
    """A local dataset failed format validation; ``errors`` holds every problem found."""

    def __init__(self, errors: list):
        self.errors = errors
        super().__init__(f"dataset failed validation ({len(errors)} problem(s))")


class UnsupportedVersion(KaosLibError):
    """This kaos-lib is past its support deadline (``kaos_lib.support``): steps stop, writes are refused."""


class StepError(KaosLibError):
    """A pipeline step cannot start, read an input, or hand its result on (``kaos_lib.step``)."""


class LockError(KaosLibError):
    """A ledger (``kaos_lib.lock``) is malformed, missing from its MLflow run, or cannot be written."""
