// Stand-in Clio pages built from the app's own form data, in two markup styles. Used by harness.js (the tests) and sample.js
// (pages to try the extension on by hand). Layout A uses native controls. Layout B uses divs, role buttons and a custom drop-down.
(function () {
  "use strict";
  var FORMS = window.MWB_FORMS;
  window.__submitted = 0;

  function el(tag, props, kids) {
    var e = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) { if (k === "data") { Object.assign(e.dataset, props.data); } else { e[k] = props[k]; } });
    (kids || []).forEach(function (k) { e.append(k); });
    return e;
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  // ---- what the paralegal copied: one answer for each entry, opening every follow-up -------------------------
  function sampleAnswers(form) {
    var needed = {};
    form.entries.forEach(function (e) { if (e.when && !(e.when[0] in needed)) { needed[e.when[0]] = e.when[1]; } });
    var answers = [];
    form.entries.forEach(function (e) {
      var text;
      // the other branch of a yes/no question stays closed, so it gets no answer
      if (e.when && needed[e.when[0]] !== e.when[1]) { return; }
      if (e.kind === "yesno") { text = needed[e.n] || "Yes"; }
      else if (e.kind === "radio") { text = needed[e.n] || e.options[0]; }
      else if (e.kind === "checkbox") { text = [needed[e.n] || e.options[0], e.options[e.options.length - 1]].filter(function (v, i, a) { return a.indexOf(v) === i; }).join(" | "); }
      else if (e.kind === "date") { text = "09/14/2026"; }
      else { text = "Sample answer " + e.n; }
      answers.push({ n: e.n, text: text });
    });
    return answers;
  }

  // ---- layout A: native controls, label for=, a star after each title -----------------------------------------
  function buildA(form) {
    var root = el("form", { id: "clio", onsubmit: function (ev) { ev.preventDefault(); window.__submitted += 1; } });
    form.entries.forEach(function (e) {
      var id = "a" + e.n, box = el("div", { className: "field", data: { n: e.n } });
      if (e.when) { box.hidden = true; box.dataset.when = JSON.stringify(e.when); }
      var title = e.title || (e.clio + " *");
      if (e.kind === "text" || e.kind === "textarea" || e.kind === "date") {
        box.append(el("label", { htmlFor: id, textContent: title }));
        var c = e.kind === "textarea" || e.limit === null && e.kind === "textarea" ? el("textarea", { id: id }) : el("input", { id: id, type: e.kind === "date" ? "date" : "text" });
        if (e.limit && e.kind !== "date") { c.maxLength = e.limit; }
        box.append(c);
      } else {
        box.append(el("legend", { textContent: title }));
        (e.kind === "yesno" ? ["Yes", "No"] : e.options).forEach(function (o, i) {
          var cid = id + "-" + i;
          box.append(el("input", { id: cid, type: e.kind === "checkbox" ? "checkbox" : "radio", name: "g" + e.n, value: o }), el("label", { htmlFor: cid, textContent: o }));
        });
      }
      root.append(box);
    });
    root.append(el("button", { type: "submit", id: "sub", textContent: "Submit" }));
    document.body.append(root);
    root.addEventListener("change", function () { setTimeout(function () { reveal(form, "A"); }, 250); });
  }
  function readA(e) {
    if (e.kind === "text" || e.kind === "textarea" || e.kind === "date") { return document.getElementById("a" + e.n).value; }
    return Array.prototype.filter.call(document.querySelectorAll("[name=g" + e.n + "]"), function (i) { return i.checked; }).map(function (i) { return i.value; }).join(" | ");
  }

  // ---- layout B: divs, buttons with roles, a custom drop-down, wrapped labels, no label for= -------------------
  function buildB(form) {
    var root = el("div", { id: "clio" });
    form.entries.forEach(function (e) {
      var row = el("div", { className: "field", data: { n: e.n } });
      if (e.when) { row.hidden = true; row.dataset.when = JSON.stringify(e.when); }
      row.append(el("div", { className: "q-title", textContent: e.clio }));
      var ctl = el("div", { className: "ctl" });
      if (e.kind === "text") { ctl.append(el("input", { type: "text", placeholder: "Type here" })); }
      else if (e.kind === "textarea") { ctl.append(el("textarea", {})); }
      else if (e.kind === "date") { ctl.append(el("input", { type: "text", placeholder: "MM/DD/YYYY" })); }
      else if (e.kind === "yesno") {
        ["Yes", "No"].forEach(function (o) {
          var b = el("button", { type: "button", textContent: o });
          b.setAttribute("role", "radio"); b.setAttribute("aria-checked", "false");
          b.addEventListener("click", function () {
            Array.prototype.forEach.call(ctl.querySelectorAll("[role=radio]"), function (x) { x.setAttribute("aria-checked", x === b ? "true" : "false"); });
            setTimeout(function () { reveal(form, "B"); }, 250);
          });
          ctl.append(b);
        });
      } else if (e.kind === "radio") {
        var box = el("button", { type: "button", textContent: "Select" });
        box.setAttribute("role", "combobox"); box.setAttribute("aria-haspopup", "listbox");
        box.addEventListener("click", function () {
          if (document.getElementById("pop")) { document.getElementById("pop").remove(); return; }
          var pop = el("ul", { id: "pop" });
          pop.setAttribute("role", "listbox");
          e.options.forEach(function (o) {
            var li = el("li", { textContent: o });
            li.setAttribute("role", "option");
            li.addEventListener("click", function () { box.textContent = o; pop.remove(); setTimeout(function () { reveal(form, "B"); }, 250); });
            pop.append(li);
          });
          ctl.append(pop);
        });
        ctl.append(box);
      } else {
        e.options.forEach(function (o) {
          var box = el("input", { type: "checkbox", value: o });
          box.addEventListener("change", function () { setTimeout(function () { reveal(form, "B"); }, 250); });
          ctl.append(el("label", {}, [box, el("span", { textContent: " " + o })]));
        });
      }
      row.append(ctl);
      root.append(row);
    });
    root.append(el("button", { type: "submit", id: "sub", textContent: "Submit", onclick: function () { window.__submitted += 1; } }));
    document.body.append(root);
  }
  function readB(e) {
    var ctl = document.querySelector(".field[data-n='" + e.n + "'] .ctl");
    if (e.kind === "text" || e.kind === "textarea" || e.kind === "date") { return ctl.querySelector("input, textarea").value; }
    if (e.kind === "yesno") { var on = ctl.querySelector("[aria-checked=true]"); return on ? on.textContent : ""; }
    if (e.kind === "radio") { var t = ctl.querySelector("[role=combobox]").textContent; return t === "Select" ? "" : t; }
    return Array.prototype.filter.call(ctl.querySelectorAll("input"), function (i) { return i.checked; }).map(function (i) { return i.value; }).join(" | ");
  }

  // A follow-up shows after its parent holds the answer that opens it, a moment later, as Clio does.
  function reveal(form, layout) {
    form.entries.forEach(function (e) {
      if (!e.when) { return; }
      var box = document.querySelector(".field[data-n='" + e.n + "']");
      var parent = form.entries[e.when[0] - 1];
      var value = layout === "A" ? readA(parent) : readB(parent);
      box.hidden = value.split(" | ").indexOf(e.when[1]) < 0;
    });
  }


  window.MockClio = { el: el, sleep: sleep, sampleAnswers: sampleAnswers, buildA: buildA, buildB: buildB, readA: readA, readB: readB };
})();
