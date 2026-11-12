// The linter's JSON report and graph: types and strict parsers.
// Why: everything the extension shows comes from `kaosctl lint` JSON, so the shape is checked once, here, and a
// malformed or foreign document becomes a readable error instead of a crash further down.

export interface Position { line: number; column: number }
export interface Range1 { start: Position; end: Position }

export interface Finding {
  rule: string;
  name: string;
  level: "error" | "warning" | "info";
  file: string;
  range: Range1;
  message: string;
  fix: string;
  doc: string;
}

export interface Skipped { rule: string; name: string; reason: string; doc: string }

export interface Report {
  ruleset_version: string;
  summary: { errors: number; warnings: number; infos: number; skipped: number };
  findings: Finding[];
  skipped: Skipped[];
}

export interface GraphNode {
  id: string;
  name: string | null;
  variable: string | null;
  line: number;
  dynamic: boolean;
  gpu: boolean | null;
  walltime: string | number | boolean | null;
  resumable: string | number | boolean | null;
  disk: string | number | boolean | null;
}

export interface GraphPipeline {
  name: string | null;
  line: number;
  nodes: GraphNode[];
  edges: { from: string; to: string }[];
  unresolved: { step: string; line: number; reason: string }[];
}

export interface Graph {
  graph_version: number;
  ruleset_version: string;
  file: string;
  pipelines: GraphPipeline[];
}

export const SUPPORTED_GRAPH_VERSION = 1;

type Obj = Record<string, unknown>;

function obj(value: unknown, what: string): Obj {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${what} is not an object`);
  }
  return value as Obj;
}

function arr(value: unknown, what: string): unknown[] {
  if (!Array.isArray(value)) { throw new Error(`${what} is not a list`); }
  return value;
}

function str(o: Obj, key: string, what: string): string {
  if (typeof o[key] !== "string") { throw new Error(`${what}.${key} is not text`); }
  return o[key] as string;
}

function num(o: Obj, key: string, what: string): number {
  if (typeof o[key] !== "number") { throw new Error(`${what}.${key} is not a number`); }
  return o[key] as number;
}

function position(value: unknown, what: string): Position {
  const o = obj(value, what);
  return { line: num(o, "line", what), column: num(o, "column", what) };
}

function range(value: unknown, what: string): Range1 {
  const o = obj(value, what);
  return { start: position(o.start, `${what}.start`), end: position(o.end, `${what}.end`) };
}

function finding(value: unknown, i: number): Finding {
  const what = `finding ${i}`;
  const o = obj(value, what);
  const level = str(o, "level", what);
  if (level !== "error" && level !== "warning" && level !== "info") {
    throw new Error(`${what}.level is '${level}', expected error, warning or info`);
  }
  return {
    rule: str(o, "rule", what), name: str(o, "name", what), level, file: str(o, "file", what),
    range: range(o.range, `${what}.range`), message: str(o, "message", what), fix: str(o, "fix", what),
    doc: str(o, "doc", what),
  };
}

/** Parse the text of `kaosctl lint --format json`. Throws an Error that says what is wrong with the document. */
export function parseReport(text: string): Report {
  let raw: unknown;
  try { raw = JSON.parse(text); } catch { throw new Error("the check did not print JSON"); }
  const o = obj(raw, "report");
  const summary = obj(o.summary, "report.summary");
  return {
    ruleset_version: str(o, "ruleset_version", "report"),
    summary: {
      errors: num(summary, "errors", "summary"), warnings: num(summary, "warnings", "summary"),
      infos: num(summary, "infos", "summary"), skipped: num(summary, "skipped", "summary"),
    },
    findings: arr(o.findings, "report.findings").map(finding),
    skipped: arr(o.skipped, "report.skipped").map((s, i) => {
      const so = obj(s, `skipped ${i}`);
      return { rule: str(so, "rule", "skipped"), name: str(so, "name", "skipped"),
               reason: str(so, "reason", "skipped"), doc: str(so, "doc", "skipped") };
    }),
  };
}

function node(value: unknown, i: number): GraphNode {
  const what = `node ${i}`;
  const o = obj(value, what);
  const scalar = (k: string) => {
    const v = o[k];
    return typeof v === "string" || typeof v === "number" || typeof v === "boolean" ? v : null;
  };
  return {
    id: str(o, "id", what), name: typeof o.name === "string" ? o.name : null,
    variable: typeof o.variable === "string" ? o.variable : null, line: num(o, "line", what),
    dynamic: o.dynamic === true, gpu: typeof o.gpu === "boolean" ? o.gpu : null,
    walltime: scalar("walltime"), resumable: scalar("resumable"), disk: scalar("disk"),
  };
}

/** Parse the text of `kaosctl lint --graph`. Throws an Error that says what is wrong with the document. */
export function parseGraph(text: string): Graph {
  let raw: unknown;
  try { raw = JSON.parse(text); } catch { throw new Error("the graph command did not print JSON"); }
  const o = obj(raw, "graph");
  const version = num(o, "graph_version", "graph");
  if (version !== SUPPORTED_GRAPH_VERSION) {
    throw new Error(`the installed kaosctl writes graph version ${version}, this extension reads ${SUPPORTED_GRAPH_VERSION}: update the extension or kaosctl`);
  }
  return {
    graph_version: version, ruleset_version: str(o, "ruleset_version", "graph"), file: str(o, "file", "graph"),
    pipelines: arr(o.pipelines, "graph.pipelines").map((p, pi) => {
      const po = obj(p, `pipeline ${pi}`);
      return {
        name: typeof po.name === "string" ? po.name : null, line: num(po, "line", "pipeline"),
        nodes: arr(po.nodes, "pipeline.nodes").map(node),
        edges: arr(po.edges, "pipeline.edges").map((e) => {
          const eo = obj(e, "edge");
          return { from: str(eo, "from", "edge"), to: str(eo, "to", "edge") };
        }),
        unresolved: arr(po.unresolved, "pipeline.unresolved").map((u) => {
          const uo = obj(u, "unresolved");
          return { step: str(uo, "step", "unresolved"), line: num(uo, "line", "unresolved"),
                   reason: str(uo, "reason", "unresolved") };
        }),
      };
    }),
  };
}
