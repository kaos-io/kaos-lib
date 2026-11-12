"""The shape of the guide: the cheat sheet lists everything the code offers, every page has one place in the
navigation, and the navigation has the four kinds of page and no other."""
import inspect
import pathlib
import re

import yaml

from kaos_lib import step
from kaos_lib.lint import constants

REPO = pathlib.Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
CHEAT = (DOCS / "cheat-sheet.md").read_text(encoding="utf-8")
# Not part of what a step's code calls: the parser of the context, and the reset a test harness uses.
NOT_CALLED_BY_A_STEP = {"parse", "stop"}
KINDS = ["Home", "Start here", "How it works", "How to", "Reference", "Changelog"]


def nav() -> list:
    class Loader(yaml.SafeLoader):
        pass
    Loader.add_multi_constructor("tag:yaml.org,2002:python/", lambda loader, suffix, node: None)
    return yaml.load((REPO / "mkdocs.yml").read_text(encoding="utf-8"), Loader)["nav"]


def pages_of(entry) -> list:
    if isinstance(entry, str):
        return [entry]
    if isinstance(entry, dict):
        return [p for value in entry.values() for p in pages_of(value)]
    return [p for item in entry for p in pages_of(item)]


def rows(text: str) -> list:
    return [line for line in text.splitlines() if line.startswith("|") and not line.startswith("|---")]


def test_should_list_every_keyword_of_step_in_the_cheat_sheet():
    missing = [kw for kw in constants.STEP_PARAMS if f"`{kw}=`" not in CHEAT and not (kw == "name" and "`name`" in CHEAT)]
    assert not missing, f"keywords of step() that the cheat sheet does not list: {missing}"


def test_should_list_every_call_of_the_step_api_in_the_cheat_sheet():
    calls = [name for name, member in inspect.getmembers(step, inspect.isfunction)
             if member.__module__ == step.__name__ and not name.startswith("_") and name not in NOT_CALLED_BY_A_STEP]
    assert calls, "no public call found in kaos_lib.step"
    missing = [name for name in calls if f"`step.{name}(" not in CHEAT]
    assert not missing, f"calls of kaos_lib.step that the cheat sheet does not list: {missing}"


def test_should_link_every_line_of_the_cheat_sheet_to_its_page():
    lines = [r for r in rows(CHEAT) if not r.startswith("| keyword") and not r.startswith("| call")]
    assert len(lines) >= len(constants.STEP_PARAMS)
    assert all(re.search(r"\]\([a-z0-9-]+\.md(#[a-z0-9_-]+)?\)", line) for line in lines), "a cheat sheet line has no link"


def test_should_put_every_page_in_the_navigation_once():
    listed = pages_of(nav())
    found = sorted(p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md")
                   if "generated" not in p.parts and "examples" not in p.parts and "design" not in p.parts)
    assert sorted(listed) == sorted(set(listed)), "a page is in the navigation twice"
    absent = [p for p in found if p not in listed]
    assert not absent, f"pages that are not in the navigation: {absent}"


def test_should_group_the_navigation_in_the_four_kinds_of_page():
    assert [next(iter(e)) if isinstance(e, dict) else e for e in nav()] == KINDS
