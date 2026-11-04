// A stand-in Clio form to try the extension on by hand. Pick the form and the markup style in the links at the top.
(function () {
  "use strict";
  var FORMS = window.MWB_FORMS, M = window.MockClio;
  var q = new URLSearchParams(location.search);
  var slug = FORMS[q.get("form")] ? q.get("form") : Object.keys(FORMS)[0];
  var layout = q.get("layout") === "B" ? "B" : "A";
  var form = FORMS[slug];
  var bar = document.getElementById("bar");

  Object.keys(FORMS).forEach(function (s) {
    var a = M.el("a", { href: "?form=" + s + "&layout=" + layout, textContent: FORMS[s].name });
    if (s === slug) { a.style.fontWeight = "700"; a.style.color = "#fff"; }
    bar.append(a);
  });
  bar.append(M.el("br"), "Markup style: ");
  ["A", "B"].forEach(function (l) {
    var a = M.el("a", { href: "?form=" + slug + "&layout=" + l, textContent: l === "A" ? "A, native inputs" : "B, buttons and a drop-down" });
    if (l === layout) { a.style.fontWeight = "700"; a.style.color = "#fff"; }
    bar.append(a);
  });
  var copy = M.el("button", { type: "button", textContent: "Copy sample answers for this form" });
  var said = M.el("span", { id: "said" });
  bar.append(copy, said);

  // The same text Copy for Clio puts on the clipboard, with sample answers, so the extension can be tried without the app.
  copy.addEventListener("click", function () {
    var lines = ["Matter Workbench answers for Clio, format 1", "Form: " + slug, "Client: Sample", "Call: 2026-11-05", "Version: 1",
      "Copied: " + new Date().toISOString()];
    M.sampleAnswers(form).forEach(function (a) { lines.push("--- " + a.n + ". " + form.entries[a.n - 1].text, a.text); });
    lines.push("--- End of answers");
    navigator.clipboard.writeText(lines.join("\n")).then(function () { said.textContent = " Copied. Now click the extension icon."; },
      function () { said.textContent = " The browser blocked the copy."; });
  });

  (layout === "A" ? M.buildA : M.buildB)(form);
  var sub = document.getElementById("sub");
  var count = M.el("span", { id: "count", textContent: "Submit pressed: 0" });
  sub.after(count);
  sub.addEventListener("click", function () { count.textContent = "Submit pressed: " + window.__submitted; });
  document.getElementById("clio").addEventListener("submit", function () { count.textContent = "Submit pressed: " + window.__submitted; });
  document.getElementById("stage").append(document.getElementById("clio"));
})();
