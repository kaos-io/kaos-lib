import assert from "node:assert/strict";
import { test } from "node:test";
import { downloadArgs, downloadedFile, extensionVersionFor, parseKaosctlVersion, updateNeeded } from "../src/update";

test("should_read_the_version_from_the_first_line_of_kaosctl_version", () => {
  assert.equal(parseKaosctlVersion("kaosctl 0.4.0rc7 (prerelease v0.4.0-rc.7)\nplatform: unknown (not signed in)\n"), "0.4.0rc7");
  assert.equal(parseKaosctlVersion("kaosctl 0.4.0 (stable v0.4.0)"), "0.4.0");
  assert.equal(parseKaosctlVersion("usage: kaosctl [-h]"), undefined);
  assert.equal(parseKaosctlVersion(""), undefined);
});

test("should_map_a_release_to_the_extension_published_with_it", () => {
  assert.equal(extensionVersionFor("0.4.0"), "0.4.0");
  assert.equal(extensionVersionFor("0.4.0rc7"), "0.4.0-rc.7");
  assert.equal(extensionVersionFor("0.4.0.dev3"), undefined);
  assert.equal(extensionVersionFor("0.4.0+local"), undefined);
});

test("should_offer_the_matching_extension_only_when_this_one_differs", () => {
  assert.deepEqual(updateNeeded("0.1.1", "kaosctl 0.4.0rc7 (prerelease)"), { kaosLib: "0.4.0rc7", wanted: "0.4.0-rc.7" });
  assert.equal(updateNeeded("0.4.0-rc.7", "kaosctl 0.4.0rc7 (prerelease)"), undefined);
  assert.equal(updateNeeded("0.1.1", "kaosctl 0.4.0.dev3 (local)"), undefined);
  assert.equal(updateNeeded("0.1.1", "'kaosctl' was not found"), undefined);
});

test("should_take_the_downloaded_file_from_the_last_line", () => {
  assert.deepEqual(downloadArgs("/tmp/u"), ["vscode", "install", "--download", "/tmp/u"]);
  assert.equal(downloadedFile("/tmp/u/kaos-pipeline-0.4.0-rc.7.vsix\n"), "/tmp/u/kaos-pipeline-0.4.0-rc.7.vsix");
  assert.equal(downloadedFile("note\n/tmp/u/kaos-pipeline-0.4.0.vsix\n\n"), "/tmp/u/kaos-pipeline-0.4.0.vsix");
  assert.equal(downloadedFile("ERROR: no VS Code extension is published"), undefined);
  assert.equal(downloadedFile(""), undefined);
});
