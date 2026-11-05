// Run with: node --test clio_filler/tests/popup.test.js
// Runs popup.js against a stub page and a stub clipboard, to check what it tells the person.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.join(__dirname, "..");
const IDS = ["message", "summary", "s-form", "s-client", "s-call", "s-answers", "s-age", "warning", "fill", "reread",
  "results", "structure", "structure-status"];

async function openPopup(clipboard) {
  const els = {};
  IDS.forEach((id) => { els[id] = { id, hidden: false, disabled: false, textContent: "", addEventListener() {}, replaceChildren() {} }; });
  const window = {};
  const ctx = vm.createContext({
    window, document: { getElementById: (id) => els[id], createElement: () => ({ appendChild() {} }) },
    navigator: { clipboard: { readText: async () => clipboard } }, chrome: {}, Date, Object, Math, Number, String, Array,
  });
  ctx.globalThis = ctx;
  for (const f of ["forms-data.js", "parse.js", "popup.js"]) { vm.runInContext(fs.readFileSync(path.join(root, f), "utf8"), ctx, { filename: f }); }
  await new Promise((r) => setImmediate(r));
  return els;
}

function copy({ form = "probate-intake-form", copied, answers = ["--- 1. What was the name of your loved one?", "Stefan"] } = {}) {
  return ["Matter Workbench answers for Clio, format 1", "Form: " + form, "Client: Nadia", "Call: 2026-10-27", "Version: 3",
    "Copied: " + copied.toISOString(), ...answers, "--- End of answers"].join("\n");
}

test("a copy with no answers cannot be filled", async () => {
  const els = await openPopup(copy({ copied: new Date(), answers: [] }));
  assert.strictEqual(els.fill.disabled, true);
  assert.match(els.message.textContent, /no answers/);
});

test("a fresh copy with an answer can be filled and shows no warning", async () => {
  const els = await openPopup(copy({ copied: new Date() }));
  assert.strictEqual(els.fill.disabled, false);
  assert.strictEqual(els.warning.hidden, true);
});

test("an old copy and a copy stamped in the future both warn", async () => {
  const old = await openPopup(copy({ copied: new Date(Date.now() - 2 * 3600 * 1000) }));
  assert.match(old.warning.textContent, /more than 30 minutes old/);
  const future = await openPopup(copy({ copied: new Date(Date.now() + 2 * 3600 * 1000) }));
  assert.match(future.warning.textContent, /in the future/);
  assert.strictEqual(future["s-age"].textContent, "time unknown");
});

test("a form name from the prototype chain is an unknown form, not a crash", async () => {
  for (const name of ["constructor", "toString", "__proto__"]) {
    const els = await openPopup(copy({ form: name, copied: new Date() }));
    assert.match(els.message.textContent, /does not know/);
    assert.strictEqual(els.fill.disabled, true);
  }
});
