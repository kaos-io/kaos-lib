// Quick fixes for the findings that have one obvious edit.
// Why: a fix is offered only when the edit is certain and local. The renames come from the library's schema
// (`renamed_arguments`), so a new rename needs no extension change.

import { MappedDiagnostic } from "./diagnostics";

export interface TextEdit {
  startLine: number;
  startCharacter: number;
  endLine: number;
  endCharacter: number;
  newText: string;
}

export interface QuickFix { title: string; edit: TextEdit }

// The rule that reports an argument step() does not take.
const REFUSED_ARGUMENT_RULE = "L-E06";

/**
 * The quick fixes for one diagnostic. `textAtStart` is the document text from the diagnostic's start to the end of
 * its line (enough to see the argument name). Returns [] when there is no safe fix.
 */
export function quickFixesFor(d: Pick<MappedDiagnostic, "rule" | "startLine" | "startCharacter">,
                              textAtStart: string, renamed: Record<string, string>): QuickFix[] {
  if (d.rule !== REFUSED_ARGUMENT_RULE) { return []; }
  const m = /^([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)/.exec(textAtStart);
  if (!m || !Object.prototype.hasOwnProperty.call(renamed, m[1])) { return []; }
  const to = renamed[m[1]];
  return [{
    title: `Rename '${m[1]}' to '${to}'`,
    edit: { startLine: d.startLine, startCharacter: d.startCharacter, endLine: d.startLine,
            endCharacter: d.startCharacter + m[1].length, newText: to },
  }];
}
