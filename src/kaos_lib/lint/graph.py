"""The step graph of a pipeline.py, as JSON, for the editor's read-only graph view (`kaosctl lint --graph`).

Why: the editor must draw the same steps and dependencies the linter reads, not a second reading of the file. The
graph comes from `pipeline_reader` (static: the file is parsed, never run). A step the file builds in a loop or a
condition is marked `dynamic`: its place in the graph cannot be known without running the code, so it is shown, not
wired. A dependency the file writes in a form the reader cannot follow is listed in `unresolved`, never guessed.
"""
from __future__ import annotations

import ast
import json
import pathlib
from typing import Optional

from .constants import PIPELINE_FILE, RULESET_VERSION
from .engine import MissingPipeline
from .pipeline_reader import UNKNOWN, Block, PipelineFacts, Step, _callee, read_pipeline
from .source import TooLarge, buffer_source, parse_python, read_text

# The shape of this document. Bump when a field an editor reads changes meaning or goes away.
GRAPH_VERSION = 1


def _pipeline_name(block: Block) -> Optional[str]:
    """The literal name given to `pipeline("name")`, or None."""
    for item in block.node.items:
        call = item.context_expr
        if isinstance(call, ast.Call) and call.args and isinstance(call.args[0], ast.Constant) \
                and isinstance(call.args[0].value, str) and _callee(call) is not None:
            return call.args[0].value
    return None


def _node(facts: PipelineFacts, step: Step, index: int) -> dict:
    span = facts.src.span(step.call)
    name = step.name if isinstance(step.name, str) else None
    return {
        "id": f"s{index}", "name": name, "variable": step.var, "line": span.line, "range": span.to_dict(),
        "dynamic": step.dynamic,
        "gpu": None if step.is_gpu is None else step.is_gpu,
        "kind": _text(step.value("kind", None)),
        "walltime": _text(step.value("walltime", None)),
        "resumable": _text(step.value("resumable", None)),
        "disk": _text(step.value("disk", None)),
    }


def _text(value):
    return None if value is None or value is UNKNOWN else value if isinstance(value, (str, bool, int)) else None


def _needs(step: Step) -> list:
    """The elements of needs=[...]: ('var', name), or ('other', node) for anything else."""
    node = step.node("needs")
    if not isinstance(node, (ast.List, ast.Tuple)):
        return [] if node is None else [("other", node)]
    return [("var", el.id) if isinstance(el, ast.Name) else ("other", el) for el in node.elts]


def _block(facts: PipelineFacts, block: Block, start: int) -> dict:
    nodes = [_node(facts, s, start + i) for i, s in enumerate(block.steps)]
    by_var = {n["variable"]: n["id"] for n, s in zip(nodes, block.steps) if n["variable"] and not s.dynamic}
    edges, unresolved = [], []
    for node, step in zip(nodes, block.steps):
        for kind, ref in ([] if step.dynamic else _needs(step)):
            if kind == "var" and ref in by_var:
                edges.append({"from": by_var[ref], "to": node["id"]})
            else:
                unresolved.append({"step": node["id"], "line": facts.src.span(ref if kind == "other" else step.call).line,
                                   "reason": f"needs {ref!r} is not a step defined above" if kind == "var"
                                   else "needs holds something other than step variables"})
    return {"name": _pipeline_name(block), "line": facts.src.span(block.node).line, "nodes": nodes, "edges": edges,
            "unresolved": unresolved}


def build_graph(root, pipeline_file: str = PIPELINE_FILE, pipeline_text: Optional[str] = None) -> dict:
    """The graph of `root/pipeline_file`: one entry per `with pipeline(...)` block, each with nodes and edges.

    Raises MissingPipeline when the folder or the file is missing, unreadable, too large or not valid Python (the
    linter reports those as L-E00; the graph has nothing to draw).
    """
    root = pathlib.Path(root)
    if not root.is_dir():
        raise MissingPipeline(f"{root} is not a folder")
    try:
        src = read_text(root, root / pipeline_file, pipeline_file) if pipeline_text is None \
            else buffer_source(pipeline_text, pipeline_file)
    except TooLarge:
        raise MissingPipeline(f"{pipeline_file} is too large to read") from None
    if src is None:
        raise MissingPipeline(f"{pipeline_file} was not found (or is not a text file)")
    if parse_python(src) is None:
        raise MissingPipeline(f"{pipeline_file} is not valid Python, so it cannot be read")
    facts, blocks, count = read_pipeline(src), [], 0
    for block in facts.blocks:
        blocks.append(_block(facts, block, count))
        count += len(block.steps)
    return {"graph_version": GRAPH_VERSION, "ruleset_version": RULESET_VERSION, "file": src.rel, "pipelines": blocks}


def graph_json(root, pipeline_file: str = PIPELINE_FILE, pipeline_text: Optional[str] = None) -> str:
    """The graph as JSON text: two-space indent, fixed key order, a final newline."""
    return json.dumps(build_graph(root, pipeline_file, pipeline_text), indent=2, ensure_ascii=False) + "\n"
