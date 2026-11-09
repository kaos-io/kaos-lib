// Running `kaosctl`: one place that starts the process.
// Why: every call goes through execFile (no shell, so no quoting or injection), with a time limit and an output cap,
// and returns the exit code and both outputs instead of throwing, so callers decide what each code means.

import { execFile } from "child_process";

export interface RunResult {
  code: number | null;     // the exit code; null when the process could not start or was stopped
  stdout: string;
  stderr: string;
  startError?: string;     // why it could not start (for example, the command was not found)
}

export const DEFAULT_TIMEOUT_MS = 60_000;
const MAX_OUTPUT_BYTES = 16 * 1024 * 1024;

/** Run `command args...` in `cwd`. Never rejects. */
export function run(command: string, args: string[], cwd: string, timeoutMs = DEFAULT_TIMEOUT_MS, input?: string): Promise<RunResult> {
  return new Promise((resolve) => {
    const child = execFile(command, args, { cwd, timeout: timeoutMs, maxBuffer: MAX_OUTPUT_BYTES, windowsHide: true, encoding: "utf8" },
      (error, stdout, stderr) => {
        if (!error) { resolve({ code: 0, stdout, stderr }); return; }
        const e = error as NodeJS.ErrnoException & { code?: number | string; killed?: boolean };
        if (typeof e.code === "number") { resolve({ code: e.code, stdout, stderr }); return; }
        const why = e.code === "ENOENT" ? `'${command}' was not found` : e.killed ? `'${command}' did not finish in time` : e.message;
        resolve({ code: null, stdout, stderr, startError: why });
      });
    // Text for standard input (an unsaved buffer). An error here (the process ended early) is reported by execFile.
    child.stdin?.on("error", () => undefined);
    child.stdin?.end(input ?? "");
  });
}

/** The pipeline file the editor's unsaved text stands in for (kaosctl's default pipeline file). */
export const PIPELINE_ARG = "pipeline.py";

/**
 * The arguments of one check: `lint [--context FILE] --format json [--stdin-path pipeline.py]`, run in the folder
 * (so no path argument). With `fromStdin` the pipeline text is read from standard input (the unsaved buffer).
 */
export function checkArgs(contextFile: string | undefined, fromStdin = false): string[] {
  return ["lint", ...(contextFile ? ["--context", contextFile] : []), "--format", "json",
          ...(fromStdin ? ["--stdin-path", PIPELINE_ARG] : [])];
}

/** The arguments of the graph command, optionally reading the unsaved pipeline text from standard input. */
export function graphArgs(fromStdin = false): string[] {
  return ["lint", "--graph", ...(fromStdin ? ["--stdin-path", PIPELINE_ARG] : [])];
}
export const SCHEMA_ARGS = ["lint", "--schema"];
export const LOGIN_ARGS = ["login"];

// kaosctl lint exits 0 (no errors) or 2 (errors found); both print a report. Anything else: it could not run.
export const EXIT_ERRORS_FOUND = 2;

/** True when the result carries a report (exit 0 or 2); false when the check could not run. */
export function producedReport(r: RunResult): boolean {
  return r.code === 0 || r.code === EXIT_ERRORS_FOUND;
}

/** A short explanation for a result that could not run, for the user. */
export function explainFailure(r: RunResult): string {
  if (r.startError) { return `${r.startError}. Set 'kaos.kaosctlPath' or install kaos-lib (pip install kaos-lib).`; }
  const firstLine = (r.stderr || r.stdout).split("\n").find((l) => l.trim().length > 0) ?? "no output";
  return `kaosctl stopped with exit code ${r.code}: ${firstLine}`;
}
