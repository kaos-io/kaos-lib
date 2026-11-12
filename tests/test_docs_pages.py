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
KINDS = ["Home", "Start here", "The contract", "How to", "Reference", "Changelog"]
# Pages that moved: each stays as a short page that points to the new place, outside the navigation.
MOVED = {"step-kinds.md", "must-and-can.md", "principles.md", "datasets-versions-hashes.md"}


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
    lines = [r for r in rows(CHEAT) if not r.startswith("| keyword") and not r.startswith("| call")
             and not r.startswith("| kind |")]
    assert len(lines) >= len(constants.STEP_PARAMS)
    assert all(re.search(r"\]\([a-z0-9-]+\.md(#[a-z0-9_-]+)?\)", line) for line in lines), "a cheat sheet line has no link"


def test_should_put_every_page_in_the_navigation_once():
    listed = pages_of(nav())
    found = sorted(p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md")
                   if "generated" not in p.parts and "examples" not in p.parts and "design" not in p.parts)
    assert sorted(listed) == sorted(set(listed)), "a page is in the navigation twice"
    absent = [p for p in found if p not in listed and p not in MOVED]
    assert not absent, f"pages that are not in the navigation: {absent}"
    assert not MOVED & set(listed), "a page that moved is in the navigation"


def test_should_group_the_navigation_in_the_kinds_of_page_and_put_the_contract_second():
    assert [next(iter(e)) if isinstance(e, dict) else e for e in nav()] == KINDS


def table_of(text: str) -> list:
    """The rows of the table of the six step types: the lines that start with a link to a step type page."""
    return [line for line in text.splitlines() if re.match(r"\| \[`(ingest|transform|train|evaluate|publish|control)`\]", line)]


def test_should_show_the_same_table_of_step_types_on_the_overview_and_the_cheat_sheet():
    overview = table_of((DOCS / "step-types.md").read_text(encoding="utf-8"))
    assert len(overview) == len(constants.STEP_KINDS)
    assert overview == table_of(CHEAT), "the table of step types differs between the overview and the cheat sheet"


def test_should_have_a_page_for_every_step_type_with_the_same_headings():
    headings = ["What it is for", "The contract", "Where it runs", "What the platform does",
                "A complete minimal example", "Common mistakes", "Related"]
    for kind in constants.STEP_KINDS:
        text = (DOCS / f"step-type-{kind}.md").read_text(encoding="utf-8")
        assert re.findall(r"^## (.+)$", text, re.M) == headings, f"the headings of the page of {kind}"
        assert text.startswith(f"# {kind}\n")


def test_should_keep_a_moved_page_short_and_pointing_at_the_new_place():
    for name in MOVED:
        text = (DOCS / name).read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 25, f"{name} is not a short page"
        assert re.search(r"\]\((contract|step-types|data-contract)\.md", text), f"{name} does not point at the new place"
