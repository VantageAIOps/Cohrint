#!/usr/bin/env node
// Run: node knowledge/build-chunks.js
// Reads docs.html, extracts h2/h3 sections, writes two files:
//   knowledge/chunks.json      — array of {heading, body} objects (source of truth)
//   knowledge/kv-upload.json   — single KV entry: { key:"docs:chunks", value: <JSON> }
//
// Storing all chunks under ONE KV key means the upload costs exactly 1 write
// operation instead of N writes (one per heading), staying well within KV free limits.

const fs = require("fs");
const path = require("path");

const docsPath = path.resolve(__dirname, "../../vantage-final-v4/docs.html");
const outChunks = path.resolve(__dirname, "chunks.json");
const outKv = path.resolve(__dirname, "kv-upload.json");

const html = fs.readFileSync(docsPath, "utf8");

const headingPattern = /<h[23][^>]*>(.*?)<\/h[23]>/gi;
const tagPattern = /<[^>]+>/g;

const matches = Array.from(html.matchAll(headingPattern));
const chunks = [];

matches.forEach(function (match, i) {
  const heading = match[1].replace(tagPattern, "").trim();
  const start = match.index + match[0].length;
  const end = i + 1 < matches.length ? matches[i + 1].index : html.length;
  const body = html
    .slice(start, end)
    .replace(tagPattern, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 500);

  if (body.length > 50) {
    chunks.push({ heading, body });
  }
});

// Write human-readable chunks for inspection / version control
fs.writeFileSync(outChunks, JSON.stringify(chunks, null, 2));

// Write single-entry KV upload — 1 write op regardless of chunk count
const kvUpload = [
  {
    key: "docs:chunks",
    value: JSON.stringify(chunks),
    expiration_ttl: 86400 * 30,
  },
];
fs.writeFileSync(outKv, JSON.stringify(kvUpload, null, 2));

console.log(`Built ${chunks.length} chunks → 1 KV write (docs:chunks)`);
console.log(`  chunks.json:    ${outChunks}`);
console.log(`  kv-upload.json: ${outKv}`);
