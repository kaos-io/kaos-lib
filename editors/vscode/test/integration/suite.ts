// Runs inside VS Code. A tiny runner (no test framework): each check throws on failure; run() rejects if any did.
import * as assert from "assert";
import * as vscode from "vscode";

const EXTENSION_ID = "kaos-io.kaos-pipeline";
const WAIT_MS = 30_000;

async function until<T>(what: string, probe: () => T | undefined | Promise<T | undefined>): Promise<T> {
  const end = Date.now() + WAIT_MS;
  for (;;) {
    const v = await probe();
    if (v !== undefined) { return v; }
    if (Date.now() > end) { throw new Error(`timed out waiting for ${what}`); }
    await new Promise((r) => setTimeout(r, 250));
  }
}

async function pipelineDoc(): Promise<vscode.TextDocument> {
  const files = await vscode.workspace.findFiles("pipeline.py");
  return vscode.workspace.openTextDocument(files[0]);
}

const kaosChecks: Record<string, () => Promise<void>> = {
  async should_activate_and_register_commands_in_a_kaos_folder() {
    await vscode.extensions.getExtension(EXTENSION_ID)!.activate();
    const commands = await vscode.commands.getCommands(true);
    for (const c of ["kaos.checkPipeline", "kaos.showStepGraph", "kaos.signIn"]) { assert.ok(commands.includes(c), c); }
  },
  async should_show_the_finding_for_walltime_as_a_diagnostic_with_a_doc_link() {
    const doc = await pipelineDoc();
    const d = await until("L-E06 diagnostic", () => vscode.languages.getDiagnostics(doc.uri).find((x) => typeof x.code === "object" && x.code.value === "L-E06"));
    assert.equal(d.severity, vscode.DiagnosticSeverity.Error);
    assert.match(d.message, /Fix: Use hpc_time_limit/);
    assert.match(String(typeof d.code === "object" ? d.code.target : ""), /L-E06\.html$/);
  },
  async should_offer_the_rename_quick_fix_and_apply_it() {
    const doc = await pipelineDoc();
    const editor = await vscode.window.showTextDocument(doc);
    const d = vscode.languages.getDiagnostics(doc.uri).find((x) => typeof x.code === "object" && x.code.value === "L-E06")!;
    const actions = await vscode.commands.executeCommand<vscode.CodeAction[]>("vscode.executeCodeActionProvider", doc.uri, d.range, vscode.CodeActionKind.QuickFix.value);
    const fix = actions.find((a) => a.title === "Rename 'walltime' to 'hpc_time_limit'");
    assert.ok(fix, "the rename quick fix is offered");
    await vscode.workspace.applyEdit(fix!.edit!);
    assert.ok(editor.document.getText().includes('hpc_time_limit="12h"'));
    assert.ok(!editor.document.getText().includes("walltime"));
  },
  async should_lint_unsaved_text_without_a_save() {
    const doc = await pipelineDoc();
    const edit = new vscode.WorkspaceEdit();
    edit.insert(doc.uri, new vscode.Position(doc.lineCount, 0), '\n    step("zz", disk="20 GB")\n');
    await vscode.workspace.applyEdit(edit);
    assert.ok(doc.isDirty, "the buffer is unsaved");
    await until("a finding for the unsaved line", () => vscode.languages.getDiagnostics(doc.uri).find((x) => /disk='20 GB'/.test(x.message)));
  },
  async should_complete_values_from_the_schema_after_resumable_equals() {
    const doc = await pipelineDoc();
    const edit = new vscode.WorkspaceEdit();
    edit.insert(doc.uri, new vscode.Position(doc.lineCount, 0), '\nx = step("t", gpu=True, resumable=');
    await vscode.workspace.applyEdit(edit);
    const end = doc.positionAt(doc.getText().length);
    const list = await vscode.commands.executeCommand<vscode.CompletionList>("vscode.executeCompletionItemProvider", doc.uri, end);
    const labels = list.items.map((i) => (typeof i.label === "string" ? i.label : i.label.label));
    assert.ok(["True", "False", '"20m"', '"1h"'].every((l) => labels.includes(l)), labels.join(","));
  },
  async should_open_the_step_graph_without_error() {
    await vscode.commands.executeCommand("kaos.showStepGraph");
  },
};

const otherChecks: Record<string, () => Promise<void>> = {
  async should_stay_inactive_in_an_unrelated_folder() {
    await new Promise((r) => setTimeout(r, 3000));   // the extension activates on pipeline.py, then must decline
    const commands = await vscode.commands.getCommands(true);
    assert.ok(!commands.includes("kaos.checkPipeline"), "no KAOS command is registered");
    const doc = await pipelineDoc();
    assert.equal(vscode.languages.getDiagnostics(doc.uri).length, 0);
  },
};

export async function run(): Promise<void> {
  const checks = process.env.KAOS_IT_MODE === "kaos" ? kaosChecks : otherChecks;
  const failures: string[] = [];
  for (const [name, fn] of Object.entries(checks)) {
    try { await fn(); console.log(`ok - ${name}`); } catch (e) { failures.push(name); console.log(`not ok - ${name}: ${(e as Error).message}`); }
  }
  if (failures.length) { throw new Error(`${failures.length} integration check(s) failed: ${failures.join(", ")}`); }
}
