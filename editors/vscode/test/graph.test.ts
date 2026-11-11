import assert from "node:assert/strict";
import { test } from "node:test";
import { BOX_WIDTH, escapeHtml, layoutPipeline, renderGraphHtml, truncate } from "../src/graphHtml";
import { Graph, GraphNode, parseGraph } from "../src/report";
import { fixture } from "./helpers";

const graph = parseGraph(fixture("graph.json"));
const nodeBase: GraphNode = { id: "s0", name: "a", variable: "a", line: 1, dynamic: false, gpu: false, walltime: null, resumable: null, disk: null };

test("should_place_a_step_to_the_right_of_everything_it_needs", () => {
  const layout = layoutPipeline(graph.pipelines[0]);
  const x = Object.fromEntries(layout.nodes.map((n) => [n.node.name, n.x]));
  assert.ok(x["prepare"] < x["train"] && x["train"] < x["evaluate"]);
  assert.equal(layout.edges.length, 3);
});

test("should_stack_steps_of_one_depth_in_file_order", () => {
  const p = { name: "p", line: 1, edges: [], unresolved: [],
    nodes: [{ ...nodeBase, id: "s0", name: "a" }, { ...nodeBase, id: "s1", name: "b" }] };
  const [a, b] = layoutPipeline(p).nodes;
  assert.equal(a.x, b.x);
  assert.ok(b.y > a.y);
});

test("should_produce_the_same_layout_every_time", () => {
  assert.deepEqual(layoutPipeline(graph.pipelines[0]), layoutPipeline(graph.pipelines[0]));
});

test("should_survive_a_cycle_without_looping", () => {
  const p = { name: null, line: 1, unresolved: [], nodes: [{ ...nodeBase, id: "a" }, { ...nodeBase, id: "b" }],
    edges: [{ from: "a", to: "b" }, { from: "b", to: "a" }] };
  assert.equal(layoutPipeline(p).nodes.length, 2);
});

test("should_render_a_node_per_step_with_its_line_for_navigation", () => {
  const html = renderGraphHtml(graph, "abc123");
  assert.equal((html.match(/class="node/g) ?? []).length, 3);
  assert.match(html, /data-line="5"/);
  assert.match(html, /GPU/);
});

test("should_escape_every_piece_of_text_from_the_users_file", () => {
  const evil = '<img src=x onerror=alert(1)>"';
  const g: Graph = { ...graph, file: evil, pipelines: [{ name: evil, line: 1, edges: [], nodes: [{ ...nodeBase, name: evil, disk: evil }],
    unresolved: [{ step: "s0", line: 2, reason: evil }] }] };
  const html = renderGraphHtml(g, "n0nce");
  assert.ok(!html.includes("<img"), "markup from the file must not appear");
  assert.ok(html.includes("&lt;img"));
});

test("should_allow_only_the_pages_own_script_and_style_through_the_csp", () => {
  const html = renderGraphHtml(graph, "N0NCE");
  assert.match(html, /default-src 'none'; style-src 'nonce-N0NCE'; script-src 'nonce-N0NCE';/);
  assert.equal((html.match(/<script/g) ?? []).length, 1);
  assert.ok(!/https?:\/\//.test(html.replace(/http-equiv/g, "")), "no external resource");
});

test("should_mark_steps_built_in_a_loop_as_dynamic", () => {
  const g: Graph = { ...graph, pipelines: [{ name: "p", line: 1, edges: [], unresolved: [], nodes: [{ ...nodeBase, dynamic: true }] }] };
  const html = renderGraphHtml(g, "n");
  assert.match(html, /class="node dynamic"/);
  assert.match(html, /built in a loop or a condition/);
});

test("should_say_so_when_there_is_no_pipeline_or_no_step", () => {
  assert.match(renderGraphHtml({ ...graph, pipelines: [] }, "n"), /No <code>with pipeline/);
  assert.match(renderGraphHtml({ ...graph, pipelines: [{ name: "p", line: 1, nodes: [], edges: [], unresolved: [] }] }, "n"), /no steps/);
});

test("should_refuse_a_graph_of_another_version", () => {
  const other = JSON.parse(fixture("graph.json"));
  other.graph_version = 7;
  assert.throws(() => parseGraph(JSON.stringify(other)), /graph version 7/);
});

test("should_escape_and_truncate_helpers", () => {
  assert.equal(escapeHtml(`<&"'>`), "&lt;&amp;&quot;&#39;&gt;");
  assert.equal(truncate("abcdef", 4), "abc…");
  assert.ok(BOX_WIDTH > 100);
});
