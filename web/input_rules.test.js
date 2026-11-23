import assert from "node:assert/strict";
import test from "node:test";
import { normalizeContent, shouldSendOnEnter } from "./input_rules.js";
import { applyEvent, createState, visibleCitations } from "./stream_state.js";

test("blank content is not sendable", () => {
  assert.equal(normalizeContent("   \n"), "");
});

test("enter sends, shift-enter and IME do not", () => {
  assert.equal(shouldSendOnEnter({ key: "Enter", shiftKey: false, isComposing: false }), true);
  assert.equal(shouldSendOnEnter({ key: "Enter", shiftKey: true, isComposing: false }), false);
  assert.equal(shouldSendOnEnter({ key: "Enter", shiftKey: false, isComposing: true }), false);
  assert.equal(shouldSendOnEnter({ key: "Enter", shiftKey: false, isComposing: false, keyCode: 229 }), false);
});

test("events stay on their conversation and deltas are not citations", () => {
  const state = createState();
  applyEvent(state, "c1", "r1", "delta", { text: "临时", provisional: true });
  applyEvent(state, "c2", "r2", "delta", { text: "别的会话", provisional: true });
  const first = state.conversations.c1.requests.r1;
  assert.equal(first.text, "临时");
  assert.equal(visibleCitations(first).length, 0);
  applyEvent(state, "c1", "r1", "citation", { verified: true, quote: "原文", chunk_id: "k" });
  assert.equal(visibleCitations(state.conversations.c1.requests.r1).length, 0);
  applyEvent(state, "c1", "r1", "done", { status: "completed" });
  assert.equal(visibleCitations(state.conversations.c1.requests.r1).length, 1);
  assert.equal(state.conversations.c2.requests.r2.text, "别的会话");
});
