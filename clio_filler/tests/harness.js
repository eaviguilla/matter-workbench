// Test harness for headless Chrome. It builds stand-in Clio pages from the app's own form data in two different markup
// styles, runs the filler on them and writes what happened to #out as JSON. tests/test_clio_filler.py reads that back.
(async function () {
  "use strict";
  var FORMS = window.MWB_FORMS;
  var report = [];

  var M = window.MockClio, el = M.el, sleep = M.sleep, sampleAnswers = M.sampleAnswers, buildA = M.buildA, buildB = M.buildB, readA = M.readA, readB = M.readB;
  function expected(form, layout, e, text) {
    if (e.kind === "date" && layout === "A") { var m = /^(\d\d)\/(\d\d)\/(\d{4})$/.exec(text); if (!m) { return ""; } return m[3] + "-" + m[1] + "-" + m[2]; }
    return text;
  }

  async function scenario(name, slug, layout, setup) {
    document.body.replaceChildren(el("pre", { id: "scratch" }));
    var form = FORMS[slug];
    (layout === "A" ? buildA : buildB)(form);
    var answers = sampleAnswers(form);
    if (setup) { answers = setup(form, answers) || answers; }
    var run = await window.MWBFill.run(form, answers);
    await sleep(400);
    var back = {};
    form.entries.forEach(function (e) {
      var box = document.querySelector(".field[data-n='" + e.n + "']");
      if (box && !box.hidden) { back[e.n] = layout === "A" ? readA(e) : readB(e); }
    });
    var want = {};
    answers.forEach(function (a) { var e = form.entries[a.n - 1]; want[a.n] = expected(form, layout, e, a.text); if (name === "limits" && a.n === 1) { want[a.n] = ""; } });
    report.push({ name: name, slug: slug, layout: layout, run: run, back: back, want: want, submitted: window.__submitted });
  }

  var slugs = Object.keys(FORMS);
  for (var i = 0; i < slugs.length; i += 1) {
    await scenario("basic", slugs[i], "A");
    await scenario("basic", slugs[i], "B");
  }
  // a box that already holds an answer is left alone
  await scenario("already", "probate-intake-form", "A", function () {
    document.getElementById("a1").value = "keep me";
    document.getElementById("a7-0").checked = true;
  });
  // text longer than the box takes, and a date that is not a date
  await scenario("limits", "probate-intake-form", "A", function (form, answers) {
    answers[0].text = new Array(301).join("x");
    answers[4].text = "14 September, year not said";
  });
  // a follow-up whose parent never got its answer is reported, not guessed
  await scenario("orphan", "probate-intake-form", "B", function (form) {
    return [{ n: 8, text: "2217 Vista Alegre Drive" }];
  });
  // a page that is not this form is refused
  document.body.replaceChildren(el("p", { textContent: "Nothing to see here." }));
  report.push({ name: "wrongpage", run: await window.MWBFill.run(FORMS["probate-intake-form"], sampleAnswers(FORMS["probate-intake-form"])) });
  // the layout copy holds titles and no typed values
  await scenario("structure", "probate-intake-form", "A");
  // put typed-looking values in the markup itself, where a copy of the page would carry them
  Array.prototype.forEach.call(document.querySelectorAll("input[type=text], input[type=date]"), function (i) { i.setAttribute("value", "TYPED-VALUE"); });
  Array.prototype.forEach.call(document.querySelectorAll("textarea"), function (t) { t.textContent = "TYPED-VALUE"; });
  var note = el("div", { id: "note", textContent: "TYPED-VALUE" }); note.setAttribute("contenteditable", "true");
  var pick = el("button", { type: "button", id: "pick", textContent: "TYPED-VALUE" }); pick.setAttribute("role", "combobox"); pick.setAttribute("aria-checked", "true");
  document.getElementById("clio").append(note, pick);
  report.push({ name: "structure-html", html: window.MWBFill.structure(FORMS["probate-intake-form"]) });
  document.body.replaceChildren(el("pre", { id: "out", textContent: JSON.stringify(report) }));
  document.title = "done";
})();
