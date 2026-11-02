"""Skeleton files: the placeholder language of ``skeleton.files`` and the parameter values it fills in.

Shared with kaos-lake (``pkg/kaos/templates/render.go``); both must render the fixtures identically.

    {{name}}  {{description}}  {{key}}     a text value, as is
    {{key|quote}}                          as a double-quoted YAML/JSON string
    {{key|count}}                          the number of items of a list
    {{#each key}} ... {{/each}}            once per item of a list: {{@item}}, {{@item|quote}}, {{@index}} (0, 1, ...)
    {{#if key}} ... {{/if}}                only when the text is not empty / the list has items

A line holding nothing but a block tag (``{{#each ..}}``, ``{{/each}}``, ``{{#if ..}}``, ``{{/if}}``) disappears
with its line break, so templates stay readable.
"""
from __future__ import annotations

import re
from typing import Optional

from ..errors import DatasetError

_STANDALONE = re.compile(r"(?m)^[ \t]*(\{\{[ \t]*[#/][^{}\n]*\}\})[ \t]*(?:\r?\n|\Z)")
_TAG = re.compile(r"\{\{([^{}\n]*)\}\}")
_EXPR = re.compile(r"^\s*(@?[A-Za-z_][A-Za-z0-9_]*)\s*(?:\|\s*([a-z]+)\s*)?$")
_OPEN = re.compile(r"^\s*#(each|if)\s+(@?[A-Za-z_][A-Za-z0-9_]*)\s*$")
_CLOSE = re.compile(r"^\s*/(each|if)\s*$")
LOOP_VALUES = ("@index", "@item")


class TemplateError(DatasetError):
    """A skeleton file's placeholders are malformed or name an unknown value."""


class ValuesError(DatasetError):
    """The values given for a layout's parameters are not acceptable."""


def quote(s: str) -> str:
    """``s`` as a double-quoted string, valid YAML and JSON (the same bytes as kaos-lake's)."""
    out = ['"']
    for ch in s:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _parse(text: str) -> list:
    """Nodes: ("text", s) | ("expr", ref, filter) | (block, ref, children)."""
    text = _STANDALONE.sub(r"\1", text)
    root: list = []
    stack = [("root", "", root)]
    pos = 0
    for m in _TAG.finditer(text):
        if m.start() > pos:
            stack[-1][2].append(("text", text[pos:m.start()]))
        pos = m.end()
        inner = m.group(1)
        opened, closed, expr = _OPEN.match(inner), _CLOSE.match(inner), _EXPR.match(inner)
        if opened:
            children: list = []
            stack[-1][2].append((opened.group(1), opened.group(2), children))
            stack.append((opened.group(1), opened.group(2), children))
        elif closed:
            kind = closed.group(1)
            if len(stack) == 1:
                raise TemplateError(f"{{{{/{kind}}}}} closes nothing")
            if stack[-1][0] != kind:
                raise TemplateError(f"{{{{/{kind}}}}} closes {{{{#{stack[-1][0]} {stack[-1][1]}}}}}")
            stack.pop()
        elif expr:
            stack[-1][2].append(("expr", expr.group(1), expr.group(2) or ""))
        else:
            raise TemplateError(f"{{{{{inner}}}}} is not a placeholder")
    if pos < len(text):
        stack[-1][2].append(("text", text[pos:]))
    if len(stack) > 1:
        raise TemplateError(f"{{{{#{stack[-1][0]} {stack[-1][1]}}}}} is not closed")
    return root


def _check(nodes: list, texts: set, lists: set, in_each: bool) -> None:
    for node in nodes:
        kind, ref = node[0], node[1] if len(node) > 1 else ""
        if kind == "text":
            continue
        loop = ref in LOOP_VALUES
        if loop and not in_each:
            raise TemplateError(f"{ref} is only known inside {{{{#each}}}}")
        if not loop and ref not in texts and ref not in lists:
            raise TemplateError(f"unknown value {ref}")
        if kind == "expr":
            flt = node[2]
            if flt not in ("", "quote", "count"):
                raise TemplateError(f"unknown filter {flt}")
            if ref in lists and flt != "count":
                raise TemplateError(f"{ref} is a list: use {{{{#each {ref}}}}} or {{{{{ref}|count}}}}")
            if ref not in lists and flt == "count":
                raise TemplateError(f"count needs a list; {ref} is not one")
        elif kind == "each":
            if ref not in lists:
                raise TemplateError(f"#each needs a list; {ref} is not one")
            _check(node[2], texts, lists, True)
        else:
            _check(node[2], texts, lists, in_each)


def compile_template(text: str, texts: set, lists: set) -> list:
    """Parsed ``text``; TemplateError when it is malformed or names a value that is not ``texts``/``lists``."""
    nodes = _parse(text)
    _check(nodes, texts, lists, False)
    return nodes


def _eval(nodes: list, values: dict, loop: Optional[dict], out: list) -> None:
    for node in nodes:
        kind = node[0]
        if kind == "text":
            out.append(node[1])
            continue
        ref = node[1]
        value = loop[ref] if ref in LOOP_VALUES else values[ref]
        if kind == "expr":
            flt = node[2]
            if flt == "count":
                out.append(str(len(value)))
            else:
                s = str(value)
                out.append(quote(s) if flt == "quote" else s)
        elif kind == "each":
            for i, item in enumerate(value):
                _eval(node[2], values, {"@index": i, "@item": item}, out)
        elif (len(value) > 0) if isinstance(value, list) else (str(value) != ""):
            _eval(node[2], values, loop, out)


def render_text(text: str, values: dict, texts: set, lists: set) -> str:
    out: list = []
    _eval(compile_template(text, texts, lists), values, None, out)
    return "".join(out)


def clean_values(parameters: list, raw: Optional[dict]) -> dict:
    """Checked, trimmed values of ``parameters`` from ``raw`` (unknown keys are ignored); ValuesError otherwise."""
    raw = raw or {}
    out: dict = {}
    for p in parameters:
        label, v = p["label"], raw.get(p["key"])
        if p["type"] == "list":
            if v is None:
                v = []
            if not isinstance(v, (list, tuple)) or not all(isinstance(x, str) for x in v):
                raise ValuesError(f"{label} must be a list of text")
            clean: list = []
            for s in (x.strip() for x in v):
                if not s:
                    continue
                if "\n" in s or "\r" in s:
                    raise ValuesError(f"{label}: {s} spans lines")
                if s in clean:
                    raise ValuesError(f"{label}: {s} is listed twice")
                clean.append(s)
            if p.get("required") and not clean:
                raise ValuesError(f"{label} needs at least one item")
            out[p["key"]] = clean
        else:
            if v is None:
                v = ""
            if not isinstance(v, str):
                raise ValuesError(f"{label} must be text")
            s = v.strip()
            if "\n" in s or "\r" in s:
                raise ValuesError(f"{label} must be one line")
            if p.get("required") and not s:
                raise ValuesError(f"{label} is required")
            out[p["key"]] = s
    return out


def render(spec: dict, name: str, description: str = "", values: Optional[dict] = None) -> dict:
    """``{path: text}`` of a new dataset ``name`` from ``spec``'s skeleton (folders as ``<folder>/.keep``)."""
    params = spec.get("parameters", [])
    data: dict = clean_values(params, values)
    data["name"], data["description"] = name.strip(), (description or "").strip()
    lists = {p["key"] for p in params if p["type"] == "list"}
    texts = {p["key"] for p in params if p["type"] == "text"} | {"name", "description"}
    skeleton = spec.get("skeleton", {})
    files = {f"{folder.rstrip('/')}/.keep": "" for folder in skeleton.get("folders", [])}
    for path, text in skeleton.get("files", {}).items():
        files[path] = render_text(text, data, texts, lists)
    return dict(sorted(files.items()))


def parse_form(spec: dict, content: str) -> dict:
    """The parameter values ``content`` (the layout's ``form_file``) holds, for editing a dataset.

    A list parameter reads its ``form_key`` as a list, or as a mapping ``{0: a, 1: b, ...}`` (ids 0..n-1);
    a text parameter as a single value. Values are the YAML text as written (null is empty). Parameters
    without ``form_key``, or whose key is absent, are left out.
    """
    import yaml
    form = spec.get("form_file")
    if not form:
        raise ValuesError(f"layout {spec['name']} has no form file")
    try:
        doc = yaml.compose(content, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        raise ValuesError(f"{form}: not valid YAML") from None
    if not isinstance(doc, yaml.MappingNode):
        raise ValuesError(f"{form}: must be a mapping")
    found = {k.value: v for k, v in doc.value if isinstance(k, yaml.ScalarNode)}
    out: dict = {}
    for p in spec.get("parameters", []):
        key = p.get("form_key")
        if not key or key not in found:
            continue
        v = found[key]
        if p["type"] == "text":
            if not isinstance(v, yaml.ScalarNode):
                raise ValuesError(f"{form}: {key} must be a single value")
            out[p["key"]] = _text(v)
        elif isinstance(v, yaml.SequenceNode):
            if not all(isinstance(x, yaml.ScalarNode) for x in v.value):
                raise ValuesError(f"{form}: {key} must list single values")
            out[p["key"]] = [_text(x) for x in v.value]
        elif isinstance(v, yaml.MappingNode):
            items = {}
            for k, x in v.value:
                if not isinstance(k, yaml.ScalarNode) or not re.fullmatch(r"0|[1-9][0-9]*", k.value):
                    raise ValuesError(f"{form}: {key}: ids must be 0, 1, 2, ...")
                if not isinstance(x, yaml.ScalarNode):
                    raise ValuesError(f"{form}: {key} must map ids to single values")
                if int(k.value) in items:
                    raise ValuesError(f"{form}: {key}: id {k.value} is listed twice")
                items[int(k.value)] = _text(x)
            if sorted(items) != list(range(len(items))):
                raise ValuesError(f"{form}: {key}: ids must run 0..{len(items) - 1} without gaps")
            out[p["key"]] = [items[i] for i in range(len(items))]
        else:
            raise ValuesError(f"{form}: {key} must be a list or an id -> value mapping")
    return out


def _text(node) -> str:
    return "" if node.tag.endswith(":null") else node.value
