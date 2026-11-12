"""Reads the structure of pipeline.py from its syntax tree: the `with pipeline(...)` blocks, the step() calls and
every call or dictionary the raw-Hera rules look at.

Why: rules should ask "which steps are there and what did they get?" and never walk syntax trees themselves, so one
change here keeps every rule consistent. Nothing here runs the file: values are read only when they are literals.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Optional

from .constants import STEP_PARAMS
from .source import SourceFile

UNKNOWN = object()   # a value that is not a literal: the rule cannot judge it and stays silent


def literal(node: Optional[ast.AST]):
    """The literal value of a node, or UNKNOWN. Uses ast.literal_eval, which never executes anything."""
    if node is None:
        return UNKNOWN
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return UNKNOWN


@dataclass
class Step:
    """One step(...) call."""
    call: ast.Call
    var: Optional[str]                  # the variable it is assigned to, when assigned directly
    dynamic: bool                       # inside a loop, condition, function or expression: order is not static
    args: dict = field(default_factory=dict)       # parameter name -> the argument's syntax node
    unknown_keywords: list = field(default_factory=list)   # keyword nodes the library does not accept
    opaque: bool = False                # *args or **kwargs: the arguments cannot be read
    extra_positional: list = field(default_factory=list)   # arguments after the name given by position

    def node(self, key: str) -> Optional[ast.AST]:
        return self.args.get(key)

    def value(self, key: str, default=None):
        """The literal value of an argument, `default` when it was not given, UNKNOWN when it is not a literal."""
        if key not in self.args:
            return default
        return literal(self.args[key])

    @property
    def name(self):
        v = self.value("name", UNKNOWN)
        return v if isinstance(v, str) else UNKNOWN

    @property
    def is_gpu(self) -> Optional[bool]:
        """True or False when `gpu=` is a literal (or absent); None when it cannot be known."""
        v = self.value("gpu", False)
        return None if v is UNKNOWN else bool(v)


@dataclass
class Block:
    """One `with pipeline(...) as p:` block."""
    node: ast.With
    steps: list = field(default_factory=list)


@dataclass
class PipelineFacts:
    """Everything the rules read from pipeline.py."""
    src: SourceFile
    blocks: list = field(default_factory=list)
    calls: list = field(default_factory=list)       # every ast.Call in the file
    dicts: list = field(default_factory=list)       # every ast.Dict in the file
    bound_names: set = field(default_factory=set)   # every name the file assigns, defines or imports

    @property
    def steps(self) -> list:
        return [s for b in self.blocks for s in b.steps]


def _import_aliases(tree: ast.AST) -> tuple:
    """Local names of `step` and `pipeline` imported from the authoring module (`import step as s` is followed)."""
    steps, pipelines = {"step"}, {"pipeline"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[-1] == "authoring":
            for a in node.names:
                if a.name == "step":
                    steps.add(a.asname or a.name)
                if a.name == "pipeline":
                    pipelines.add(a.asname or a.name)
    return steps, pipelines


def _callee(call: ast.Call) -> Optional[str]:
    """The called name (`step`) or attribute (`authoring.step`), else None."""
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _bound_names(tree: ast.AST) -> set:
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.arg):
            names.add(n.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in n.names)
    return names


def _make_step(call: ast.Call, var: Optional[str], dynamic: bool) -> Step:
    step = Step(call, var, dynamic)
    for i, arg in enumerate(call.args):
        if isinstance(arg, ast.Starred):
            step.opaque = True
        elif i == 0:
            step.args["name"] = arg
        else:                       # everything after the name is keyword-only
            step.extra_positional.append(arg)
    for kw in call.keywords:
        if kw.arg is None:
            step.opaque = True
        elif kw.arg in STEP_PARAMS:
            step.args[kw.arg] = kw.value
        else:
            step.unknown_keywords.append(kw)
    return step


def _steps_in(stmt: ast.stmt, step_names: set) -> list:
    """The step() calls of one statement of a pipeline block: a plain `x = step(...)` or `step(...)` is static, a
    step() anywhere deeper (loop, condition, function, list) is dynamic."""
    value = getattr(stmt, "value", None)
    direct = isinstance(value, ast.Call) and _callee(value) in step_names
    if direct and isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
        return [_make_step(value, stmt.targets[0].id, False)]
    if direct and isinstance(stmt, ast.Expr):
        return [_make_step(value, None, False)]
    return [_make_step(c, None, True) for c in ast.walk(stmt)
            if isinstance(c, ast.Call) and _callee(c) in step_names and (c.args or c.keywords)]


def read_pipeline(src: SourceFile) -> PipelineFacts:
    """The facts of a parsed pipeline.py. `src.tree` must be set."""
    tree = src.tree
    facts = PipelineFacts(src, bound_names=_bound_names(tree))
    step_names, pipeline_names = _import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            facts.calls.append(node)
        elif isinstance(node, ast.Dict):
            facts.dicts.append(node)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            if any(isinstance(i.context_expr, ast.Call) and _callee(i.context_expr) in pipeline_names
                   for i in node.items):
                block = Block(node)
                for stmt in node.body:
                    block.steps += _steps_in(stmt, step_names)
                facts.blocks.append(block)
    facts.blocks.sort(key=lambda b: b.node.lineno)
    return facts
