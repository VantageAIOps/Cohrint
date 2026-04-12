#!/usr/bin/env node
// Run: node knowledge/build-chunks.js > knowledge/kv-upload.json
// Reads docs.html, extracts h2/h3 sections, writes KV upload JSON to stdout.
const fs = require("fs");
const path = require("path");

const docsPath = path.resolve(__dirname, "../../vantage-final-v4/docs.html");
const html = fs.readFileSync(docsPath, "utf8");

const headingPattern = /<h[23][^>]*>(.*?)<\/h[23]>/gi;
const tagPattern = /<[^>]+>/g;

const matches = Array.from(html.matchAll(headingPattern));
const sections = [];

matches.forEach(function (match, i) {
  const heading = match[1].replace(tagPattern, "").trim();
  const start = match.index + match[0].length;
  const end = i + 1 < matches.length ? matches[i + 1].index : html.length;
  const bodyText = html
    .slice(start, end)
    .replace(tagPattern, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 500);

  if (bodyText.length > 50) {
    const key =
      "chunk:" + heading.slice(0, 40).replace(/\W+/g, "_").toLowerCase();
    sections.push({
      key: key,
      value: heading + ": " + bodyText,
      expiration_ttl: 86400 * 30,
    });
  }
});

process.stdout.write(JSON.stringify(sections, null, 2));
