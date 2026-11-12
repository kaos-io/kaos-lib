// The extension's entry: wires the pure parts to VS Code. Keep logic out of here; this file only connects.

import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";
import { describeSession, isHttpsUrl, readIssuer, sessionFilePath } from "./auth";
import { Debouncer } from "./debounce";
import { DATASET_CONFIG_FILE, FolderReader, PIPELINE_FILE, detectKaosRepo } from "./detect";
import { MappedDiagnostic, describeSkipped, mapReport, skippedToPrint, statusText } from "./diagnostics";
import { renderGraphHtml } from "./graphHtml";
import { Report, parseGraph, parseReport } from "./report";
import { LOGIN_ARGS, SCHEMA_ARGS, checkArgs, explainFailure, graphArgs, producedReport, run } from "./runner";
import { Schema, SchemaChoice, chooseSchema, completionsFor, hoverFor } from "./schema";
import { VERSION_ARGS, downloadArgs, downloadedFile, updateNeeded } from "./update";

const DIAGNOSTIC_SOURCE = "KAOS";
const LOGIN_TIMEOUT_MS = 5 * 60_000;
const ACCEPTED_ISSUERS_KEY = "kaos.acceptedIssuers";
const SKIPPED_UPDATE_KEY = "kaos.skippedUpdate";
const VERSION_TIMEOUT_MS = 30_000;
const DOWNLOAD_TIMEOUT_MS = 120_000;
const BUNDLED_SCHEMA = path.join("resources", "step-schema.json");
const PIPELINE_SELECTOR: vscode.DocumentSelector = { language: "python", pattern: "**/pipeline.py" };

class State {
  readonly output = vscode.window.createOutputChannel("KAOS");
  readonly diagnostics = vscode.languages.createDiagnosticCollection("kaos");
  readonly status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  readonly debounce = new Debouncer();
  readonly folders = new Map<string, vscode.WorkspaceFolder>();   // KAOS folders by fsPath
  readonly skippedShown = new Map<string, string>();               // skipped-rule lines last printed per folder
  readonly runIds = new Map<string, number>();                      // newest check per folder; older results are dropped
  schema: SchemaChoice | undefined;
  graphPanel: vscode.WebviewPanel | undefined;
  graphFolder: vscode.WorkspaceFolder | undefined;
  constructor(readonly context: vscode.ExtensionContext) {}
}

function settings(folder?: vscode.WorkspaceFolder) {
  const cfg = vscode.workspace.getConfiguration("kaos", folder);
  return {
    kaosctl: cfg.get<string>("kaosctlPath") || "kaosctl",
    contextFile: cfg.get<string>("contextFile") || "",
    delay: cfg.get<number>("checkDelayMs") ?? 1000,
  };
}

function folderReader(root: string): FolderReader {
  return {
    exists: async (rel) => fs.promises.stat(path.join(root, rel)).then((s) => s.isFile(), () => false),
    readHead: async (rel, max) => {
      try {
        const handle = await fs.promises.open(path.join(root, rel), "r");
        try {
          const buf = Buffer.alloc(max);
          const { bytesRead } = await handle.read(buf, 0, max, 0);
          return buf.subarray(0, bytesRead).toString("utf8");
        } finally { await handle.close(); }
      } catch { return undefined; }
    },
  };
}

function folderFor(state: State, uri?: vscode.Uri): vscode.WorkspaceFolder | undefined {
  const target = uri ?? vscode.window.activeTextEditor?.document.uri;
  const owner = target ? vscode.workspace.getWorkspaceFolder(target) : undefined;
  if (owner && state.folders.has(owner.uri.fsPath)) { return owner; }
  return state.folders.values().next().value;
}

// ------------------------------------------------------------------------------------------ schema

async function loadSchema(state: State, folder: vscode.WorkspaceFolder): Promise<void> {
  const bundled = fs.readFileSync(path.join(state.context.extensionPath, BUNDLED_SCHEMA), "utf8");
  const r = await run(settings(folder).kaosctl, SCHEMA_ARGS, folder.uri.fsPath, 15_000);
  const installed = r.code === 0 ? { text: r.stdout } : { error: explainFailure(r) };
  state.schema = chooseSchema(installed, bundled);
  const s = state.schema;
  state.output.appendLine(`Step suggestions: ${s.source} schema, rule set ${s.schema.ruleset_version}` + (s.note ? ` (${s.note})` : ""));
}

function schemaNow(state: State): Schema | undefined { return state.schema?.schema; }

function registerLanguageFeatures(state: State): vscode.Disposable[] {
  const completion = vscode.languages.registerCompletionItemProvider(PIPELINE_SELECTOR, {
    provideCompletionItems(doc, pos) {
      const schema = schemaNow(state);
      if (!schema) { return undefined; }
      const before = doc.getText(new vscode.Range(0, 0, pos.line, pos.character));
      return completionsFor(schema, before).map((c) => {
        const item = new vscode.CompletionItem(c.label, c.insertText.includes("=") ? vscode.CompletionItemKind.Property : vscode.CompletionItemKind.Value);
        item.detail = c.detail;
        item.documentation = new vscode.MarkdownString(c.documentation);
        item.insertText = c.isSnippet ? new vscode.SnippetString(c.insertText) : c.insertText;
        item.range = new vscode.Range(pos.translate(0, -c.replaceLength), pos);
        item.sortText = c.sortText;
        return item;
      });
    },
  }, "(", ",", "=", " ");
  const hover = vscode.languages.registerHoverProvider(PIPELINE_SELECTOR, {
    provideHover(doc, pos) {
      const schema = schemaNow(state);
      if (!schema) { return undefined; }
      const beforeLine = doc.getText(new vscode.Range(0, 0, pos.line, 0));
      const h = hoverFor(schema, beforeLine, doc.lineAt(pos.line).text, pos.character);
      if (!h) { return undefined; }
      const md = new vscode.MarkdownString(h.markdown);
      return new vscode.Hover(md, new vscode.Range(pos.line, h.start, pos.line, h.end));
    },
  });
  return [completion, hover];
}

// ------------------------------------------------------------------------------------------ check

function toVsDiagnostic(d: MappedDiagnostic): vscode.Diagnostic {
  const severity = d.severity === "error" ? vscode.DiagnosticSeverity.Error
    : d.severity === "warning" ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Information;
  const diag = new vscode.Diagnostic(new vscode.Range(d.startLine, d.startCharacter, d.endLine, d.endCharacter), d.message, severity);
  diag.source = DIAGNOSTIC_SOURCE;
  diag.code = { value: d.rule, target: vscode.Uri.parse(d.doc) };
  return diag;
}

function publish(state: State, folder: vscode.WorkspaceFolder, report: Report): void {
  const prefix = folder.uri.fsPath + path.sep;
  state.diagnostics.forEach((uri) => { if (uri.fsPath.startsWith(prefix)) { state.diagnostics.delete(uri); } });
  for (const [file, list] of mapReport(report)) {
    state.diagnostics.set(vscode.Uri.joinPath(folder.uri, file), list.map(toVsDiagnostic));
  }
  state.status.text = statusText(report);
  const skipped = describeSkipped(report.skipped);
  state.status.tooltip = [`Pipeline check, rule set ${report.ruleset_version}. Click to check again.`, ...skipped].join("\n");
  // The skipped rules are in the tooltip every time; the output panel gets them only when they change.
  for (const line of skippedToPrint(state.skippedShown.get(folder.uri.fsPath) ?? "", skipped)) { state.output.appendLine(line); }
  state.skippedShown.set(folder.uri.fsPath, skipped.join("\n"));
}

/** The text of the folder's pipeline.py when it is open with unsaved changes, else undefined (the file on disk is used). */
function dirtyPipelineText(folder: vscode.WorkspaceFolder): string | undefined {
  const file = path.join(folder.uri.fsPath, PIPELINE_FILE);
  return vscode.workspace.textDocuments.find((d) => d.isDirty && d.uri.fsPath === file)?.getText();
}

async function checkFolder(state: State, folder: vscode.WorkspaceFolder, announce: boolean): Promise<void> {
  const id = (state.runIds.get(folder.uri.fsPath) ?? 0) + 1;
  state.runIds.set(folder.uri.fsPath, id);
  const s = settings(folder);
  const ctxFile = s.contextFile ? path.resolve(folder.uri.fsPath, s.contextFile) : undefined;
  state.status.text = "$(sync~spin) KAOS: checking";
  const buffer = dirtyPipelineText(folder);
  const r = await run(s.kaosctl, checkArgs(ctxFile, buffer !== undefined), folder.uri.fsPath, undefined, buffer);
  if (state.runIds.get(folder.uri.fsPath) !== id) { return; }   // a newer check is running or finished
  if (!producedReport(r)) {
    const why = explainFailure(r);
    state.status.text = "$(warning) KAOS: check did not run";
    state.status.tooltip = why;
    state.output.appendLine(`Check did not run: ${why}`);
    if (announce) { void vscode.window.showErrorMessage(`KAOS check did not run: ${why}`); }
    return;
  }
  try {
    const report = parseReport(r.stdout);
    publish(state, folder, report);
    if (state.graphPanel && state.graphFolder === folder) { void refreshGraph(state, folder); }
    if (announce) {
      // The same JSON the pull request check produces, in full, for anyone who wants to compare or copy it.
      state.output.appendLine(r.stdout);
      state.output.show(true);
      const pipelineFile = path.join(folder.uri.fsPath, PIPELINE_FILE);
      const others = vscode.workspace.textDocuments.some((d) => d.isDirty && d.uri.fsPath !== pipelineFile && d.uri.fsPath.startsWith(folder.uri.fsPath + path.sep));
      if (others) { void vscode.window.showWarningMessage("KAOS checks pipeline.py as you see it, and your other files as saved: unsaved changes in them are not included."); }
      const n = report.summary;
      void vscode.window.showInformationMessage(`KAOS check: ${n.errors} errors, ${n.warnings} warnings, ${n.infos} infos` +
        (n.skipped ? `, ${n.skipped} checks skipped (see the KAOS output)` : "") + `. Rule set ${report.ruleset_version}.`);
    }
  } catch (e) {
    state.output.appendLine(`The check printed something unexpected: ${(e as Error).message}`);
    state.status.text = "$(warning) KAOS: unreadable report";
  }
}

// ------------------------------------------------------------------------------------------ graph

async function refreshGraph(state: State, folder: vscode.WorkspaceFolder): Promise<void> {
  const panel = state.graphPanel;
  if (!panel) { return; }
  const buffer = dirtyPipelineText(folder);
  const r = await run(settings(folder).kaosctl, graphArgs(buffer !== undefined), folder.uri.fsPath, undefined, buffer);
  if (r.code !== 0) {
    panel.webview.html = `<!DOCTYPE html><html><body><p>The step graph could not be drawn: ${escapeForText(r.code === null ? explainFailure(r) : r.stderr.trim() || explainFailure(r))}</p></body></html>`;
    return;
  }
  try {
    const nonce = Array.from({ length: 24 }, () => Math.floor(Math.random() * 36).toString(36)).join("");
    panel.webview.html = renderGraphHtml(parseGraph(r.stdout), nonce);
  } catch (e) { panel.webview.html = `<!DOCTYPE html><html><body><p>${escapeForText((e as Error).message)}</p></body></html>`; }
}

function escapeForText(t: string): string {
  return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function showGraph(state: State): Promise<void> {
  const folder = folderFor(state);
  if (!folder) { return; }
  state.graphFolder = folder;
  if (!state.graphPanel) {
    const panel = vscode.window.createWebviewPanel("kaosStepGraph", "KAOS step graph", vscode.ViewColumn.Beside,
      { enableScripts: true, localResourceRoots: [] });
    panel.onDidDispose(() => { state.graphPanel = undefined; });
    panel.webview.onDidReceiveMessage(async (m: unknown) => {
      const line = typeof m === "object" && m !== null ? (m as { line?: unknown }).line : undefined;
      if (typeof line !== "number" || !Number.isInteger(line) || line < 1) { return; }
      const doc = await vscode.workspace.openTextDocument(vscode.Uri.joinPath(folder.uri, PIPELINE_FILE));
      const editor = await vscode.window.showTextDocument(doc, vscode.ViewColumn.One);
      const pos = new vscode.Position(Math.min(line, doc.lineCount) - 1, 0);
      editor.selection = new vscode.Selection(pos, pos);
      editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
    });
    state.graphPanel = panel;
  }
  state.graphPanel.reveal(undefined, true);
  await refreshGraph(state, folder);
}

// ------------------------------------------------------------------------------------------ sign-in

async function signIn(state: State): Promise<void> {
  const folder = folderFor(state);
  if (!folder) { return; }
  if (!vscode.workspace.isTrusted) {
    void vscode.window.showWarningMessage("Sign-in needs a trusted folder. Trust this folder first (Workspaces: Manage Workspace Trust).");
    return;
  }
  const configPath = path.join(folder.uri.fsPath, DATASET_CONFIG_FILE);
  const issuer = fs.existsSync(configPath) ? readIssuer(fs.readFileSync(configPath, "utf8")) : undefined;
  const accepted = state.context.globalState.get<string[]>(ACCEPTED_ISSUERS_KEY, []);
  if (issuer && !accepted.includes(issuer)) {
    const shown = isHttpsUrl(issuer) ? issuer : "an address that is not https (refused)";
    if (!isHttpsUrl(issuer)) { void vscode.window.showErrorMessage(`This folder asks you to sign in at ${shown}. KAOS only signs in over https.`); return; }
    const choice = await vscode.window.showWarningMessage(
      `This folder asks you to sign in at ${issuer}. Only continue if you recognise this address.`, { modal: true }, "Sign in");
    if (choice !== "Sign in") { return; }
    await state.context.globalState.update(ACCEPTED_ISSUERS_KEY, [...accepted, issuer]);
  }
  await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "KAOS: complete the sign-in in your browser" }, async () => {
    const r = await run(settings(folder).kaosctl, LOGIN_ARGS, folder.uri.fsPath, LOGIN_TIMEOUT_MS);
    if (r.code === 0) {
      state.output.appendLine("Signed in.");
      void vscode.window.showInformationMessage("KAOS: signed in.");
    } else {
      const why = explainFailure(r);
      state.output.appendLine(`Sign-in failed: ${why}`);
      void vscode.window.showErrorMessage(`KAOS sign-in failed: ${why}`);
    }
  });
}

function showAccount(): void {
  const file = sessionFilePath(process.env, os.homedir());
  let facts: { exists: boolean; modifiedMs?: number } = { exists: false };
  try { facts = { exists: true, modifiedMs: fs.statSync(file).mtimeMs }; } catch { /* no session */ }
  void vscode.window.showInformationMessage(describeSession(facts, Date.now()));
}

// ------------------------------------------------------------------------------------------ update

// Offer the extension that was published with the installed kaosctl when this one is another version. The file is
// downloaded and checked by kaosctl before anything is asked, so the offer is only made when it can be kept.
// `asked`: the user ran the command, so every outcome is shown; on start-up only an available update is.
async function offerUpdate(state: State, folder: vscode.WorkspaceFolder, asked: boolean): Promise<void> {
  const kaosctl = settings(folder).kaosctl;
  const mine = String(state.context.extension.packageJSON.version);
  const v = await run(kaosctl, VERSION_ARGS, folder.uri.fsPath, VERSION_TIMEOUT_MS);
  if (v.code !== 0) {
    if (asked) { void vscode.window.showErrorMessage(`KAOS: ${explainFailure(v)}`); }
    return;
  }
  const need = updateNeeded(mine, v.stdout);
  if (!need) {
    if (asked) { void vscode.window.showInformationMessage(`KAOS extension ${mine}: nothing newer is published for your kaosctl.`); }
    return;
  }
  if (!asked && state.context.globalState.get<string>(SKIPPED_UPDATE_KEY) === need.wanted) { return; }
  const dir = path.join(state.context.globalStorageUri.fsPath, "updates");
  const d = await run(kaosctl, downloadArgs(dir), folder.uri.fsPath, DOWNLOAD_TIMEOUT_MS);
  const file = d.code === 0 ? downloadedFile(d.stdout) : undefined;
  if (!file) {
    const why = d.code === 0 ? "kaosctl printed no file" : explainFailure(d);
    state.output.appendLine(`No extension update for kaosctl ${need.kaosLib}: ${why}`);
    if (asked) { void vscode.window.showWarningMessage(`KAOS: no extension update for kaosctl ${need.kaosLib}: ${why}`); }
    return;
  }
  const choice = await vscode.window.showInformationMessage(
    `KAOS extension ${need.wanted} matches your kaosctl ${need.kaosLib}; this one is ${mine}.`, "Update", "Not now");
  if (choice !== "Update") {
    if (choice === "Not now") { await state.context.globalState.update(SKIPPED_UPDATE_KEY, need.wanted); }
    return;
  }
  try {
    await vscode.commands.executeCommand("workbench.extensions.installExtension", vscode.Uri.file(file));
  } catch (err) {
    void vscode.window.showErrorMessage(`KAOS: the update could not be installed: ${err instanceof Error ? err.message : String(err)}`);
    return;
  }
  state.output.appendLine(`Installed the extension ${need.wanted} from ${file}.`);
  const reload = await vscode.window.showInformationMessage(`KAOS extension ${need.wanted} is installed. Reload the window to use it.`, "Reload window");
  if (reload === "Reload window") { await vscode.commands.executeCommand("workbench.action.reloadWindow"); }
}

// ------------------------------------------------------------------------------------------ activation

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const state = new State(context);
  context.subscriptions.push(state.output, state.diagnostics, state.status, { dispose: () => state.debounce.dispose() });
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const marker = await detectKaosRepo(folderReader(folder.uri.fsPath));
    if (marker) { state.folders.set(folder.uri.fsPath, folder); state.output.appendLine(`${folder.name}: KAOS pipeline repository (${marker})`); }
  }
  await vscode.commands.executeCommand("setContext", "kaos.active", state.folders.size > 0);
  if (state.folders.size === 0) { return; }   // not a KAOS repository: stay inactive

  const first = state.folders.values().next().value as vscode.WorkspaceFolder;
  await loadSchema(state, first);
  state.status.command = "kaos.checkPipeline";
  state.status.text = "KAOS";
  state.status.show();

  const schedule = (uri: vscode.Uri, waitMs?: number) => {
    const folder = vscode.workspace.getWorkspaceFolder(uri);
    if (folder && state.folders.has(folder.uri.fsPath)) {
      state.debounce.schedule(folder.uri.fsPath, waitMs ?? settings(folder).delay, () => void checkFolder(state, folder, false));
    }
  };
  const watcher = vscode.workspace.createFileSystemWatcher("**/{pipeline.py,config/**,steps/**}");
  context.subscriptions.push(
    ...registerLanguageFeatures(state),
    // A save, a change to pipeline.py (the unsaved text is checked through stdin) and a file change on disk all go
    // through the same debounce, so one edit gives one run. Other files are read as saved.
    vscode.workspace.onDidSaveTextDocument((d) => schedule(d.uri)),
    vscode.workspace.onDidChangeTextDocument((e) => {
      const isPipeline = path.basename(e.document.uri.fsPath) === PIPELINE_FILE;
      if (e.contentChanges.length > 0 && (isPipeline || !e.document.isDirty)) { schedule(e.document.uri); }
    }),
    watcher,
    watcher.onDidChange((u) => schedule(u)),
    vscode.commands.registerCommand("kaos.checkPipeline", async () => {
      const folder = folderFor(state);
      if (folder) { await checkFolder(state, folder, true); }
    }),
    vscode.commands.registerCommand("kaos.showStepGraph", () => showGraph(state)),
    vscode.commands.registerCommand("kaos.signIn", () => signIn(state)),
    vscode.commands.registerCommand("kaos.showAccount", showAccount),
    vscode.commands.registerCommand("kaos.updateExtension", () => offerUpdate(state, folderFor(state) ?? first, true)),
    vscode.commands.registerCommand("kaos.reloadSchema", async () => { await loadSchema(state, first); void vscode.window.showInformationMessage(`KAOS step suggestions: ${state.schema?.source} schema.`); }),
  );
  void checkFolder(state, first, false);
  void offerUpdate(state, first, false);
}

export function deactivate(): void { /* disposables are released through context.subscriptions */ }
