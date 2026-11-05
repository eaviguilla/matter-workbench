// Reads the text that Copy for Clio puts on the clipboard in Matter Workbench. Nothing here touches the page.
//
//   Matter Workbench answers for Clio, format 1
//   Form: probate-intake-form
//   Client: Nadia Kowalczyk
//   Call: 2026-10-27
//   Version: 3
//   Copied: 2026-11-05T14:02:11.000Z
//   --- 1. What was the name of your loved one?
//   Stefan Kowalczyk
//   --- End of answers
(function (root) {
  var HEADER = "Matter Workbench answers for Clio, format 1";
  var END = "--- End of answers";

  function parse(text) {
    var lines = String(text == null ? "" : text).replace(/\r\n?/g, "\n").split("\n");
    var i = 0;
    while (i < lines.length && lines[i].trim() === "") { i += 1; }
    if (i >= lines.length || lines[i].trim() !== HEADER) { return { ok: false, reason: "not-ours" }; }
    i += 1;
    var meta = {};
    for (; i < lines.length && lines[i].indexOf("--- ") !== 0; i += 1) {
      var m = /^([A-Za-z]+):[ \t]*(.*)$/.exec(lines[i]);
      if (m) { meta[m[1].toLowerCase()] = m[2].trim(); }
    }
    var answers = [], cur = null, ended = false, repeated = [];
    var seen = {};
    for (; i < lines.length; i += 1) {
      var line = lines[i];
      if (line.replace(/[ \t]+$/, "") === END) { ended = true; break; }
      var h = /^--- (\d+)\.[ \t]*(.*)$/.exec(line);
      if (h) {
        var n = Number(h[1]);
        if (seen[n]) { repeated.push(n); cur = null; continue; }
        seen[n] = true;
        cur = { n: n, question: h[2].trim(), lines: [] };
        answers.push(cur);
      } else if (cur) {
        cur.lines.push(line);
      }
    }
    if (!ended) { return { ok: false, reason: "cut-off" }; }
    var out = [];
    answers.forEach(function (a) {
      var value = a.lines.join("\n").replace(/^ ( *-{3,})/gm, "$1").trim();
      if (value !== "" && !/^not discussed\b/i.test(value)) { out.push({ n: a.n, question: a.question, text: value }); }
    });
    var copied = meta.copied ? new Date(meta.copied) : null;
    return {
      ok: true,
      form: meta.form || "",
      client: meta.client || "",
      call: meta.call || "",
      version: meta.version || "",
      copied: copied && !isNaN(copied.getTime()) ? copied : null,
      answers: out,
      repeated: repeated
    };
  }

  var api = { parse: parse, HEADER: HEADER };
  root.MWBParse = api;
  if (typeof module !== "undefined") { module.exports = api; }
})(typeof window !== "undefined" ? window : globalThis);
