#!/usr/bin/env node
// Standalone props.json contract gate (Criterion 6, pre-render).
// Imports the SAME zod schema the Remotion composition uses
// (remotion/src/schema.ts) so there is no second source of truth, and parses
// props.json against it. Exits non-zero on any drift.
//
// Usage:  node scripts/validate_props.mjs [path/to/props.json]
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { propsSchema } from "../remotion/src/schema.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const propsPath =
  process.argv[2] ??
  path.join(here, "..", "remotion", "public", "props.json");

let raw;
try {
  raw = JSON.parse(readFileSync(propsPath, "utf8"));
} catch (e) {
  console.error(`Cannot read/parse ${propsPath}: ${e.message}`);
  process.exit(2);
}

const res = propsSchema.safeParse(raw);
if (!res.success) {
  console.error(`INVALID props.json: ${propsPath}`);
  console.error(JSON.stringify(res.error.issues, null, 2));
  process.exit(1);
}
console.log(
  `props.json OK: ${propsPath} ` +
    `(${res.data.pages.length} pages, template=${res.data.template.id}/${res.data.template.anim})`,
);
