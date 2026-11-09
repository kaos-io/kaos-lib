"""The engine: reads a repository, runs every registered rule and builds the report.

Why: one function, `lint_project`, is the single path every surface uses, so the gate, `kaosctl lint` and later the
console see the same findings for the same files, catalogue and rule-set version. It never imports or runs client
code: files are read as text and parsed.
"""
from __future__ import annotations

import pathlib
from typing import Optional

from . import rules_errors, rules_infos, rules_warnings  # noqa: F401  (importing registers the rules)
from .catalogue import Catalogue, default_catalogue
from .constants import MAX_FILE_BYTES, PIPELINE_FILE, RULESET_VERSION
from .model import ERROR, Finding, Report, Skipped, Span
from .pipeline_reader import read_pipeline
from .project_reader import config_sections, dataset_default
from .registry import (REQUIRES_CLASSES, REQUIRES_CONTINUATIONS, REQUIRES_HPC, RULES, Hit, LintContext, Rule)
from .source import TooLarge, parse_python, read_text

NOT_ANALYSABLE = Rule("L-E00", "NotAnalysable", ERROR, "Fix the file so it can be read, then run the check again.",
                      lambda ctx: ())
ALL_RULES = [NOT_ANALYSABLE] + RULES


class MissingPipeline(Exception):
    """The repository root does not exist."""


def _missing_facts(rule: Rule, catalogue: Catalogue) -> Optional[str]:
    """Why the rule cannot run with this catalogue, or None when everything it needs is there."""
    if rule.inactive:
        return rule.inactive
    for need in rule.requires:
        if need == REQUIRES_CLASSES and catalogue.classes is None:
            return "the catalogue has no list of compute classes (give --context, the project's platform context)"
        if need == REQUIRES_HPC and catalogue.hpc is None:
            return catalogue.hpc_note or "the catalogue has no HPC (Slurm) site facts"
        if need == REQUIRES_CONTINUATIONS and catalogue.max_continuations is None:
            return "the catalogue has no continuation cap"
    return None


def _finding(rule: Rule, hit: Hit) -> Finding:
    return Finding(rule.id, rule.name, rule.level, hit.file, hit.span, hit.message, hit.fix or rule.fix, rule.doc)


def _not_analysable(message: str, file: str = PIPELINE_FILE, span: Span = Span(1, 1, 1, 1)) -> Finding:
    return _finding(NOT_ANALYSABLE, Hit(file, span, message))


def lint_project(root, catalogue: Optional[Catalogue] = None, pipeline_file: str = PIPELINE_FILE) -> Report:
    """Lint the pipeline at `root/pipeline_file` and the files around it.

    Static: nothing of the repository is imported or run. Returns a Report; a file that cannot be read or parsed
    becomes an L-E00 error finding rather than an exception.
    """
    root = pathlib.Path(root)
    if not root.is_dir():
        raise MissingPipeline(f"{root} is not a folder")
    catalogue = catalogue or default_catalogue()
    report = Report(RULESET_VERSION, catalogue.to_dict())
    try:
        src = read_text(root, root / pipeline_file, pipeline_file)
    except TooLarge:
        report.findings.append(_not_analysable(
            f"{pipeline_file} is larger than {MAX_FILE_BYTES // 1024} KiB, more than the check reads. Split the "
            f"pipeline's code into your steps."))
        return _with_skips(report, catalogue)
    if src is None:
        report.findings.append(_not_analysable(f"{pipeline_file} was not found (or is not a text file)."))
        return _with_skips(report, catalogue)
    if parse_python(src) is None:
        report.findings.append(_not_analysable(f"{pipeline_file} is not valid Python, so it cannot be read.",
                                               src.rel))
        return _with_skips(report, catalogue)
    ctx = LintContext(root, read_pipeline(src), catalogue, config_sections(root), dataset_default(root))
    for rule in RULES:
        if _missing_facts(rule, catalogue) is None:
            report.findings += [_finding(rule, h) for h in rule.check(ctx)]
    report.findings = _unique(report.findings)
    return _with_skips(report, catalogue)


def _unique(findings: list) -> list:
    """Drop findings that repeat (two paths of one rule can reach the same place)."""
    seen, out = set(), []
    for f in findings:
        key = (f.rule, f.file, f.span, f.message)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def _with_skips(report: Report, catalogue: Catalogue) -> Report:
    report.skipped = [Skipped(r.id, r.name, reason, r.doc) for r in RULES
                      for reason in [_missing_facts(r, catalogue)] if reason]
    return report
