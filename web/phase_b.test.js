import assert from "node:assert/strict";
import test from "node:test";
import { parseMarkdown } from "./markdown.js";

test("markdown blocks keep script text as text", () => {
  const blocks = parseMarkdown("段落\n\n<script>alert(1)</script>\n\n- 一项\n\n```\n代码\n```\n\n|甲|乙|\n|---|---|\n|1|2|");
  const types = blocks.map((block) => block.type);
  assert.deepEqual(types, ["paragraph", "paragraph", "list", "code", "table"]);
  assert.equal(blocks[1].text.includes("<script>"), true);
  assert.equal(JSON.stringify(blocks).includes("innerHTML"), false);
});

test("template availability follows ready files", async () => {
  const { templateState } = await import("./templates.js");
  const blocked = templateState([{ status: "failed", enabled: 1 }]);
  assert.equal(blocked.find((item) => item.id === "summary").enabled, false);
  assert.equal(blocked.find((item) => item.id === "free").enabled, true);
  const open = templateState([{ status: "ready", enabled: 1 }]);
  assert.equal(open.find((item) => item.id === "summary").enabled, true);
});

test("upload rules explain limits before submit", async () => {
  const { uploadBlockReason } = await import("./upload_rules.js");
  assert.match(uploadBlockReason([], { name: "a.png", size: 10 }), /只接受/);
  assert.match(uploadBlockReason([], { name: "a.pdf", size: 20 * 1024 * 1024 + 1 }), /20MB/);
  assert.equal(uploadBlockReason([], { name: "a.pdf", size: 12 }), "");
});
