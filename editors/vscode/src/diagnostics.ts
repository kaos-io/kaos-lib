// Findings of the linter -> the data of editor diagnostics.
// Why: the mapping is the contract between `kaosctl lint --format json` and what the user sees; it is pure so a
// change to it is tested without VS Code, and the editor shows exactly the findings the PR check reports.

import { Finding, Report, Skipped } from "./report";

export type Severity = "error" | "warning" | "information";

export interface MappedDiagnostic {
  file: string;            // relative to the folder the check ran in
  startLine: number;       // 0-based, as VS Code counts
  startCharacter: number;
  endLine: number;
  endCharacter: number;
  severity: Severity;
  message: string;         // the message, then the fix hint
  rule: string;
  doc: string;             // the rule's page; the editor makes the rule id a link to it
  fix: string;
}

const SEVERITY: Record<Finding["level"], Severity> = { error: "error", warning: "warning", info: "information" };

/** One finding as a diagnostic. Positions go from the report's 1-based lines and columns to 0-based. */
export function mapFinding(f: Finding): MappedDiagnostic {
  const startLine = Math.max(0, f.range.start.line - 1);
  const startCharacter = Math.max(0, f.range.start.column - 1);
  let endLine = Math.max(startLine, f.range.end.line - 1);
  let endCharacter = Math.max(0, f.range.end.column - 1);
  // An empty range is invisible in the editor: widen it by one character so the squiggle shows.
  if (endLine === startLine && endCharacter <= startCharacter) { endCharacter = startCharacter + 1; }
  if (endLine < startLine) { endLine = startLine; }
  return {
    file: f.file, startLine, startCharacter, endLine, endCharacter, severity: SEVERITY[f.level],
    message: `${f.message}\nFix: ${f.fix}`, rule: f.rule, doc: f.doc, fix: f.fix,
  };
}

/** The diagnostics of a report, grouped by file (the files with findings only). */
export function mapReport(report: Report): Map<string, MappedDiagnostic[]> {
  const byFile = new Map<string, MappedDiagnostic[]>();
  for (const f of report.findings) {
    const list = byFile.get(f.file) ?? [];
    list.push(mapFinding(f));
    byFile.set(f.file, list);
  }
  return byFile;
}

/** One line per rule that did not run: shown in the output, never counted as passed (the skipped rule is not a pass). */
export function describeSkipped(skipped: Skipped[]): string[] {
  return skipped.map((s) => `skipped ${s.rule} ${s.name}: ${s.reason}`);
}

/** The status bar text: errors and warnings, and a mark when rules were skipped. */
export function statusText(report: Report): string {
  const { errors, warnings, skipped } = report.summary;
  const base = `KAOS: ${errors} error${errors === 1 ? "" : "s"}, ${warnings} warning${warnings === 1 ? "" : "s"}`;
  return skipped > 0 ? `${base}, ${skipped} skipped` : base;
}

/**
 * The skipped-rule lines to print now: all of them when they differ from what was printed last (`previous`, the
 * lines joined by newlines), none when they are the same. Keeps the output panel quiet on repeated checks.
 */
export function skippedToPrint(previous: string, skipped: string[]): string[] {
  return skipped.join("\n") === previous ? [] : skipped;
}
