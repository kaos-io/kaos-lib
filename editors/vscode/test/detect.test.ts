import assert from "node:assert/strict";
import { test } from "node:test";
import { FolderReader, detectKaosRepo, importsAuthoring } from "../src/detect";

function folder(files: Record<string, string>): FolderReader {
  return {
    exists: async (p) => p in files,
    readHead: async (p, max) => (p in files ? files[p].slice(0, max) : undefined),
  };
}

test("should_detect_a_repo_with_a_compat_file", async () => {
  assert.equal(await detectKaosRepo(folder({ ".kaos/compat.yaml": "" })), ".kaos/compat.yaml");
});

test("should_detect_a_repo_with_a_dataset_config", async () => {
  assert.equal(await detectKaosRepo(folder({ ".kubecore/dataset-config.yaml": "x: 1" })), ".kubecore/dataset-config.yaml");
});

test("should_detect_a_pipeline_py_that_imports_the_authoring_module", async () => {
  const files = { "pipeline.py": "from kubecore.authoring import pipeline, step\n" };
  assert.match(String(await detectKaosRepo(folder(files))), /pipeline\.py/);
});

test("should_stay_inactive_in_an_unrelated_repository", async () => {
  assert.equal(await detectKaosRepo(folder({ "pipeline.py": "import os\nprint('hi')\n", "README.md": "x" })), undefined);
  assert.equal(await detectKaosRepo(folder({})), undefined);
});

test("should_not_be_fooled_by_a_comment_or_a_string_that_mentions_the_module", () => {
  assert.equal(importsAuthoring("# from kubecore.authoring import step\n"), false);
  assert.equal(importsAuthoring("x = 'import kubecore.authoring'\n"), false);
});

test("should_accept_the_import_forms_people_write", () => {
  for (const text of ["import kubecore.authoring\n", "from kubecore import authoring\n", "from kubecore import (authoring)\n",
                      "from kubecore.authoring import step as s\n", "  from kubecore.authoring import step\n"]) {
    assert.equal(importsAuthoring(text), true, text);
  }
});

test("should_not_run_or_read_more_than_the_head_of_a_huge_pipeline_file", async () => {
  let asked = 0;
  const reader: FolderReader = { exists: async () => false, readHead: async (_p, max) => { asked = max; return ""; } };
  await detectKaosRepo(reader);
  assert.ok(asked > 0 && asked <= 1024 * 1024);
});
