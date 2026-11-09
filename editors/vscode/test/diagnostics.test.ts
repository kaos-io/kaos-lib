import assert from "node:assert/strict";
import { test } from "node:test";
import { skippedToPrint, describeSkipped, mapFinding, mapReport, statusText } from "../src/diagnostics";
import { parseReport } from "../src/report";
import { fixture } from "./helpers";

const report = parseReport(fixture("report.json"));

test("should_group_findings_by_file", () => {
  const byFile = mapReport(report);
  assert.deepEqual([...byFile.keys()].sort(), ["config/dataset.yaml", "pipeline.py"]);
  assert.equal(byFile.get("pipeline.py")!.length, 3);
});

test("should_convert_one_based_positions_to_zero_based", () => {
  const e06 = mapReport(report).get("pipeline.py")!.find((d) => d.rule === "L-E06")!;
  assert.deepEqual([e06.startLine, e06.startCharacter, e06.endLine, e06.endCharacter], [4, 53, 4, 67]);
});

test("should_map_levels_to_severities", () => {
  const sev = Object.fromEntries(report.findings.map((f) => [f.rule, mapFinding(f).severity]));
  assert.equal(sev["L-E06"], "error");
  assert.equal(sev["L-W02"], "warning");
  assert.equal(sev["L-I01"], "information");
});

test("should_carry_the_fix_hint_and_the_doc_link", () => {
  const d = mapFinding(report.findings.find((f) => f.rule === "L-E06")!);
  assert.match(d.message, /no argument 'walltime'/);
  assert.match(d.message, /\nFix: Use hpc_time_limit/);
  assert.match(d.doc, /^https:\/\/.*L-E06\.html$/);
});

test("should_widen_an_empty_range_so_it_is_visible", () => {
  const f = report.findings[0];
  const d = mapFinding({ ...f, range: { start: { line: 3, column: 5 }, end: { line: 3, column: 5 } } });
  assert.equal(d.endCharacter, d.startCharacter + 1);
});

test("should_never_produce_a_negative_position", () => {
  const d = mapFinding({ ...report.findings[0], range: { start: { line: 0, column: 0 }, end: { line: 0, column: 0 } } });
  assert.ok(d.startLine >= 0 && d.startCharacter >= 0 && d.endLine >= d.startLine);
});

test("should_report_skipped_rules_as_skipped_never_as_passed", () => {
  const lines = describeSkipped(report.skipped);
  assert.ok(lines.length > 0 && lines.every((l) => l.startsWith("skipped ")));
  assert.match(statusText(report), /skipped/);
});

test("should_summarise_counts_for_the_status_bar", () => {
  assert.match(statusText(report), /^KAOS: 1 error, 2 warnings/);
});

test("should_reject_a_report_that_is_not_the_contract", () => {
  assert.throws(() => parseReport("nope"), /did not print JSON/);
  assert.throws(() => parseReport("{}"), /summary is not an object|not an object/);
  const broken = JSON.parse(fixture("report.json"));
  broken.findings[0].level = "fatal";
  assert.throws(() => parseReport(JSON.stringify(broken)), /expected error, warning or info/);
});

test("should_map_the_same_report_to_the_same_diagnostics_each_time", () => {
  assert.deepEqual([...mapReport(report)], [...mapReport(parseReport(fixture("report.json")))]);
});

test("should_print_skipped_rules_once_and_again_only_when_they_change", () => {
  const lines = describeSkipped(report.skipped);
  assert.deepEqual(skippedToPrint("", lines), lines, "first time: print");
  assert.deepEqual(skippedToPrint(lines.join("\n"), lines), [], "same as before: quiet");
  assert.deepEqual(skippedToPrint(lines.join("\n"), lines.slice(1)), lines.slice(1), "changed: print the new set");
  assert.deepEqual(skippedToPrint("", []), [], "nothing skipped: nothing to print");
});
