import assert from "node:assert/strict";
import { test } from "node:test";
import { mapReport } from "../src/diagnostics";
import { quickFixesFor } from "../src/quickfix";
import { parseReport } from "../src/report";
import { parseSchema } from "../src/schema";
import { bundledSchemaText, fixture } from "./helpers";

const renamed = parseSchema(bundledSchemaText()).step.renamed_arguments;
const source = fixture("pipeline.py").split("\n");
const walltime = mapReport(parseReport(fixture("report.json"))).get("pipeline.py")!.find((d) => d.rule === "L-E06")!;
const textAtStart = source[walltime.startLine].slice(walltime.startCharacter);

test("should_rename_walltime_to_walltime", () => {
  const fixes = quickFixesFor(walltime, textAtStart, renamed);
  assert.equal(fixes.length, 1);
  assert.equal(fixes[0].title, "Rename 'walltime' to 'walltime'");
  const e = fixes[0].edit;
  assert.equal(source[e.startLine].slice(0, e.startCharacter) + e.newText + source[e.endLine].slice(e.endCharacter),
    source[4].replace("walltime", "walltime"));
});

test("should_replace_only_the_argument_name_and_keep_the_value", () => {
  const e = quickFixesFor(walltime, textAtStart, renamed)[0].edit;
  assert.equal(e.endCharacter - e.startCharacter, "walltime".length);
});

test("should_offer_nothing_for_other_rules", () => {
  assert.deepEqual(quickFixesFor({ ...walltime, rule: "L-W02" }, textAtStart, renamed), []);
});

test("should_offer_nothing_for_an_argument_without_a_known_rename", () => {
  assert.deepEqual(quickFixesFor(walltime, 'bogus="1h")', renamed), []);
  assert.deepEqual(quickFixesFor(walltime, 'disk="20 GB")', renamed), []);
});

test("should_be_idempotent_once_the_name_is_fixed", () => {
  assert.deepEqual(quickFixesFor(walltime, 'walltime="12h")', renamed), []);
});

test("should_not_treat_a_prototype_property_as_a_rename", () => {
  assert.deepEqual(quickFixesFor(walltime, 'constructor="x")', renamed), []);
});
