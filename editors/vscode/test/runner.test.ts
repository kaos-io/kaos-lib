import assert from "node:assert/strict";
import { test } from "node:test";
import { Debouncer } from "../src/debounce";
import { checkArgs, explainFailure, producedReport, run } from "../src/runner";

test("should_build_the_check_arguments_with_and_without_a_context_file", () => {
  assert.deepEqual(checkArgs(undefined), ["lint", "--format", "json"]);
  assert.deepEqual(checkArgs("/p/ctx.yaml"), ["lint", "--context", "/p/ctx.yaml", "--format", "json"]);
});

test("should_return_stdout_and_exit_code_zero", async () => {
  const r = await run(process.execPath, ["-e", "console.log('hi')"], process.cwd());
  assert.deepEqual([r.code, r.stdout.trim()], [0, "hi"]);
});

test("should_return_a_non_zero_exit_code_with_the_output_instead_of_throwing", async () => {
  const r = await run(process.execPath, ["-e", "console.log('report'); process.exit(2)"], process.cwd());
  assert.equal(r.code, 2);
  assert.equal(r.stdout.trim(), "report");
  assert.equal(producedReport(r), true);
});

test("should_say_when_the_command_is_missing", async () => {
  const r = await run("kaosctl-does-not-exist-xyz", [], process.cwd());
  assert.equal(r.code, null);
  assert.match(explainFailure(r), /was not found.*kaos\.kaosctlPath/);
  assert.equal(producedReport(r), false);
});

test("should_treat_other_exit_codes_as_could_not_run", async () => {
  const r = await run(process.execPath, ["-e", "console.error('ERROR: boom'); process.exit(1)"], process.cwd());
  assert.equal(producedReport(r), false);
  assert.match(explainFailure(r), /exit code 1: ERROR: boom/);
});

test("should_not_pass_arguments_through_a_shell", async () => {
  const r = await run(process.execPath, ["-e", "console.log(process.argv[1])", "a; echo injected"], process.cwd());
  assert.equal(r.stdout.trim(), "a; echo injected");
});

test("should_stop_a_process_that_takes_too_long", async () => {
  const r = await run(process.execPath, ["-e", "setTimeout(()=>{},10000)"], process.cwd(), 200);
  assert.equal(r.code, null);
  assert.match(explainFailure(r), /did not finish in time/);
});

test("should_run_the_action_once_for_a_burst_of_events", async () => {
  const d = new Debouncer();
  let calls = 0;
  for (let i = 0; i < 5; i++) { d.schedule("k", 30, () => { calls++; }); }
  await new Promise((r) => setTimeout(r, 120));
  assert.equal(calls, 1);
  d.dispose();
});

test("should_keep_separate_keys_separate_and_cancel_on_dispose", async () => {
  const d = new Debouncer();
  const seen: string[] = [];
  d.schedule("a", 20, () => seen.push("a"));
  d.schedule("b", 20, () => seen.push("b"));
  d.schedule("c", 50, () => seen.push("c"));
  await new Promise((r) => setTimeout(r, 35));
  d.dispose();
  await new Promise((r) => setTimeout(r, 60));
  assert.deepEqual(seen.sort(), ["a", "b"]);
});
