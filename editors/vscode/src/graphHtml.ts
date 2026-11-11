// The step graph as an HTML page (an SVG drawing) for the read-only graph view.
// Why: the page is built from the linter's parsed pipeline, never from running the file. Every piece of text that came
// from the user's file is escaped, and the page allows only its own nonce'd script (which only reports a click).

import { Graph, GraphNode, GraphPipeline } from "./report";

export const BOX_WIDTH = 200;
export const BOX_HEIGHT = 64;
const GAP_X = 70;
const GAP_Y = 26;
const MARGIN = 20;
const MAX_LABEL = 24;

export interface PlacedNode { node: GraphNode; x: number; y: number; depth: number }
export interface PlacedEdge { from: string; to: string; x1: number; y1: number; x2: number; y2: number }
export interface Layout { nodes: PlacedNode[]; edges: PlacedEdge[]; width: number; height: number }

/** Escape text for HTML text and attribute values. */
export function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/** Shorten a label to the width of a box. */
export function truncate(text: string, max = MAX_LABEL): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

/**
 * Place the steps in columns by their longest chain of dependencies (a step is right of everything it needs).
 * Steps in one column keep the order of the file. Pure: the same pipeline always gives the same drawing.
 */
export function layoutPipeline(p: GraphPipeline): Layout {
  const parents = new Map<string, string[]>();
  for (const e of p.edges) { parents.set(e.to, [...(parents.get(e.to) ?? []), e.from]); }
  const depth = new Map<string, number>();
  const depthOf = (id: string, seen: Set<string>): number => {
    const known = depth.get(id);
    if (known !== undefined) { return known; }
    if (seen.has(id)) { return 0; }   // a cycle cannot come from the reader; do not loop if it ever does
    seen.add(id);
    const d = Math.max(-1, ...(parents.get(id) ?? []).map((q) => depthOf(q, seen))) + 1;
    depth.set(id, d);
    return d;
  };
  const rowsUsed = new Map<number, number>();
  const placed: PlacedNode[] = p.nodes.map((node) => {
    const d = depthOf(node.id, new Set());
    const row = rowsUsed.get(d) ?? 0;
    rowsUsed.set(d, row + 1);
    return { node, depth: d, x: MARGIN + d * (BOX_WIDTH + GAP_X), y: MARGIN + row * (BOX_HEIGHT + GAP_Y) };
  });
  const byId = new Map(placed.map((n) => [n.node.id, n]));
  const edges: PlacedEdge[] = [];
  for (const e of p.edges) {
    const a = byId.get(e.from), b = byId.get(e.to);
    if (a && b) {
      edges.push({ from: e.from, to: e.to, x1: a.x + BOX_WIDTH, y1: a.y + BOX_HEIGHT / 2, x2: b.x, y2: b.y + BOX_HEIGHT / 2 });
    }
  }
  const columns = Math.max(0, ...placed.map((n) => n.depth)) + 1;
  const rows = Math.max(1, ...rowsUsed.values());
  return {
    nodes: placed, edges,
    width: MARGIN * 2 + columns * BOX_WIDTH + (columns - 1) * GAP_X,
    height: MARGIN * 2 + rows * BOX_HEIGHT + (rows - 1) * GAP_Y,
  };
}

function badges(n: GraphNode): string[] {
  const out: string[] = [];
  if (n.gpu) { out.push("GPU"); }
  if (n.walltime !== null) { out.push(`limit ${String(n.walltime)}`); }
  if (n.resumable === true || (typeof n.resumable === "string")) { out.push("resumable"); }
  if (n.resumable === false) { out.push("not resumable"); }
  if (n.disk !== null) { out.push(`disk ${String(n.disk)}`); }
  return out;
}

function nodeSvg(p: PlacedNode): string {
  const n = p.node;
  const label = n.name ?? "(name is computed)";
  const sub = n.dynamic ? "built in a loop or a condition" : badges(n).join(" · ");
  const title = `${label}${sub ? `: ${sub}` : ""} (line ${n.line})`;
  return `<g class="node${n.dynamic ? " dynamic" : ""}" tabindex="0" role="button" data-line="${n.line}" transform="translate(${p.x},${p.y})">` +
    `<title>${escapeHtml(title)}</title>` +
    `<rect width="${BOX_WIDTH}" height="${BOX_HEIGHT}" rx="6"/>` +
    `<text class="name" x="12" y="26">${escapeHtml(truncate(label))}</text>` +
    `<text class="sub" x="12" y="46">${escapeHtml(truncate(sub, 30))}</text></g>`;
}

function edgeSvg(e: PlacedEdge): string {
  const mid = (e.x1 + e.x2) / 2;
  return `<path class="edge" marker-end="url(#arrow)" d="M${e.x1},${e.y1} C${mid},${e.y1} ${mid},${e.y2} ${e.x2},${e.y2}"/>`;
}

function pipelineHtml(p: GraphPipeline): string {
  const layout = layoutPipeline(p);
  const heading = p.name ? `Pipeline ${escapeHtml(p.name)}` : "Pipeline";
  const note = p.unresolved.length
    ? `<ul class="unresolved">${p.unresolved.map((u) => `<li>Line ${u.line}: ${escapeHtml(u.reason)}</li>`).join("")}</ul>` : "";
  const body = p.nodes.length === 0
    ? "<p>This pipeline has no steps.</p>"
    : `<svg width="${layout.width}" height="${layout.height}" viewBox="0 0 ${layout.width} ${layout.height}" role="group" aria-label="${heading}">` +
      `<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z"/></marker></defs>` +
      `${layout.edges.map(edgeSvg).join("")}${layout.nodes.map(nodeSvg).join("")}</svg>`;
  return `<section><h2>${heading} <span class="muted">line ${p.line}, ${p.nodes.length} step${p.nodes.length === 1 ? "" : "s"}</span></h2>${body}${note}</section>`;
}

const STYLE = `
body{font-family:var(--vscode-font-family);color:var(--vscode-foreground);background:var(--vscode-editor-background);padding:8px 16px}
h1{font-size:1.2em;margin:.2em 0}h2{font-size:1.05em;margin:1.2em 0 .4em}.muted{color:var(--vscode-descriptionForeground);font-weight:normal;font-size:.85em}
svg{max-width:100%;overflow:auto}.node{cursor:pointer}.node rect{fill:var(--vscode-editorWidget-background);stroke:var(--vscode-focusBorder);stroke-width:1.2}
.node.dynamic rect{stroke-dasharray:5 4;stroke:var(--vscode-descriptionForeground)}.node:hover rect,.node:focus rect{stroke-width:2.4;outline:none}
.node .name{fill:var(--vscode-foreground);font-size:13px;font-weight:600}.node .sub{fill:var(--vscode-descriptionForeground);font-size:11px}
.edge{fill:none;stroke:var(--vscode-descriptionForeground);stroke-width:1.4}marker path{fill:var(--vscode-descriptionForeground)}
.unresolved{color:var(--vscode-editorWarning-foreground)}`;

/**
 * The whole page. `nonce` must be a fresh random value per render; the Content-Security-Policy allows only that
 * nonce'd script and style, so text from the user's file cannot run anything.
 */
export function renderGraphHtml(graph: Graph, nonce: string): string {
  const csp = `default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';`;
  const sections = graph.pipelines.length ? graph.pipelines.map(pipelineHtml).join("") : "<p>No <code>with pipeline(...)</code> block was found.</p>";
  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="${csp}">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1"><title>Step graph</title><style nonce="${nonce}">${STYLE}</style></head><body>` +
    `<h1>Step graph <span class="muted">${escapeHtml(graph.file)} · read from the file, nothing is run</span></h1>${sections}` +
    `<script nonce="${nonce}">const vscode=acquireVsCodeApi();` +
    `function open(el){const g=el.closest('.node');if(g){vscode.postMessage({line:Number(g.dataset.line)});}}` +
    `document.addEventListener('click',e=>open(e.target));` +
    `document.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open(e.target);}});</script></body></html>`;
}
