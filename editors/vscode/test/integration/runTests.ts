// Launches VS Code (an installed one; nothing is downloaded) and runs suite.ts inside it, once for a KAOS pipeline
// folder and once for an unrelated folder (AC-15). Usage: node out/test/integration/runTests.js <code> <kaosctl>
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { runTests } from "@vscode/test-electron";

const PACKAGE_ROOT = path.resolve(__dirname, "..", "..", "..");

function workspace(kind: "kaos" | "other"): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), `kaos-it-${kind}-`));
  const pipeline = fs.readFileSync(path.join(PACKAGE_ROOT, "test", "fixtures", "pipeline.py"), "utf8");
  if (kind === "kaos") {
    fs.mkdirSync(path.join(dir, ".kaos"));
    fs.writeFileSync(path.join(dir, ".kaos", "compat.yaml"), "kaos_lib: '>=0.4'\n");
    fs.mkdirSync(path.join(dir, "config"));
    fs.writeFileSync(path.join(dir, "config", "train.yaml"), "train:\n  epochs: 3\n");
    fs.writeFileSync(path.join(dir, "pipeline.py"), pipeline);
  } else {
    fs.writeFileSync(path.join(dir, "pipeline.py"), "import os\nprint(os.getcwd())\n");
  }
  return dir;
}

async function launch(code: string, kaosctl: string, kind: "kaos" | "other"): Promise<void> {
  const data = fs.mkdtempSync(path.join(os.tmpdir(), "kaos-it-data-"));
  fs.mkdirSync(path.join(data, "User"), { recursive: true });
  fs.writeFileSync(path.join(data, "User", "settings.json"), JSON.stringify({ "kaos.kaosctlPath": kaosctl, "security.workspace.trust.enabled": false }));
  await runTests({
    vscodeExecutablePath: code,
    extensionDevelopmentPath: PACKAGE_ROOT,
    extensionTestsPath: path.join(__dirname, "suite"),
    extensionTestsEnv: { KAOS_IT_MODE: kind },
    launchArgs: [workspace(kind), "--user-data-dir", data, "--extensions-dir", path.join(data, "ext"), "--disable-extensions", "--no-sandbox"],
  });
}

async function main(): Promise<void> {
  const [code, kaosctl] = process.argv.slice(2);
  if (!code || !kaosctl) { throw new Error("usage: runTests.js <path to the code executable> <path to kaosctl>"); }
  await launch(code, kaosctl, "kaos");
  await launch(code, kaosctl, "other");
}

main().catch((e) => { console.error(e); process.exit(1); });
