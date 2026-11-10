// Is this extension the one that was published with the user's kaosctl?
// Why: every kaos-lib release publishes the extension built from the same commit, at the same version. The editor
// never updates an extension that was installed from a file, so the extension compares itself with the kaosctl it
// runs and offers the matching one. Pure functions only; extension.ts does the asking and the installing.

export const VERSION_ARGS = ["--version"];

/** The arguments that download (and check) the extension of the installed kaos-lib into `dir`. */
export function downloadArgs(dir: string): string[] {
  return ["vscode", "install", "--download", dir];
}

/** `kaosctl --version` prints "kaosctl 0.4.0rc7 (prerelease ...)" first: the version, or undefined. */
export function parseKaosctlVersion(output: string): string | undefined {
  const m = /^kaosctl\s+(\S+)/.exec(output.trim());
  return m ? m[1] : undefined;
}

/**
 * The extension version published with a kaos-lib release: "0.4.0" -> "0.4.0", "0.4.0rc7" -> "0.4.0-rc.7".
 * Anything else (a local or commit install) has no published extension: undefined.
 */
export function extensionVersionFor(kaosLib: string): string | undefined {
  const m = /^(\d+\.\d+\.\d+)(?:rc(\d+))?$/.exec(kaosLib);
  if (!m) { return undefined; }
  return m[2] === undefined ? m[1] : `${m[1]}-rc.${m[2]}`;
}

export interface UpdateNeeded {
  kaosLib: string;   // the installed kaos-lib, as kaosctl names it
  wanted: string;    // the extension version published with it
}

/** What to offer, or undefined when this extension already matches or kaosctl is not a published release. */
export function updateNeeded(extensionVersion: string, versionOutput: string): UpdateNeeded | undefined {
  const kaosLib = parseKaosctlVersion(versionOutput);
  const wanted = kaosLib ? extensionVersionFor(kaosLib) : undefined;
  if (!kaosLib || !wanted || wanted === extensionVersion) { return undefined; }
  return { kaosLib, wanted };
}

/** The file `kaosctl vscode install --download` printed (its last line), or undefined. */
export function downloadedFile(stdout: string): string | undefined {
  const lines = stdout.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
  const last = lines[lines.length - 1];
  return last && last.endsWith(".vsix") ? last : undefined;
}
