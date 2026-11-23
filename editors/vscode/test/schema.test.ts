import assert from "node:assert/strict";
import { test } from "node:test";
import { SUPPORTED_SCHEMA_VERSION, Schema, analyzeStepContext, chooseSchema, completionsFor, hoverFor, parseSchema, stepCallNames } from "../src/schema";
import { bundledSchemaText } from "./helpers";

const schema: Schema = parseSchema(bundledSchemaText());
const names = (text: string) => completionsFor(schema, text).map((c) => c.label);

test("should_parse_the_bundled_schema_and_know_every_step_argument", () => {
  assert.equal(schema.schema_version, SUPPORTED_SCHEMA_VERSION);
  assert.deepEqual(schema.step.parameters.map((p) => p.name).slice(0, 3), ["name", "kind", "reads"]);
  assert.ok(schema.step.parameters.every((p) => p.doc.length > 20));
});

test("should_refuse_a_schema_of_an_unknown_version_and_garbage", () => {
  assert.throws(() => parseSchema(JSON.stringify({ schema_version: 99 })), /version 99/);
  assert.throws(() => parseSchema("not json"), /not JSON/);
  assert.throws(() => parseSchema("[]"), /not an object/);
});

test("should_offer_argument_names_inside_a_step_call", () => {
  const got = names('with pipeline("p") as p:\n    step("train", ');
  assert.ok(got.includes("gpu") && got.includes("idle_timeout") && !got.includes("walltime") && !got.includes("resumable"));
  assert.ok(!got.includes("name"), "name is already given as the first positional argument");
});

test("should_filter_argument_names_by_the_typed_prefix", () => {
  assert.deepEqual(names('step("t", idl'), ["idle_timeout"]);
});

test("should_not_offer_an_argument_that_was_already_given", () => {
  assert.ok(!names('step("t", gpu=True, ').includes("gpu"));
});

test("should_offer_the_schema_values_after_idle_timeout_equals", () => {
  const items = completionsFor(schema, 'step("train", gpu=True, idle_timeout=');
  assert.deepEqual(items.map((i) => i.label), ['"40m"', '"1h"', "0"]);
  assert.ok(items.every((i) => i.documentation.length > 10), "each value carries inline docs");
});

test("should_narrow_value_completions_by_what_is_typed_and_report_the_replace_length", () => {
  const items = completionsFor(schema, 'step("train", gpu=True, idle_timeout="4');
  assert.deepEqual(items.map((i) => i.label), ['"40m"']);
  assert.equal(items[0].replaceLength, 2);
});

test("should_offer_gpu_values", () => {
  assert.deepEqual(names("step('a', gpu="), ["True", "False"]);
});

test("should_offer_nothing_outside_a_step_call", () => {
  assert.deepEqual(names("x = foo(re"), []);
  assert.deepEqual(names('with pipeline("p") as p:\n    '), []);
  assert.deepEqual(names("step('a')\nfoo("), []);
});

test("should_offer_nothing_inside_a_list_argument_or_an_unknown_argument_value", () => {
  assert.deepEqual(names('step("a", needs=[b, '), []);
  assert.deepEqual(names('step("a", bogus='), []);
});

test("should_ignore_parentheses_commas_and_hashes_inside_strings_and_comments", () => {
  assert.ok(names('step("a(b,c", # a ) comment\n     ').includes("gpu"));
  assert.ok(names('step("a", disk="2),(", ').includes("gpu"));
  assert.ok(names('step("""x\n),""", ').includes("gpu"));
});

test("should_follow_an_import_alias_of_step", () => {
  const text = "from kubecore.authoring import pipeline, step as s\n";
  assert.ok(stepCallNames(text).has("s"));
  assert.ok(names(`${text}s("a", `).includes("gpu"));
  assert.deepEqual(names('s("a", '), [], "an alias that was never imported is not step()");
});

test("should_analyse_the_context_kind", () => {
  assert.deepEqual(analyzeStepContext('step("a", disk='), { kind: "value", param: "disk", prefix: "" });
  assert.equal(analyzeStepContext('step("a", disk=="x"').kind, "none", "== is a comparison, not a keyword");
  assert.equal(analyzeStepContext("nothing").kind, "none");
});

test("should_show_hover_docs_for_an_argument_name_and_its_value", () => {
  const before = 'with pipeline("p") as p:\n';
  const line = '    step("train", gpu=True, idle_timeout="40m")';
  const onName = hoverFor(schema, before, line, line.indexOf("idle_timeout") + 3);
  assert.ok(onName !== null && onName.markdown.includes("**idle_timeout**"));
  assert.equal(onName.start, line.indexOf("idle_timeout"));
  const onValue = hoverFor(schema, before, line, line.indexOf("True") + 1);
  assert.ok(onValue && onValue.markdown.includes("**gpu**"));
});

test("should_link_the_rule_pages_in_hover_docs_when_the_schema_has_their_address", () => {
  const line = 'step("a", gpu=True, idle_timeout="40m")';
  const at = line.indexOf("idle_timeout") + 2;
  const none = hoverFor(schema, "", line, at);
  assert.ok(none && !none.markdown.includes("]("), "the bundled schema has no docs address, so no link");
  const raw = JSON.parse(bundledSchemaText());
  raw.step.parameters.find((p: { name: string }) => p.name === "idle_timeout").links =
    [{ title: "L-W02", url: "https://docs.example/lint/L-W02.html" }];
  const h = hoverFor(parseSchema(JSON.stringify(raw)), "", line, at);
  assert.ok(h && h.markdown.includes("[L-W02](https://docs.example/lint/L-W02.html)"));
});

test("should_explain_an_argument_on_hover", () => {
  const line = 'step("a", gpu=True, idle_timeout="40m")';
  const h = hoverFor(schema, "", line, line.indexOf("idle_timeout") + 1);
  assert.ok(h && h.markdown.includes("idle_timeout"));
});

test("should_give_no_hover_on_ordinary_words", () => {
  assert.equal(hoverFor(schema, "", "x = compute(a, b)", 5), null);
  assert.equal(hoverFor(schema, "", 'step("a", gpu=True)', 1), null, "the step word itself is not an argument");
});

test("should_prefer_the_installed_schema_and_fall_back_with_a_reason", () => {
  const bundled = bundledSchemaText();
  assert.equal(chooseSchema({ text: bundled }, bundled).source, "kaosctl");
  const missing = chooseSchema({ error: "'kaosctl' was not found" }, bundled);
  assert.deepEqual([missing.source, missing.note], ["bundled", "'kaosctl' was not found"]);
  const newer = chooseSchema({ text: JSON.stringify({ schema_version: 2 }) }, bundled);
  assert.equal(newer.source, "bundled");
  assert.match(String(newer.note), /version 2/);
});
