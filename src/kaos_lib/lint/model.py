"""The report: findings, skipped rules and the JSON they serialise to.

Why: every surface (the PR gate, `kaosctl lint`, later the console and the editor) must print the same bytes for the
same input, so the serialisation lives in one place and is deterministic (fixed key order, sorted findings).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

ERROR, WARNING, INFO = "error", "warning", "info"
LEVEL_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}


class MixedRulesetVersions(ValueError):
    """Reports made by different rule-set versions were combined: findings would not be comparable."""


@dataclass(frozen=True)
class Span:
    """A range in a file: 1-based line and column, the end column exclusive."""
    line: int
    column: int
    end_line: int
    end_column: int

    def to_dict(self) -> dict:
        return {"start": {"line": self.line, "column": self.column},
                "end": {"line": self.end_line, "column": self.end_column}}

    @staticmethod
    def from_dict(d: dict) -> "Span":
        return Span(d["start"]["line"], d["start"]["column"], d["end"]["line"], d["end"]["column"])


@dataclass(frozen=True)
class Finding:
    """One problem found: which rule, how serious, where, what it means and how to fix it."""
    rule: str
    name: str
    level: str
    file: str
    span: Span
    message: str
    fix: str
    doc: str

    def sort_key(self) -> tuple:
        return (self.file, self.span.line, self.span.column, LEVEL_ORDER[self.level], self.rule, self.message)

    def to_dict(self) -> dict:
        return {"rule": self.rule, "name": self.name, "level": self.level, "file": self.file,
                "range": self.span.to_dict(), "message": self.message, "fix": self.fix, "doc": self.doc}

    @staticmethod
    def from_dict(d: dict) -> "Finding":
        return Finding(d["rule"], d["name"], d["level"], d["file"], Span.from_dict(d["range"]), d["message"],
                       d["fix"], d["doc"])


@dataclass(frozen=True)
class Skipped:
    """A rule that did not run, and why: never reported as passed."""
    rule: str
    name: str
    reason: str
    doc: str

    def to_dict(self) -> dict:
        return {"rule": self.rule, "name": self.name, "reason": self.reason, "doc": self.doc}

    @staticmethod
    def from_dict(d: dict) -> "Skipped":
        return Skipped(d["rule"], d["name"], d["reason"], d["doc"])


@dataclass
class Report:
    """The result of one run: findings (sorted), skipped rules, and the facts the run used."""
    ruleset_version: str
    catalogue: dict
    findings: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

    def count(self, level: str) -> int:
        return sum(1 for f in self.findings if f.level == level)

    @property
    def errors(self) -> int:
        return self.count(ERROR)

    def to_dict(self) -> dict:
        return {
            "ruleset_version": self.ruleset_version,
            "catalogue": self.catalogue,
            "summary": {"errors": self.count(ERROR), "warnings": self.count(WARNING), "infos": self.count(INFO),
                        "skipped": len(self.skipped)},
            "findings": [f.to_dict() for f in sorted(self.findings, key=Finding.sort_key)],
            "skipped": [s.to_dict() for s in sorted(self.skipped, key=lambda s: s.rule)],
        }

    def to_json(self) -> str:
        """The report as JSON text: two-space indent, the fixed key order of to_dict, a final newline."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    @staticmethod
    def from_dict(d: dict) -> "Report":
        return Report(d["ruleset_version"], d["catalogue"], [Finding.from_dict(f) for f in d["findings"]],
                      [Skipped.from_dict(s) for s in d["skipped"]])

    @staticmethod
    def from_json(text: str) -> "Report":
        return Report.from_dict(json.loads(text))


def merge_reports(reports: list, ruleset_version: Optional[str] = None) -> Report:
    """Combine reports into one; refuses reports from different rule-set versions (PRD-CONSOLE-1682 CON-13)."""
    versions = {r.ruleset_version for r in reports}
    if ruleset_version is not None:
        versions.add(ruleset_version)
    if len(versions) > 1:
        raise MixedRulesetVersions(
            f"reports come from different rule-set versions ({', '.join(sorted(versions))}); "
            f"run every part with the same kaos-lib")
    merged = Report(next(iter(versions)), reports[0].catalogue if reports else {})
    for r in reports:
        merged.findings += r.findings
        merged.skipped += r.skipped
    return merged
