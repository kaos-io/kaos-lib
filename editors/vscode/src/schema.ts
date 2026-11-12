// The step-API schema (from `kaosctl lint --schema`) and what the editor does with it: completion and hover.
// Why: every suggestion and doc text comes from the library's schema, never from a list in this extension. All
// functions here are pure (text in, data out) so they are tested without VS Code.

export const SUPPORTED_SCHEMA_VERSION = 1;

export interface SchemaValue { insert: string; label: string; doc: string }
export interface SchemaLink { title: string; url: string }
export interface SchemaParam {
  name: string;
  position: number;
  type: string;
  required: boolean;
  default: string | null;
  gpu_only: boolean;
  pattern: string | null;
  doc: string;
  snippet: string;
  values: SchemaValue[];
  links: SchemaLink[];
}
export interface Schema {
  schema_version: number;
  ruleset_version: string;
  guide: string;
  authoring_modules: string[];
  step: { function: string; parameters: SchemaParam[] };
}

type Obj = Record<string, unknown>;

function asObj(v: unknown, what: string): Obj {
  if (typeof v !== "object" || v === null || Array.isArray(v)) { throw new Error(`${what} is not an object`); }
  return v as Obj;
}
function asStr(o: Obj, k: string, what: string): string {
  if (typeof o[k] !== "string") { throw new Error(`${what}.${k} is not text`); }
  return o[k] as string;
}
function asList(v: unknown, what: string): unknown[] {
  if (!Array.isArray(v)) { throw new Error(`${what} is not a list`); }
  return v;
}

function parseParam(v: unknown, i: number): SchemaParam {
  const what = `parameter ${i}`;
  const o = asObj(v, what);
  return {
    name: asStr(o, "name", what),
    position: typeof o.position === "number" ? o.position : i,
    type: asStr(o, "type", what),
    required: o.required === true,
    default: typeof o.default === "string" ? o.default : null,
    gpu_only: o.gpu_only === true,
    pattern: typeof o.pattern === "string" ? o.pattern : null,
    doc: asStr(o, "doc", what),
    snippet: asStr(o, "snippet", what),
    values: asList(o.values, `${what}.values`).map((x, j) => {
      const xo = asObj(x, `${what}.values[${j}]`);
      return { insert: asStr(xo, "insert", "value"), label: asStr(xo, "label", "value"), doc: asStr(xo, "doc", "value") };
    }),
    links: asList(o.links, `${what}.links`).map((x) => {
      const xo = asObj(x, "link");
      return { title: asStr(xo, "title", "link"), url: asStr(xo, "url", "link") };
    }),
  };
}

/** Parse schema JSON text. Throws an Error saying what is wrong, including an unknown schema version. */
export function parseSchema(text: string): Schema {
  let raw: unknown;
  try { raw = JSON.parse(text); } catch { throw new Error("the schema is not JSON"); }
  const o = asObj(raw, "schema");
  const version = o.schema_version;
  if (version !== SUPPORTED_SCHEMA_VERSION) {
    throw new Error(`schema version ${String(version)} is not one this extension reads (it reads ${SUPPORTED_SCHEMA_VERSION})`);
  }
  const step = asObj(o.step, "schema.step");
  return {
    schema_version: SUPPORTED_SCHEMA_VERSION,
    ruleset_version: asStr(o, "ruleset_version", "schema"),
    guide: asStr(o, "guide", "schema"),
    authoring_modules: asList(o.authoring_modules, "schema.authoring_modules").map(String),
    step: {
      function: asStr(step, "function", "schema.step"),
      parameters: asList(step.parameters, "schema.step.parameters").map(parseParam),
    },
  };
}

export interface SchemaChoice { schema: Schema; source: "kaosctl" | "bundled"; note: string | null }

/**
 * Prefer the schema of the installed kaosctl; fall back to the bundled one when it is missing, unreadable or of a
 * version this extension does not read. `note` says why the fallback was used (shown to the user, never silent).
 */
export function chooseSchema(installed: { text?: string; error?: string }, bundledText: string): SchemaChoice {
  if (installed.text !== undefined) {
    try { return { schema: parseSchema(installed.text), source: "kaosctl", note: null }; }
    catch (e) { return { schema: parseSchema(bundledText), source: "bundled", note: `kaosctl's schema was not used: ${(e as Error).message}` }; }
  }
  return { schema: parseSchema(bundledText), source: "bundled", note: installed.error ?? "kaosctl was not run" };
}

// ---------------------------------------------------------------------------------------------- call context

interface Frame { open: number; callee: string | null; lastComma: number; segments: string[] }

export type StepContext =
  | { kind: "none" }
  | { kind: "name"; prefix: string; usedKeywords: string[]; positionalCount: number }
  | { kind: "value"; param: string; prefix: string };

const IDENT_BEFORE_PAREN = /([A-Za-z_][A-Za-z0-9_]*)\s*$/;

/** Names that call the library's step(): `step`, and any `from <x>.authoring import step as <alias>`. */
export function stepCallNames(text: string): Set<string> {
  const names = new Set<string>(["step"]);
  const re = /from\s+[\w.]*authoring\s+import\s+([^\n#]+)/g;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    for (const part of m[1].split(",")) {
      const alias = /^\s*\(?\s*step\s+as\s+(\w+)/.exec(part);
      if (alias) { names.add(alias[1]); }
    }
  }
  return names;
}

function scan(text: string): Frame[] {
  const stack: Frame[] = [];
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (c === "#") { while (i < text.length && text[i] !== "\n") { i++; } continue; }
    if (c === '"' || c === "'") {
      const triple = text.startsWith(c.repeat(3), i);
      const quote = triple ? c.repeat(3) : c;
      i += quote.length;
      while (i < text.length && !text.startsWith(quote, i)) {
        if (text[i] === "\\") { i++; }
        else if (!triple && text[i] === "\n") { break; }
        i++;
      }
      i += quote.length;
      continue;
    }
    const top = stack[stack.length - 1];
    if (c === "(" || c === "[" || c === "{") {
      const callee = c === "(" ? IDENT_BEFORE_PAREN.exec(text.slice(Math.max(0, i - 80), i))?.[1] ?? null : null;
      stack.push({ open: i, callee, lastComma: i, segments: [] });
    } else if (c === ")" || c === "]" || c === "}") {
      stack.pop();
    } else if (c === "," && top) {
      top.segments.push(text.slice(top.lastComma + 1, i));
      top.lastComma = i;
    }
    i++;
  }
  return stack;
}

/** The text without `# comments` (a `#` inside a string stays). Used on one argument at a time. */
function stripComments(text: string): string {
  let out = "";
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (c === "#") { while (i < text.length && text[i] !== "\n") { i++; } continue; }
    if (c === '"' || c === "'") {
      const quote = text.startsWith(c.repeat(3), i) ? c.repeat(3) : c;
      let j = i + quote.length;
      while (j < text.length && !text.startsWith(quote, j)) { j += text[j] === "\\" ? 2 : 1; }
      j = Math.min(text.length, j + quote.length);
      out += text.slice(i, j);
      i = j;
      continue;
    }
    out += c;
    i++;
  }
  return out;
}

/**
 * Where the cursor is inside a step(...) call, from the text before the cursor.
 * `name`: the cursor is where an argument name is typed; `value`: after `<param>=`; `none`: anywhere else
 * (outside a step call, inside a list or another call, or on a positional argument).
 */
export function analyzeStepContext(textBefore: string): StepContext {
  const frames = scan(textBefore);
  const top = frames[frames.length - 1];
  if (!top || top.callee === null || !stepCallNames(textBefore).has(top.callee)) { return { kind: "none" }; }
  const current = stripComments(textBefore.slice(top.lastComma + 1));
  const keyword = /^\s*([A-Za-z_]\w*)\s*=(?!=)([\s\S]*)$/.exec(current);
  if (keyword) { return { kind: "value", param: keyword[1], prefix: keyword[2].trimStart() }; }
  const typed = /^\s*([A-Za-z_]\w*)?$/.exec(current);
  if (!typed) { return { kind: "none" }; }
  const used = top.segments.map((s) => /^\s*([A-Za-z_]\w*)\s*=(?!=)/.exec(stripComments(s))?.[1]).filter((x): x is string => !!x);
  const positionalCount = top.segments.length - used.length;
  return { kind: "name", prefix: typed[1] ?? "", usedKeywords: used, positionalCount };
}

// ---------------------------------------------------------------------------------------------- completion

export interface CompletionEntry {
  label: string;
  detail: string;
  documentation: string;   // Markdown
  insertText: string;
  isSnippet: boolean;
  replaceLength: number;   // characters before the cursor the insertion replaces
  sortText: string;
}

function docMarkdown(p: SchemaParam): string {
  const lines = [p.doc];
  if (p.gpu_only) { lines.push("", "Only for `gpu=True` steps."); }
  if (p.default) { lines.push("", `Default: \`${p.default}\`.`); }
  if (p.links.length) { lines.push("", p.links.map((l) => `[${l.title}](${l.url})`).join(" · ")); }
  return lines.join("\n");
}

/** Completion entries for the text before the cursor; empty outside a step(...) call or on an unknown argument. */
export function completionsFor(schema: Schema, textBefore: string): CompletionEntry[] {
  const ctx = analyzeStepContext(textBefore);
  const params = schema.step.parameters;
  if (ctx.kind === "name") {
    return params
      .filter((p) => p.position >= ctx.positionalCount && !ctx.usedKeywords.includes(p.name) && p.name.startsWith(ctx.prefix))
      .map((p) => ({
        label: p.name, detail: p.type + (p.required ? " (required)" : ""), documentation: docMarkdown(p),
        insertText: `${p.name}=${p.snippet}`, isSnippet: true, replaceLength: ctx.prefix.length,
        sortText: String(p.position).padStart(2, "0"),
      }));
  }
  if (ctx.kind === "value") {
    const p = params.find((x) => x.name === ctx.param);
    if (!p) { return []; }
    return p.values
      .filter((v) => v.insert.startsWith(ctx.prefix))
      .map((v, i) => ({
        label: v.label, detail: `${p.name}: ${p.type}`, documentation: `${v.doc}\n\n${docMarkdown(p)}`,
        insertText: v.insert, isSnippet: false, replaceLength: ctx.prefix.length, sortText: String(i).padStart(2, "0"),
      }));
  }
  return [];
}

// ---------------------------------------------------------------------------------------------- hover

export interface HoverResult { markdown: string; start: number; end: number }   // start/end: columns of the word

const WORD = /[A-Za-z_][A-Za-z0-9_]*/g;

/**
 * Hover text for the word under `column` of `line`, given the whole text up to the start of that line.
 * Shows the documentation of a step() argument (on its name or on its value), or the rename hint for an argument
 * the library no longer takes.
 */
export function hoverFor(schema: Schema, textBeforeLine: string, line: string, column: number): HoverResult | null {
  for (const m of line.matchAll(WORD)) {
    const start = m.index ?? 0;
    const end = start + m[0].length;
    if (column < start || column > end) { continue; }
    const ctx = analyzeStepContext(textBeforeLine + line.slice(0, end));
    const followedByEquals = /^\s*=(?!=)/.test(line.slice(end));
    if (ctx.kind === "name" && ctx.prefix === m[0] && followedByEquals) { return paramHover(schema, m[0], start, end); }
    if (ctx.kind === "value") { return paramHover(schema, ctx.param, start, end); }
    return null;
  }
  return null;
}

function paramHover(schema: Schema, name: string, start: number, end: number): HoverResult | null {
  const p = schema.step.parameters.find((x) => x.name === name);
  if (p) { return { markdown: `**${p.name}** \`${p.type}\`\n\n${docMarkdown(p)}`, start, end }; }
  return null;
}
