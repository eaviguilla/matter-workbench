// Runs inside the Clio tab. Finds each question of the chosen form by its title and puts the copied answer in the
// field that belongs to it. It sets values and ticks options only. It never submits, never leaves the page and never
// sends anything anywhere. The popup calls probe() first, then run(), and structure() on request.
(function (root) {
  "use strict";

  var DOC = root.document;
  var CANDIDATES = "label, legend, span, div, p, h1, h2, h3, h4, h5, h6, strong, b, em, td, th, dt, dd, li, a, small";
  var CONTROLS = "input, select, textarea, button, [contenteditable=''], [contenteditable='true'], [role='radio'], [role='checkbox'], [role='combobox'], [role='switch'], [role='listbox']";
  var TEXT_TYPES = { "": 1, text: 1, search: 1, tel: 1, email: 1, number: 1, url: 1, date: 1, "datetime-local": 1, month: 1 };
  var NEVER_CLICK = /^(submit|save|send|next|finish|continue|cancel|back|done|apply|delete|remove)$/i;
  var POLL_MS = 100;
  var WAIT_FOR_FOLLOW_UP_MS = 2500;

  function sleep(ms) { return new Promise(function (done) { setTimeout(done, ms); }); }

  // Titles and options are compared as lower case words, so punctuation, stars and spacing never decide a match.
  function norm(s) {
    return String(s == null ? "" : s).toLowerCase().replace(/[ ​-‍﻿]/g, " ").replace(/&/g, " and ")
      .replace(/[^a-z0-9]+/g, " ").trim();
  }
  function sameWords(a, b) {
    a = norm(a); b = norm(b);
    if (!a || !b) { return false; }
    return a === b || (a.length >= 4 && b.length >= 4 && (a.indexOf(b) === 0 || b.indexOf(a) === 0));
  }
  function titleMatches(text, wanted) {
    var t = norm(text).replace(/^\d+ /, "");
    if (!t || !wanted) { return false; }
    if (t === wanted) { return true; }
    return t.indexOf(wanted) === 0 && /^(required|optional)?$/.test(t.slice(wanted.length).trim());
  }

  function visible(el) {
    if (!el || !el.getClientRects || el.getClientRects().length === 0) { return false; }
    var style = root.getComputedStyle(el);
    return style.visibility !== "hidden" && style.display !== "none";
  }
  function labelOf(el) {
    var labels = el.labels && el.labels.length ? el.labels : null;
    if (labels) { return labels[0]; }
    if (el.id) {
      var byFor = DOC.querySelector("label[for='" + (root.CSS && root.CSS.escape ? root.CSS.escape(el.id) : el.id) + "']");
      if (byFor) { return byFor; }
    }
    return el.closest("label");
  }
  function isTick(el) { return el.tagName === "INPUT" && (el.type === "radio" || el.type === "checkbox"); }
  // A native tick box is often hidden behind a styled label, so it counts when its label shows.
  function usable(el) {
    if (visible(el)) { return true; }
    if (isTick(el)) { var l = labelOf(el); return !!l && visible(l); }
    return false;
  }
  function optionText(el) {
    if (el.tagName === "INPUT" || el.getAttribute("role") === "radio" || el.getAttribute("role") === "checkbox") {
      var l = el.tagName === "INPUT" ? labelOf(el) : null;
      if (l) { return l.textContent; }
      if (el.getAttribute("aria-label")) { return el.getAttribute("aria-label"); }
      if (el.tagName !== "INPUT" && el.textContent.trim()) { return el.textContent; }
      var next = el.nextElementSibling || el.parentElement;
      if (el.nextSibling && el.nextSibling.nodeType === 3 && el.nextSibling.textContent.trim()) { return el.nextSibling.textContent; }
      return next ? next.textContent : "";
    }
    return el.textContent;
  }

  // ---- finding the title of a question and the controls that follow it ----------------------------------------
  function snapshot() {
    var out = [];
    Array.prototype.forEach.call(DOC.querySelectorAll(CANDIDATES), function (el) {
      var raw = el.textContent;
      if (raw.length > 400 || raw.trim() === "") { return; }
      out.push({ el: el, text: norm(raw).replace(/^\d+ /, "") });
    });
    return out;
  }
  function matchesIn(snap, entry) {
    var wanted = norm(entry.clio || entry.text).replace(/^\d+ /, "");
    var hits = snap.filter(function (c) { return titleMatches(c.text, wanted) && visible(c.el); }).map(function (c) { return c.el; });
    // Keep the innermost element, so a wrapper with the same words is not taken for the title.
    return hits.filter(function (el) { return !hits.some(function (other) { return other !== el && el.contains(other); }); });
  }
  function allTitles(snap, form) {
    var list = [];
    form.entries.forEach(function (e) { matchesIn(snap, e).forEach(function (el) { if (list.indexOf(el) < 0) { list.push(el); } }); });
    return list;
  }
  function inBetween(from, to, scope) {
    var out = [];
    Array.prototype.forEach.call(scope.querySelectorAll(CONTROLS), function (c) {
      if (from.contains(c) || !(from.compareDocumentPosition(c) & 4)) { return; }
      if (to && !(to.compareDocumentPosition(c) & 2)) { return; }
      if (c.type === "hidden" || (c.tagName === "INPUT" && /^(submit|button|reset|image|file)$/.test(c.type))) { return; }
      if (c.tagName === "BUTTON" && !c.getAttribute("aria-haspopup") && !c.getAttribute("role") && !c.textContent.trim()) { return; }
      if (usable(c)) { out.push(c); }
    });
    return out;
  }
  function lowestCommonAncestor(nodes) {
    if (!nodes.length) { return DOC.body; }
    var node = nodes[0];
    while (node && !nodes.every(function (n) { return node.contains(n); })) { node = node.parentElement; }
    return node || DOC.body;
  }
  // The controls of one question: those after its title and before the title of the next question.
  function controlsFor(title, snap, form) {
    if (title.tagName === "LABEL" && title.control && usable(title.control) && !isTick(title.control)) { return [title.control]; }
    var titles = allTitles(snap, form);
    var scope = lowestCommonAncestor(titles.concat([title]));
    var next = titles.filter(function (t) { return t !== title && (title.compareDocumentPosition(t) & 4) && !title.contains(t); })
      .sort(function (a, b) { return (a.compareDocumentPosition(b) & 4) ? -1 : 1; })[0] || null;
    return inBetween(title, next, scope);
  }

  // ---- setting values -------------------------------------------------------------------------------------------
  function fire(el, names) {
    names.forEach(function (n) { el.dispatchEvent(new Event(n, { bubbles: true })); });
  }
  function setText(el, value) {
    el.focus();
    if (el.isContentEditable && el.tagName !== "INPUT" && el.tagName !== "TEXTAREA") {
      el.textContent = value;
    } else {
      var proto = el.tagName === "TEXTAREA" ? root.HTMLTextAreaElement.prototype : root.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    }
    fire(el, ["input", "change"]);
    el.blur();
    fire(el, ["blur", "focusout"]);
  }
  function press(el) {
    ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach(function (n) {
      var Ctor = n.indexOf("pointer") === 0 && root.PointerEvent ? root.PointerEvent : root.MouseEvent;
      el.dispatchEvent(new Ctor(n, { bubbles: true, cancelable: true, view: root }));
    });
  }
  function safeToClick(el) {
    if (el.tagName === "INPUT" && /^(submit|button|reset|image)$/.test(el.type)) { return false; }
    if (el.tagName === "BUTTON" && el.type === "submit" && !el.getAttribute("role")) { return false; }
    return !NEVER_CLICK.test(el.textContent.trim());
  }
  function tick(el, on) {
    if (isTick(el)) {
      if (el.disabled) { return false; }
      if (el.checked !== on) { el.click(); }
      if (el.checked !== on) { var l = labelOf(el); if (l) { l.click(); } }
      return el.checked === on;
    }
    if (!safeToClick(el)) { return false; }
    if ((el.getAttribute("aria-checked") === "true") !== on) { press(el); }
    return (el.getAttribute("aria-checked") === "true") === on;
  }
  function isoDate(text) {
    var m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(text.trim());
    if (!m) { return ""; }
    var d = new Date(Date.UTC(+m[3], +m[1] - 1, +m[2]));      // 13/45/2020 and 02/30/2020 are not dates
    if (d.getUTCFullYear() !== +m[3] || d.getUTCMonth() !== +m[1] - 1 || d.getUTCDate() !== +m[2]) { return ""; }
    return m[3] + "-" + ("0" + m[1]).slice(-2) + "-" + ("0" + m[2]).slice(-2);
  }
  function pickFromSelect(sel, answer) {
    var opts = Array.prototype.slice.call(sel.options);
    var hit = opts.filter(function (o) { return norm(o.text) === norm(answer); })[0]
      || opts.filter(function (o) { return sameWords(o.text, answer); })[0]
      || opts.filter(function (o) { return norm(o.value) === norm(answer); })[0];
    if (!hit) { return false; }
    sel.value = hit.value;
    fire(sel, ["input", "change"]);
    return true;
  }
  function selectHasAnswer(sel) {
    return sel.value !== "" && !(sel.selectedIndex === 0 && /^(select|choose|please|-+)/i.test(sel.options[0] ? sel.options[0].text.trim() : ""));
  }

  // A custom drop-down: open it, then click the entry that carries the answer.
  async function pickFromCombo(box, answer) {
    if (!safeToClick(box)) { return false; }
    press(box);
    for (var i = 0; i < 10; i += 1) {
      await sleep(POLL_MS);
      var items = Array.prototype.slice.call(DOC.querySelectorAll("[role='option'], [role='menuitem'], [role='menuitemradio'], li[data-value], ul[role='listbox'] li"))
        .filter(function (el) { return visible(el); });
      var hit = items.filter(function (el) { return norm(el.textContent) === norm(answer); })[0]
        || items.filter(function (el) { return sameWords(el.textContent, answer); })[0];
      if (hit) { press(hit); await sleep(POLL_MS); return true; }
    }
    press(box);
    return false;
  }

  // Two follow-ups can carry the same title on Clio ("Please explain."). A follow-up belongs to the box that comes after
  // its own parent question, so an answer for the later one never lands in the earlier one's box.
  function followsParent(entry, el, snap, form) {
    var parent = form.entries.filter(function (e) { return e.n === entry.when[0]; })[0];
    var at = parent ? matchesIn(snap, parent)[0] : null;
    return !at || !!(at.compareDocumentPosition(el) & 4);
  }

  // ---- filling one entry ----------------------------------------------------------------------------------------
  async function fillEntry(entry, answer, snap, form, used) {
    var title = null;
    var start = Date.now();
    for (;;) {
      var hits = matchesIn(snap, entry).filter(function (el) { return used.indexOf(el) < 0; });
      if (entry.when) { hits = hits.filter(function (el) { return followsParent(entry, el, snap, form); }); }
      title = hits[0] || null;
      if (title || !entry.when || Date.now() - start > WAIT_FOR_FOLLOW_UP_MS) { break; }
      await sleep(POLL_MS);
      snap = snapshot();
    }
    if (!title) { return { n: entry.n, status: "missing", note: entry.when ? "Clio did not show this follow-up." : "Not found on this page." }; }
    used.push(title);
    var group = controlsFor(title, snap, form);
    if (!group.length) { return { n: entry.n, status: "missing", note: "No field found under the title." }; }
    var kind = entry.kind;
    try {
      if (kind === "checkbox") { return await fillChecks(entry, answer, group); }
      if (kind === "yesno" || kind === "radio") { return await fillChoice(entry, answer, group); }
      return await fillValue(entry, answer, group);
    } catch (e) {
      return { n: entry.n, status: "flag", note: "Could not fill this one (" + e.name + ")." };
    }
  }

  async function fillValue(entry, answer, group) {
    var el = group.filter(function (c) {
      return (c.tagName === "INPUT" && TEXT_TYPES[c.type] === 1) || c.tagName === "TEXTAREA" || c.tagName === "SELECT"
        || c.isContentEditable || c.getAttribute("role") === "combobox";
    })[0];
    if (!el) { return { n: entry.n, status: "missing", note: "No box found under the title." }; }
    if (el.tagName === "SELECT") {
      if (selectHasAnswer(el)) { return { n: entry.n, status: "already", note: "Clio already has an answer." }; }
      return pickFromSelect(el, answer) ? { n: entry.n, status: "filled", note: "" } : { n: entry.n, status: "flag", note: "No choice in the list matches the answer." };
    }
    if (el.getAttribute("role") === "combobox" && el.tagName !== "INPUT") {
      return (await pickFromCombo(el, answer)) ? { n: entry.n, status: "filled", note: "" } : { n: entry.n, status: "flag", note: "Could not choose it from the list." };
    }
    var current = el.isContentEditable && el.tagName !== "INPUT" ? el.textContent : el.value;
    if (current.trim() !== "") { return { n: entry.n, status: "already", note: "Clio already has an answer." }; }
    var value = answer;
    if (entry.kind === "date") {
      var iso = isoDate(answer);
      if (!iso) { return { n: entry.n, status: "flag", note: "Not a date as MM/DD/YYYY, so it was left blank." }; }
      value = el.type === "date" ? iso : answer;
    }
    // Setting a value from code ignores maxlength, so a long answer is flagged here instead of being sent past the limit.
    var room = el.maxLength > 0 ? el.maxLength : entry.limit;
    if (room && value.length > room) { return { n: entry.n, status: "flag", note: "The answer has " + value.length + " characters and Clio takes " + room + ", so it was left blank." }; }
    setText(el, value);
    await sleep(30);
    var kept = el.isContentEditable && el.tagName !== "INPUT" ? el.textContent : el.value;
    if (kept === value) { return { n: entry.n, status: "filled", note: "" }; }
    if (kept.trim() === "") { return { n: entry.n, status: "flag", note: "The box did not take the text." }; }
    return { n: entry.n, status: "flag", note: "The box kept " + kept.length + " of " + value.length + " characters." };
  }

  function choiceControls(group) {
    var ticks = group.filter(function (c) { return (c.tagName === "INPUT" && c.type === "radio") || c.getAttribute("role") === "radio"; });
    if (ticks.length) { return { kind: "ticks", list: ticks }; }
    var sel = group.filter(function (c) { return c.tagName === "SELECT"; })[0];
    if (sel) { return { kind: "select", list: [sel] }; }
    var combo = group.filter(function (c) { return c.getAttribute("role") === "combobox" || c.getAttribute("aria-haspopup"); })[0];
    var buttons = group.filter(function (c) { return c.tagName === "BUTTON" && !c.getAttribute("aria-haspopup"); });
    if (buttons.length && !combo) { return { kind: "buttons", list: buttons }; }
    if (combo) { return { kind: "combo", list: [combo] }; }
    return { kind: "none", list: [] };
  }
  function answerWord(entry, answer) {
    if (entry.kind !== "yesno") { return answer; }
    var first = norm(answer).split(" ")[0];
    return first === "yes" ? "Yes" : (first === "no" ? "No" : answer);
  }
  async function fillChoice(entry, answer, group) {
    var want = answerWord(entry, answer);
    var found = choiceControls(group);
    if (found.kind === "select") {
      if (selectHasAnswer(found.list[0])) { return { n: entry.n, status: "already", note: "Clio already has an answer." }; }
      return pickFromSelect(found.list[0], want) ? { n: entry.n, status: "filled", note: "" } : { n: entry.n, status: "flag", note: "No choice in the list matches the answer." };
    }
    if (found.kind === "combo") {
      return (await pickFromCombo(found.list[0], want)) ? { n: entry.n, status: "filled", note: "" } : { n: entry.n, status: "flag", note: "Could not choose it from the list." };
    }
    if (found.kind === "none") { return { n: entry.n, status: "missing", note: "No choices found under the title." }; }
    var chosen = found.list.filter(function (c) {
      return found.kind === "buttons" ? c.getAttribute("aria-pressed") === "true" || c.getAttribute("aria-checked") === "true" : (c.checked || c.getAttribute("aria-checked") === "true");
    });
    if (chosen.length) { return { n: entry.n, status: "already", note: "Clio already has an answer." }; }
    var hit = found.list.filter(function (c) { return norm(optionText(c)) === norm(want); })[0]
      || found.list.filter(function (c) { return sameWords(optionText(c), want); })[0];
    if (!hit) { return { n: entry.n, status: "flag", note: "No choice is called \"" + want.slice(0, 40) + "\"." }; }
    if (found.kind === "buttons") {
      if (!safeToClick(hit)) { return { n: entry.n, status: "flag", note: "That button was left alone." }; }
      press(hit);
      await sleep(40);
      return { n: entry.n, status: "filled", note: "" };
    }
    return tick(hit, true) ? { n: entry.n, status: "filled", note: "" } : { n: entry.n, status: "flag", note: "The choice did not stay ticked." };
  }

  async function fillChecks(entry, answer, group) {
    var boxes = group.filter(function (c) { return (c.tagName === "INPUT" && c.type === "checkbox") || c.getAttribute("role") === "checkbox"; });
    if (!boxes.length) {
      var sel = group.filter(function (c) { return c.tagName === "SELECT"; })[0];
      if (sel && !selectHasAnswer(sel)) { return pickFromSelect(sel, answer.split(" | ")[0]) ? { n: entry.n, status: "filled", note: "" } : { n: entry.n, status: "flag", note: "No choice in the list matches the answer." }; }
      return { n: entry.n, status: "missing", note: "No tick boxes found under the title." };
    }
    if (boxes.some(function (b) { return b.checked || b.getAttribute("aria-checked") === "true"; })) {
      return { n: entry.n, status: "already", note: "Clio already has an answer." };
    }
    var wanted = answer.split(/ \| |\n/).map(function (s) { return s.trim(); }).filter(Boolean);
    var missed = [];
    wanted.forEach(function (w) {
      var hit = boxes.filter(function (b) { return norm(optionText(b)) === norm(w); })[0] || boxes.filter(function (b) { return sameWords(optionText(b), w); })[0];
      if (!hit || !tick(hit, true)) { missed.push(w); }
    });
    await sleep(30);
    if (missed.length) { return { n: entry.n, status: "flag", note: "Not ticked: " + missed.map(function (m) { return m.slice(0, 30); }).join(", ") + "." }; }
    return { n: entry.n, status: "filled", note: "" };
  }

  // ---- the three calls the popup makes ------------------------------------------------------------------------
  // How many of the form's always-shown questions are on this page. The popup picks the frame with the most.
  function probe(form) {
    var snap = snapshot();
    var always = form.entries.filter(function (e) { return !e.when; });
    var found = always.filter(function (e) { return matchesIn(snap, e).length > 0; }).length;
    var enough = found >= Math.max(2, Math.ceil(always.length * 0.6));
    return { found: found, total: always.length, enough: enough };
  }

  async function run(form, answers) {
    var check = probe(form);
    if (!check.enough) { return { ok: false, found: check.found, total: check.total, results: [] }; }
    var byN = {};
    answers.forEach(function (a) { byN[a.n] = a.text; });
    var results = [], used = [];
    var known = {};
    form.entries.forEach(function (e) { known[e.n] = true; });
    answers.forEach(function (a) { if (!known[a.n]) { results.push({ n: a.n, status: "flag", note: "This question is not on the form." }); } });
    for (var i = 0; i < form.entries.length; i += 1) {
      var entry = form.entries[i];
      if (byN[entry.n] === undefined) { continue; }
      var res = await fillEntry(entry, byN[entry.n], snapshot(), form, used);
      results.push(res);
      var hasKids = form.entries.some(function (e) { return e.when && e.when[0] === entry.n; });
      if (hasKids) { await sleep(150); }
    }
    results.sort(function (a, b) { return a.n - b.n; });
    return { ok: true, found: check.found, total: check.total, results: results };
  }

  // The layout of the open form without anything typed into it, for the owner to send when a field is not found.
  function structure(form) {
    var scope = null;
    var snap = snapshot();
    var titles = form ? allTitles(snap, form) : [];
    if (titles.length) { scope = lowestCommonAncestor(titles); }
    if (!scope || scope === DOC.body) { scope = DOC.querySelector("form") || DOC.querySelector("main, [role='main']"); }
    if (!scope) { return ""; }
    var copy = scope.cloneNode(true);
    Array.prototype.forEach.call(copy.querySelectorAll("script, style, link, noscript, iframe, object, embed, img, picture, video, audio, canvas"), function (n) { n.remove(); });
    Array.prototype.forEach.call(copy.querySelectorAll("svg"), function (n) { n.replaceChildren(); });
    var keep = /^(id|class|name|type|for|role|aria-[a-z]+|placeholder|disabled|readonly|required|maxlength|contenteditable|multiple|rows|cols|min|max|tabindex|hidden|checked|selected)$/;
    var all = [copy].concat(Array.prototype.slice.call(copy.querySelectorAll("*")));
    all.forEach(function (n) {
      var isChoice = n.tagName === "OPTION" || (n.tagName === "INPUT" && /^(radio|checkbox)$/.test(n.type));
      Array.prototype.slice.call(n.attributes).forEach(function (a) {
        var allowed = keep.test(a.name) || (a.name === "value" && isChoice);
        if (!allowed || a.name === "checked" || a.name === "selected") { n.removeAttribute(a.name); }
      });
      ["aria-checked", "aria-pressed", "aria-selected", "aria-valuenow", "aria-valuetext", "aria-activedescendant"].forEach(function (a) { n.removeAttribute(a); });
      var typedInto = n.tagName === "TEXTAREA" || (n.hasAttribute("contenteditable") && n.getAttribute("contenteditable") !== "false") || /^(textbox|combobox)$/.test(n.getAttribute("role") || "") || n.getAttribute("aria-haspopup") === "listbox";
      if (typedInto) { n.replaceChildren(); }
    });
    var walker = DOC.createTreeWalker(copy, 4);
    var texts = [];
    while (walker.nextNode()) { texts.push(walker.currentNode); }
    texts.forEach(function (t) { if (t.nodeValue.length > 300) { t.nodeValue = t.nodeValue.slice(0, 300); } });
    var html = copy.outerHTML;
    return html.length > 400000 ? html.slice(0, 400000) : html;
  }

  var api = { probe: probe, run: run, structure: structure, norm: norm, titleMatches: titleMatches };
  root.MWBFill = api;
})(typeof window !== "undefined" ? window : globalThis);
