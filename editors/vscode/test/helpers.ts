import * as fs from "fs";
import * as path from "path";

// Compiled tests live in out/test; the sources of fixtures and resources stay in the package folder.
export const PACKAGE_ROOT = path.resolve(__dirname, "..", "..");

export function fixture(name: string): string {
  return fs.readFileSync(path.join(PACKAGE_ROOT, "test", "fixtures", name), "utf8");
}

export function bundledSchemaText(): string {
  return fs.readFileSync(path.join(PACKAGE_ROOT, "resources", "step-schema.json"), "utf8");
}
