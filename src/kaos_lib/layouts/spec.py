"""Reading a layout spec (``layout.yaml``) and the small schema language it and its manifest rules use.

Shared contract with kaos-lake (``pkg/kaos/templates``): ``shared/layout.schema.json`` and the fixtures in
``tests/layout_fixtures`` are the same bytes in both repositories, and both implementations must give the same
answers on them. Keep this module and kaos-lake's ``spec.go`` aligned when either changes.

YAML is turned into plain values the same way in both: mappings become dicts keyed by the key's text,
sequences lists, scalars None/bool/int/float/str by their resolved tag (timestamps and binary stay text).
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any, Optional

import yaml

from ..errors import DatasetError

SHARED = pathlib.Path(__file__).with_name("shared")
SCHEMA_PATH = SHARED / "layout.schema.json"
RESERVED_NAMES = {"none"}          # `dataset create --layout none` makes an empty repository
RESERVED_KEYS = {"name", "description"}   # always available to skeleton files
MAX_SPEC_BYTES = 256 * 1024

SCHEMA_KEYWORDS = {"type", "enum", "required", "properties", "additionalProperties", "items", "minItems",
                   "maxItems", "minProperties", "maxProperties", "minimum", "maximum", "minLength", "maxLength",
                   "pattern"}
ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description", "default", "examples"}
TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}

# RE2 (Go) and Python re differ here: refuse what only one of them knows.
_NOT_PORTABLE = re.compile(r"\(\?[=!<>]|\(\?P=|\\[1-9]")


class SpecError(DatasetError):
    """A layout spec is not valid; the message names the file and every problem."""


# ------------------------------------------------------------------ YAML -> plain values
class _YAMLError(ValueError):
    pass


def _scalar(node: yaml.ScalarNode) -> Any:
    tag = node.tag.rsplit(":", 1)[-1]
    if tag in ("null", "bool", "int", "float"):
        return yaml.constructor.SafeConstructor().construct_object(node)
    return node.value   # str, timestamp, binary, anything else: its text


def _plain(node) -> Any:
    if isinstance(node, yaml.MappingNode):
        out = {}
        for key, value in node.value:
            if not isinstance(key, yaml.ScalarNode):
                raise _YAMLError("a mapping key is not a scalar")
            if key.tag.endswith(":merge"):
                raise _YAMLError("merge keys are not supported")
            out[key.value] = _plain(value)
        return out
    if isinstance(node, yaml.SequenceNode):
        return [_plain(v) for v in node.value]
    return _scalar(node)


def load_yaml(text: str) -> Any:
    """Plain values of a YAML document (None for an empty one); ValueError when it is not valid YAML."""
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        raise _YAMLError(str(exc)) from None
    return None if node is None else _plain(node)


# ------------------------------------------------------------------ the schema subset
def _type_of(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


def _has_type(v: Any, t: str) -> bool:
    actual = _type_of(v)
    return actual == t or (t == "number" and actual == "integer")


def _fmt(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _loc(path: str) -> str:
    return path or "(root)"


def _num(v: Any) -> str:
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def check_schema(schema: Any, where: str = "schema") -> list:
    """Problems of a schema itself: only the supported keywords, sensible values."""
    if not isinstance(schema, dict):
        return [f"{where}: must be an object"]
    errors = []
    for key in sorted(schema):
        if key not in SCHEMA_KEYWORDS and key not in ANNOTATIONS:
            errors.append(f"{where}: keyword {key} is not supported")
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not types or any(not isinstance(x, str) or x not in TYPES for x in types):
            errors.append(f"{where}: type must name {', '.join(sorted(TYPES))}")
    if "pattern" in schema:
        errors += check_pattern(schema["pattern"], f"{where}.pattern")
    for key in ("properties",):
        if key in schema:
            if not isinstance(schema[key], dict):
                errors.append(f"{where}.{key}: must be an object")
            else:
                for name in sorted(schema[key]):
                    errors += check_schema(schema[key][name], f"{where}.{key}.{name}")
    for key in ("items",):
        if key in schema:
            errors += check_schema(schema[key], f"{where}.{key}")
    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
        errors += check_schema(schema["additionalProperties"], f"{where}.additionalProperties")
    if "required" in schema and (not isinstance(schema["required"], list)
                                 or not all(isinstance(x, str) for x in schema["required"])):
        errors.append(f"{where}.required: must be a list of keys")
    if "enum" in schema and not isinstance(schema["enum"], list):
        errors.append(f"{where}.enum: must be a list")
    for key in ("minItems", "maxItems", "minProperties", "maxProperties", "minLength", "maxLength"):
        if key in schema and _type_of(schema[key]) != "integer":
            errors.append(f"{where}.{key}: must be an integer")
    for key in ("minimum", "maximum"):
        if key in schema and _type_of(schema[key]) not in ("integer", "number"):
            errors.append(f"{where}.{key}: must be a number")
    return errors


def validate(value: Any, schema: dict, path: str = "") -> list:
    """Problems of ``value`` against ``schema`` (a checked schema), in a fixed order."""
    errors = []
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_has_type(value, x) for x in types):
            return [f"{_loc(path)}: must be {' or '.join(types)}"]
    if "enum" in schema and not any(_type_of(value) == _type_of(e) and value == e for e in schema["enum"]):
        return [f"{_loc(path)}: must be one of {', '.join(_fmt(e) for e in schema['enum'])}"]
    kind = _type_of(value)
    if kind == "object":
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{_loc(path)}: {key} is required")
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            errors.append(f"{_loc(path)}: needs at least {schema['minProperties']} keys")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            errors.append(f"{_loc(path)}: allows at most {schema['maxProperties']} keys")
        props, extra = schema.get("properties", {}), schema.get("additionalProperties", True)
        for key in sorted(value):
            sub = f"{path}.{key}" if path else key
            if key in props:
                errors += validate(value[key], props[key], sub)
            elif extra is False:
                errors.append(f"{sub}: is not allowed")
            elif isinstance(extra, dict):
                errors += validate(value[key], extra, sub)
    elif kind == "array":
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{_loc(path)}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{_loc(path)}: allows at most {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                errors += validate(item, schema["items"], f"{path}[{i}]")
    elif kind in ("integer", "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{_loc(path)}: must be at least {_num(schema['minimum'])}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{_loc(path)}: must be at most {_num(schema['maximum'])}")
    elif kind == "string":
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{_loc(path)}: needs at least {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{_loc(path)}: allows at most {schema['maxLength']} characters")
        if "pattern" in schema and not re.search(schema["pattern"], value, re.ASCII):
            errors.append(f"{_loc(path)}: does not match {schema['pattern']}")
    return errors


def check_pattern(pattern: Any, where: str) -> list:
    """Problems of a regular expression both Go (RE2) and Python must read the same way."""
    if not isinstance(pattern, str):
        return [f"{where}: must be text"]
    if _NOT_PORTABLE.search(pattern):
        return [f"{where}: lookaround and backreferences are not supported"]
    try:
        re.compile(pattern, re.ASCII)
    except re.error:
        return [f"{where}: does not compile"]
    return []


_SCHEMA: dict = {}


def layout_schema() -> dict:
    """The shared ``layout.schema.json``."""
    if not _SCHEMA:
        _SCHEMA.update(load_yaml(SCHEMA_PATH.read_text()))
    return _SCHEMA


# ------------------------------------------------------------------ paths and patterns
def check_path(p: str, where: str, pattern: bool = False) -> list:
    """A relative POSIX path inside the dataset (``pattern``: may hold ``*``, ``?`` and whole-segment ``**``)."""
    what = "pattern" if pattern else "path"
    if p.startswith("/") or "\\" in p or any(s in ("", ".", "..") for s in p.split("/")):
        return [f"{where}: {p} is not a relative {what} inside the dataset"]
    if not pattern and any(c in p for c in "*?"):
        return [f"{where}: {p} must not hold * or ?"]
    if pattern and any("**" in s and s != "**" for s in p.split("/")):
        return [f"{where}: {p}: ** must be a whole folder level"]
    return []


# ------------------------------------------------------------------ the spec
def _semantic(spec: dict) -> list:
    """What the schema cannot say."""
    from . import render
    errors = []
    if spec["name"] in RESERVED_NAMES:
        errors.append(f"name: {spec['name']} is reserved")
    params = spec.get("parameters", [])
    keys = [p["key"] for p in params]
    for i, p in enumerate(params):
        if p["key"] in RESERVED_KEYS:
            errors.append(f"parameters[{i}].key: {p['key']} is reserved")
        elif keys.index(p["key"]) != i:
            errors.append(f"parameters[{i}].key: {p['key']} is used twice")
        if "form_key" in p and "form_file" not in spec:
            errors.append(f"parameters[{i}].form_key: the layout has no form_file")
    if "form_file" in spec:
        errors += check_path(spec["form_file"], "form_file")
    skeleton = spec.get("skeleton", {})
    for i, folder in enumerate(skeleton.get("folders", [])):
        errors += check_path(folder, f"skeleton.folders[{i}]")
    lists = {p["key"] for p in params if p["type"] == "list"}
    texts = {p["key"] for p in params if p["type"] == "text"} | RESERVED_KEYS
    for path in sorted(skeleton.get("files", {})):
        errors += check_path(path, f"skeleton.files.{path}")
        try:
            render.compile_template(skeleton["files"][path], texts, lists)
        except render.TemplateError as exc:
            errors.append(f"skeleton.files.{path}: {exc}")
    r = spec.get("rules", {})
    for key in ("required", "allowed"):
        for i, g in enumerate(r.get(key, [])):
            errors += check_path(g, f"rules.{key}[{i}]", pattern=True)
    for key in ("extensions", "pairs", "lines"):
        for i, rule in enumerate(r.get(key, [])):
            errors += check_path(rule["files"], f"rules.{key}[{i}].files", pattern=True)
    for i, rule in enumerate(r.get("pairs", [])):
        errors += check_path(rule["needs"].replace("{stem}", "x"), f"rules.pairs[{i}].needs")
    for i, rule in enumerate(r.get("lines", [])):
        errors += check_pattern(rule["pattern"], f"rules.lines[{i}].pattern")
    for i, rule in enumerate(r.get("manifests", [])):
        errors += check_path(rule["file"], f"rules.manifests[{i}].file")
        errors += check_schema(rule["schema"], f"rules.manifests[{i}].schema")
    for i, g in enumerate(spec.get("materialize", {}).get("include", [])):
        errors += check_path(g, f"materialize.include[{i}]", pattern=True)
    return errors


def problems(spec: Any) -> list:
    """Every problem of a layout spec (plain values), schema first, then the rules in code."""
    errors = validate(spec, layout_schema())
    return errors or _semantic(spec)


def parse(text: str, origin: str = "layout.yaml") -> dict:
    """The spec in ``text`` (YAML or JSON); SpecError naming ``origin`` and every problem otherwise."""
    if len(text.encode()) > MAX_SPEC_BYTES:
        raise SpecError(f"{origin}: larger than {MAX_SPEC_BYTES // 1024} KiB")
    try:
        spec = load_yaml(text)
    except ValueError:
        raise SpecError(f"{origin}: not valid YAML") from None
    return from_value(spec, origin)


def from_value(spec: Any, origin: str) -> dict:
    """``spec`` (already plain values, e.g. from JSON) checked; SpecError otherwise."""
    errors = problems(spec)
    if errors:
        raise SpecError(f"{origin} is not a valid layout:\n" + "\n".join(f"  - {e}" for e in errors))
    return spec


def dumps(spec: dict) -> str:
    """The spec as JSON (what kaos-lake serves)."""
    return json.dumps(spec, indent=2, sort_keys=True)


def read(path: pathlib.Path, origin: Optional[str] = None) -> dict:
    """The spec in a ``layout.yaml`` file, or in the ``layout.yaml`` of a folder."""
    path = pathlib.Path(path)
    if path.is_dir():
        path = path / "layout.yaml"
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        raise SpecError(f"cannot read {path}: {exc}") from None
    return parse(text, origin or str(path))
