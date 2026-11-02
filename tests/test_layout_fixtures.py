"""The shared layout fixtures: kaos-lake runs the same files (pkg/kaos/templates) and must give the same answers.

``SHA256SUMS`` pins the shared bytes (the schema, the built-in layouts, the fixtures). kaos-lake's copy of that
file must be identical: a change here is a change there, in the same review.
"""
import hashlib
import pathlib

import pytest

from kaos_lib import layouts
from kaos_lib.layouts import render, rules, spec

HERE = pathlib.Path(__file__).with_name("layout_fixtures")
ROOTS = {"shared": spec.SHARED, "fixtures": HERE}


def cases(name):
    return [pytest.param(c, id=c["case"]) for c in spec.load_yaml((HERE / f"{name}.yaml").read_text())]


def layout_of(case) -> dict:
    if "builtin" in case:
        return layouts.load(case["builtin"]).spec
    return spec.from_value(case["layout"], case["case"])


def tree_bytes(tree) -> dict:
    return {p: bytes.fromhex(v["hex"]) if isinstance(v, dict) else v.encode() for p, v in (tree or {}).items()}


def test_shared_bytes_match_sha256sums():
    want = {}
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        digest, rel = line.split("  ", 1)
        want[rel] = digest
    root, _, rest = zip(*(rel.partition("/") for rel in want))
    got = {rel: hashlib.sha256((ROOTS[r] / tail).read_bytes()).hexdigest()
           for rel, r, tail in zip(want, root, rest)}
    assert got == want
    listed = {f"shared/{p.relative_to(spec.SHARED).as_posix()}" for p in spec.SHARED.rglob("*") if p.is_file()}
    listed |= {f"fixtures/{p.name}" for p in HERE.glob("*.yaml")}
    assert listed == set(want), "every shared file is pinned"


def test_builtins_are_valid_specs():
    assert layouts.builtin_names() == ["raw", "yolo"]
    for name in layouts.builtin_names():
        assert layouts.load(name).source == "builtin"


@pytest.mark.parametrize("case", cases("spec"))
def test_spec(case):
    errors = spec.problems(case["layout"])
    if case.get("ok"):
        assert errors == []
    else:
        assert any(case["error"] in e for e in errors), errors


@pytest.mark.parametrize("case", cases("render"))
def test_render(case):
    lay = layout_of(case)
    if "error" in case:
        with pytest.raises(render.ValuesError, match=None) as exc:
            render.render(lay, case["name"], case.get("description", ""), case.get("values"))
        assert case["error"] in str(exc.value)
    else:
        assert render.render(lay, case["name"], case.get("description", ""), case.get("values")) == case["files"]


@pytest.mark.parametrize("case", cases("parse"))
def test_parse(case):
    lay = layout_of(case)
    if "error" in case:
        with pytest.raises(render.ValuesError) as exc:
            render.parse_form(lay, case["content"])
        assert case["error"] in str(exc.value)
    else:
        assert render.parse_form(lay, case["content"]) == case["values"]


@pytest.mark.parametrize("case", cases("validate"))
def test_validate(case):
    tree = tree_bytes(case["tree"])
    assert rules.check(layout_of(case), tree, tree.__getitem__) == case["errors"]
