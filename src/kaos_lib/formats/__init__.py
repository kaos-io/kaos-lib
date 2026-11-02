"""The 0.3 ``formats`` API, kept so existing code keeps working: each format is now a layout (``kaos_lib.layouts``).

``get_format(name)`` returns the layout ``name`` as a creator + consumer pair with the 0.3 signatures. New code
uses ``kaos_lib.layouts.load(name)`` directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from .. import layouts
from ..layouts import ValidationReport, local  # noqa: F401  (0.3 names)


class _Creator:
    def __init__(self, layout: layouts.Layout):
        self.layout, self.name = layout, layout.name

    def skeleton(self, classes: Optional[Sequence[str]] = None, description: str = "", title: str = "dataset",
                 **values) -> dict:
        if classes is not None:
            values["classes"] = list(classes)
        return self.layout.skeleton(title, description, values)

    def validate(self, local_dir) -> ValidationReport:
        return self.layout.validate(local_dir)

    def publish(self, *args, **kwargs):
        return self.layout.publish(*args, **kwargs)


class _Consumer:
    def __init__(self, layout: layouts.Layout):
        self.layout, self.name = layout, layout.name

    def materialize(self, ref, dest=None, client=None, commit=None, prefix=None):
        return self.layout.materialize(ref, dest, client, commit, prefix=prefix)


@dataclass(frozen=True)
class Format:
    """A named creator + consumer pair."""
    name: str
    creator: Any
    consumer: Any


def get_format(name: str) -> Format:
    """The layout ``name`` as a 0.3 format; DatasetError listing the known layouts otherwise."""
    layout = layouts.load(name)
    return Format(layout.name, _Creator(layout), _Consumer(layout))


def format_names() -> list:
    return [lay.name for lay in layouts.available(warn=False)]
