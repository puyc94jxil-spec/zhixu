import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { parseMarkdown } from "./markdown.js";
import { copyFeedback } from "./copy_feedback.js";

test("dangerous markup stays text and the renderer source has no innerHTML", () => {
  const source = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "[点我](javascript:alert(1))",
    "|<b>甲</b>|",
    "|---|",
    "|乙|",
  ].join("\n");
  const blocks = parseMarkdown(source);
  const flat = JSON.stringify(blocks);
  assert.equal(flat.includes("<script>"), true);
  assert.equal(flat.includes("onerror="), true);
  assert.equal(flat.includes("javascript:alert(1)"), true);
  assert.equal(flat.includes("innerHTML"), false);
  const renderer = readFileSync(new URL("./markdown.js", import.meta.url), "utf8");
  const app = readFileSync(new URL("./app.js", import.meta.url), "utf8");
  assert.equal(/\.innerHTML\b/.test(renderer), false);
  assert.equal(/\.innerHTML\b/.test(app), false);
  assert.equal(renderer.includes("textContent"), true);
});

test("copy feedback is a short message and does not include the answer", () => {
  assert.equal(copyFeedback(true), "已复制");
  assert.equal(copyFeedback(false), "复制失败，请手动选择文字");
  assert.equal(copyFeedback(true).includes("预算"), false);
});
