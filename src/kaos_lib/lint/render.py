"""Human-readable forms of a report: plain text for a terminal and Markdown for a pull request comment.

Why: the JSON is the contract; these are views of it. Both are built from a Report (so a stored JSON report can be
rendered later without running the linter again) and are deterministic.
"""
from __future__ import annotations

from typing import Optional

from .model import ERROR, INFO, WARNING, Finding, Report

MAX_COMMENT_FINDINGS = 50   # a pull request comment is capped by GitHub; the rest is counted, not listed
_ICON = {ERROR: "❌", WARNING: "⚠️", INFO: "ℹ️"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def summary_line(report: Report) -> str:
    """'2 errors, 1 warning, 3 infos' (and the skipped rules when there are any)."""
    s = report.to_dict()["summary"]
    line = f"{_plural(s['errors'], 'error')}, {_plural(s['warnings'], 'warning')}, {_plural(s['infos'], 'info')}"
    return line + (f"; {_plural(s['skipped'], 'rule')} skipped" if s["skipped"] else "")


def status_description(report: Report) -> str:
    """The commit status text (GitHub caps it at 140 characters)."""
    return f"{summary_line(report)} (rule set {report.ruleset_version})"[:140]


def text(report: Report) -> str:
    """The report for a terminal."""
    out = []
    for f in sorted(report.findings, key=Finding.sort_key):
        out.append(f"{f.file}:{f.span.line}:{f.span.column}: {f.level} {f.rule} {f.name}: {f.message}")
        out.append(f"    fix: {f.fix}")
        out.append(f"    docs: {f.doc}")
    for s in report.skipped:
        out.append(f"skipped {s.rule} {s.name}: {s.reason}")
    out.append(f"{summary_line(report)}. Rule set {report.ruleset_version}; facts from: "
               f"{report.catalogue.get('source')}.")
    return "\n".join(out) + "\n"


def markdown(report: Report, file_link_base: Optional[str] = None) -> str:
    """The report as a Markdown section for a pull request comment.

    file_link_base, when given, is a URL prefix such as https://github.com/org/repo/blob/<sha>/ that turns each
    `file:line` into a link to that line.
    """
    findings = sorted(report.findings, key=Finding.sort_key)
    out = [f"#### Pipeline lint: {summary_line(report)}", ""]
    if not findings:
        out += ["No problems found.", ""]
    else:
        out += ["| | rule | where | what |", "|---|---|---|---|"]
        for f in findings[:MAX_COMMENT_FINDINGS]:
            where = f"`{f.file}:{f.span.line}`"
            if file_link_base:
                where = f"[{where}]({file_link_base}{f.file}#L{f.span.line})"
            what = f"{_cell(f.message)}<br>**Fix:** {_cell(f.fix)} [Details]({f.doc})"
            out.append(f"| {_ICON[f.level]} | [{f.rule}]({f.doc}) {f.name} | {where} | {what} |")
        if len(findings) > MAX_COMMENT_FINDINGS:
            out.append(f"\n…and {len(findings) - MAX_COMMENT_FINDINGS} more. Run `kaosctl lint` to see them all.")
        out.append("")
    if report.skipped:
        out += ["<details><summary>Rules that did not run</summary>", ""]
        out += [f"- `{s.rule}` {s.name}: {s.reason}" for s in report.skipped]
        out += ["", "</details>", ""]
    out.append(f"Rule set {report.ruleset_version}. Errors fail the `pipeline-lint` check; warnings and infos do "
               f"not. A clean report does not prove the pipeline is right: the check reads your files without "
               f"running them. Run it yourself with `kaosctl lint`.")
    return "\n".join(out) + "\n"


def _cell(value: str) -> str:
    """Text safe inside a Markdown table cell."""
    return value.replace("|", "\\|").replace("\n", " ")
