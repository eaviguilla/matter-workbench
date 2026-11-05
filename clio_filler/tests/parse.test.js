// Run with: node --test clio_filler/tests/parse.test.js
const test = require("node:test");
const assert = require("node:assert");
const { parse, HEADER } = require("../parse.js");

const sample = [HEADER, "Form: probate-intake-form", "Client: Nadia", "Call: 2026-10-27", "Version: 3",
  "Copied: 2026-11-05T14:02:11.000Z", "--- 1. Name?", "Stefan Kowalczyk", "--- 2. Notes?", "line one", " --- not a block", "line three",
  "--- 3. Empty?", "", "--- End of answers"].join("\n");

test("reads the header and every answered block", () => {
  const r = parse(sample);
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.form, "probate-intake-form");
  assert.strictEqual(r.client, "Nadia");
  assert.strictEqual(r.version, "3");
  assert.strictEqual(r.copied.toISOString(), "2026-11-05T14:02:11.000Z");
  assert.deepStrictEqual(r.answers.map((a) => a.n), [1, 2]);
});

test("a line that was escaped on copy comes back as it was typed", () => {
  assert.strictEqual(parse(sample).answers[1].text, "line one\n--- not a block\nline three");
});

test("text that is not ours is refused", () => {
  assert.deepStrictEqual(parse("hello"), { ok: false, reason: "not-ours" });
  assert.deepStrictEqual(parse(""), { ok: false, reason: "not-ours" });
  assert.deepStrictEqual(parse(null), { ok: false, reason: "not-ours" });
});

test("a copy with no end line is reported as cut off", () => {
  assert.deepStrictEqual(parse(sample.replace("--- End of answers", "")), { ok: false, reason: "cut-off" });
});

test("windows line endings and leading blank lines are fine", () => {
  const r = parse("\r\n\r\n" + sample.replace(/\n/g, "\r\n"));
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.answers.length, 2);
});

test("a repeated number keeps the first answer and is reported", () => {
  const r = parse([HEADER, "Form: f", "--- 1. A?", "first", "--- 1. A?", "second", "--- End of answers"].join("\n"));
  assert.deepStrictEqual(r.repeated, [1]);
  assert.deepStrictEqual(r.answers.map((a) => a.text), ["first"]);
});

test("an unreadable time is null instead of throwing", () => {
  assert.strictEqual(parse(sample.replace(/Copied: .*/, "Copied: soon")).copied, null);
});

test("an answer line that spells the end line does not end the read", () => {
  const text = [HEADER, "Form: f", "--- 1. A?", " --- End of answers", "after", "--- 2. B?", "next", "--- End of answers"].join("\n");
  const r = parse(text);
  assert.strictEqual(r.ok, true);
  assert.deepStrictEqual(r.answers.map((a) => a.n), [1, 2]);
  assert.strictEqual(r.answers[0].text, "--- End of answers\nafter");
});

test("a Not discussed answer is dropped, with or without words after it, so Clio keeps the box empty", () => {
  const text = [HEADER, "Form: f", "--- 1. A?", "Not discussed", "--- 2. B?", "not discussed. Caller unsure.", "--- 3. C?", "Yes", "--- End of answers"].join("\n");
  assert.deepStrictEqual(parse(text).answers.map((a) => a.n), [3]);
});
