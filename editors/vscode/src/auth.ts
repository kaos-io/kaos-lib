// Sign-in state and the pieces of the sign-in command that can be decided without VS Code.
// Why: sign-in is `kaosctl login` (authorization code with PKCE on a loopback address). The extension never sees or
// stores a token: it only asks whether `kaosctl` left a session on this machine, by looking at the file's
// existence and age, never at its content.

import * as path from "path";

export const SESSION_FILE_NAME = "lakefs-session.json";

/** Where `kaosctl login` keeps its session (the same rule as kaos-lib: $KUBECORE_ML_HOME or ~/.config/kubecore-ml). */
export function sessionFilePath(env: Record<string, string | undefined>, home: string): string {
  const base = env.KUBECORE_ML_HOME || path.join(home, ".config", "kubecore-ml");
  return path.join(base, SESSION_FILE_NAME);
}

export interface SessionFacts { exists: boolean; modifiedMs?: number }

/** One line for the user: whether a session is there and how old it is. Whether it is still valid is the server's call. */
export function describeSession(facts: SessionFacts, nowMs: number): string {
  if (!facts.exists || facts.modifiedMs === undefined) {
    return "Not signed in. Run 'KAOS: Sign in'.";
  }
  const hours = Math.max(0, Math.floor((nowMs - facts.modifiedMs) / 3_600_000));
  const age = hours < 1 ? "less than an hour ago" : hours < 48 ? `${hours} hours ago` : `${Math.floor(hours / 24)} days ago`;
  return `Signed in (session from ${age}). If a command says you are not signed in, run 'KAOS: Sign in' again.`;
}

/** The `oidcIssuer` value of a dataset-config.yaml text, or undefined. A plain line match: the file is not run or loaded. */
export function readIssuer(configText: string): string | undefined {
  const m = /^[ \t]*oidcIssuer[ \t]*:[ \t]*["']?([^\s"'#]+)["']?/m.exec(configText);
  return m?.[1];
}

/** An issuer is acceptable to show in a confirmation only when it is an https URL; anything else is refused. */
export function isHttpsUrl(value: string): boolean {
  try { return new URL(value).protocol === "https:"; } catch { return false; }
}
