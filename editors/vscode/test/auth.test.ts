import assert from "node:assert/strict";
import * as path from "path";
import { test } from "node:test";
import { describeSession, isHttpsUrl, readIssuer, sessionFilePath } from "../src/auth";

test("should_find_the_session_where_kaosctl_keeps_it", () => {
  assert.equal(sessionFilePath({}, "/home/u"), path.join("/home/u", ".config", "kubecore-ml", "lakefs-session.json"));
  assert.equal(sessionFilePath({ KUBECORE_ML_HOME: "/x" }, "/home/u"), path.join("/x", "lakefs-session.json"));
});

test("should_say_not_signed_in_without_a_session", () => {
  assert.match(describeSession({ exists: false }, 0), /Not signed in/);
});

test("should_say_how_old_the_session_is_and_never_claim_it_is_valid", () => {
  const now = 1_000_000_000_000;
  assert.match(describeSession({ exists: true, modifiedMs: now - 10 * 60_000 }, now), /less than an hour ago/);
  assert.match(describeSession({ exists: true, modifiedMs: now - 5 * 3_600_000 }, now), /5 hours ago/);
  assert.match(describeSession({ exists: true, modifiedMs: now - 72 * 3_600_000 }, now), /3 days ago/);
  assert.match(describeSession({ exists: true, modifiedMs: now }, now), /run 'KAOS: Sign in' again/);
});

test("should_read_the_issuer_from_a_dataset_config", () => {
  assert.equal(readIssuer("oidcIssuer: https://id.example.org\noidcClientId: abc\n"), "https://id.example.org");
  assert.equal(readIssuer('oidcIssuer: "https://id.example.org" # comment\n'), "https://id.example.org");
  assert.equal(readIssuer("other: 1\n"), undefined);
});

test("should_only_accept_https_issuers_for_the_confirmation", () => {
  assert.equal(isHttpsUrl("https://id.example.org"), true);
  assert.equal(isHttpsUrl("http://id.example.org"), false);
  assert.equal(isHttpsUrl("javascript:alert(1)"), false);
  assert.equal(isHttpsUrl("not a url"), false);
});
