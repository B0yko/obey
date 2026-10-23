// SPDX-License-Identifier: Apache-2.0
// Generates src/generated/api-types.ts from components.schemas in openapi.yaml.
//
// The parser only understands the small YAML subset that openapi.yaml uses: nested mappings,
// scalars and one-line [a, b] lists. Usage: node scripts/gen-types.mjs [--check]

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const specPath = resolve(root, "openapi.yaml");
const outPath = resolve(root, "src/generated/api-types.ts");

const HEADER = [
  "// SPDX-License-Identifier: Apache-2.0",
  "// Generated from openapi.yaml by scripts/gen-types.mjs — do not edit.",
];

function unquote(text) {
  const match = /^(['"])(.*)\1$/.exec(text);
  return match ? match[2] : text;
}

function parseValue(text) {
  if (text.startsWith("[") && text.endsWith("]")) {
    const parts = text.slice(1, -1).split(",");
    return parts.map((part) => unquote(part.trim())).filter((part) => part !== "");
  }
  return unquote(text);
}

function parseYaml(text) {
  const rootNode = {};
  const stack = [{ indent: -1, node: rootNode }];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (line === "" || line.startsWith("#")) continue;
    const indent = raw.length - raw.trimStart().length;
    const match = /^([^:]+?):(?:\s+(.*))?$/.exec(line);
    if (!match) throw new Error(`unsupported YAML line: ${raw}`);
    while (stack[stack.length - 1].indent >= indent) stack.pop();
    const parent = stack[stack.length - 1].node;
    const key = unquote(match[1].trim());
    if (match[2] === undefined) {
      parent[key] = {};
      stack.push({ indent, node: parent[key] });
    } else {
      parent[key] = parseValue(match[2].trim());
    }
  }
  return rootNode;
}

const pascal = (name) => name.charAt(0).toUpperCase() + name.slice(1);
const upperSnake = (name) => name.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toUpperCase();

function tsType(schemaName, propName, prop, extras) {
  if (prop.$ref) return prop.$ref.split("/").pop();
  if (prop.enum) {
    const typeName = `${schemaName}${pascal(propName)}`;
    const constName = `${upperSnake(schemaName)}_${upperSnake(propName)}_VALUES`;
    const values = prop.enum.map((value) => JSON.stringify(value)).join(", ");
    extras.push(`export const ${constName} = [${values}] as const;`);
    extras.push(`export type ${typeName} = (typeof ${constName})[number];`, "");
    return typeName;
  }
  switch (prop.type) {
    case "string":
      return "string";
    case "integer":
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "array":
      return `${tsType(schemaName, propName, prop.items, extras)}[]`;
    default:
      throw new Error(`unsupported type for ${schemaName}.${propName}: ${prop.type}`);
  }
}

function render(spec) {
  const lines = [...HEADER, ""];
  for (const [name, schema] of Object.entries(spec.components.schemas)) {
    const required = schema.required ?? [];
    const extras = [];
    const fields = Object.entries(schema.properties).map(([propName, prop]) => {
      const optional = required.includes(propName) ? "" : "?";
      return `  ${propName}${optional}: ${tsType(name, propName, prop, extras)};`;
    });
    lines.push(...extras, `export interface ${name} {`, ...fields, "}", "");
  }
  return lines.join("\n");
}

const output = render(parseYaml(readFileSync(specPath, "utf8")));

if (process.argv.includes("--check")) {
  if (readFileSync(outPath, "utf8") !== output) {
    console.error("src/generated/api-types.ts is out of date; run `pnpm gen:types`.");
    process.exitCode = 1;
  } else {
    console.log("src/generated/api-types.ts is up to date.");
  }
} else {
  writeFileSync(outPath, output);
  console.log("wrote src/generated/api-types.ts");
}
