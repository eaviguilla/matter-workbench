// The popup. It reads the clipboard, checks the text came from Copy for Clio, and on one click fills the open Clio tab.
// Everything stays on this computer: nothing here talks to a server.
(function () {
  "use strict";
  var FORMS = window.MWB_FORMS;
  var STALE_MS = 30 * 60 * 1000;
  var LABEL = { filled: "Filled", already: "Already filled", missing: "Not found", flag: "Check" };
  var parsed = null, form = null, confirmedStale = false;

  function $(id) { return document.getElementById(id); }
  function say(text) { $("message").textContent = text; }
  function warn(text) { var w = $("warning"); w.hidden = !text; w.textContent = text || ""; }

  function age(date) {
    var minutes = Math.round((Date.now() - date.getTime()) / 60000);
    if (minutes < 1) { return "just now"; }
    if (minutes < 60) { return minutes + " minute" + (minutes === 1 ? "" : "s") + " ago"; }
    var hours = Math.round(minutes / 60);
    return hours + " hour" + (hours === 1 ? "" : "s") + " ago";
  }

  async function load() {
    $("results").hidden = true; $("summary").hidden = true; warn(""); $("fill").disabled = true; $("fill").textContent = "Fill this page";
    confirmedStale = false; parsed = null; form = null;
    var text = null;
    try { text = await navigator.clipboard.readText(); } catch (e) { text = null; }
    if (text === null) { say("Chrome did not let the extension read the clipboard. Press Read clipboard again."); return; }
    parsed = window.MWBParse.parse(text);
    if (!parsed.ok) {
      say(parsed.reason === "cut-off"
        ? "The copied text looks cut off. In Matter Workbench, press Copy for Clio again."
        : "The clipboard does not hold answers from Copy for Clio. In Matter Workbench, press Copy for Clio on a form, then open this again.");
      return;
    }
    form = FORMS[parsed.form];
    if (!form) { say("This copy is for a form this version does not know (" + parsed.form + "). Update the extension."); return; }
    $("s-form").textContent = form.name;
    $("s-client").textContent = parsed.client || "Not named";
    $("s-call").textContent = parsed.call || "";
    $("s-answers").textContent = parsed.answers.length + " answered" + (parsed.version ? ", version " + parsed.version : "");
    $("s-age").textContent = parsed.copied ? age(parsed.copied) : "time unknown";
    $("summary").hidden = false;
    say("Ready. Open the blank " + form.name + " in Clio, then press Fill this page.");
    if (!parsed.copied || Date.now() - parsed.copied.getTime() > STALE_MS) {
      warn("This copy is more than 30 minutes old. Check the client above is the one whose matter is open in Clio.");
    }
    if (parsed.repeated.length) { warn("Question " + parsed.repeated.join(", ") + " appears twice in the copy. The first one is used."); }
    $("fill").disabled = false;
  }

  async function activeTab() {
    var tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    return tabs[0] || null;
  }
  async function inject(tab) {
    await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ["fill.js"] });
  }

  async function fill() {
    var stale = !parsed.copied || Date.now() - parsed.copied.getTime() > STALE_MS;
    if (stale && !confirmedStale) { confirmedStale = true; $("fill").textContent = "Fill anyway"; return; }
    $("fill").disabled = true;
    var tab = await activeTab();
    if (!tab) { say("No tab is open."); $("fill").disabled = false; return; }
    try {
      await inject(tab);
      var probes = await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, func: function (f) { return window.MWBFill.probe(f); }, args: [form] });
      probes = probes.filter(function (p) { return p.result; }).sort(function (a, b) { return b.result.found - a.result.found; });
      var best = probes[0];
      if (!best || !best.result.enough) {
        say("This page does not look like the " + form.name + ". Found " + (best ? best.result.found : 0) + " of " + (best ? best.result.total : "its") + " question titles. Nothing was filled.");
        $("fill").disabled = false;
        return;
      }
      var out = await chrome.scripting.executeScript({ target: { tabId: tab.id, frameIds: [best.frameId] }, func: function (f, a) { return window.MWBFill.run(f, a); }, args: [form, parsed.answers] });
      show(out[0].result);
    } catch (e) {
      say("Chrome would not let the extension use this tab. Open the Clio form in a normal tab and try again.");
    }
    $("fill").disabled = false;
  }

  function show(report) {
    var list = $("results");
    list.replaceChildren();
    var counts = { filled: 0, already: 0, missing: 0, flag: 0 };
    var questions = {};
    form.entries.forEach(function (e) { questions[e.n] = e.text; });
    report.results.forEach(function (r) {
      counts[r.status] += 1;
      var li = document.createElement("li");
      [["n", r.n + "."], ["q", questions[r.n] || ""], ["s " + r.status, LABEL[r.status]]].forEach(function (pair) {
        var span = document.createElement("span");
        span.className = pair[0]; span.textContent = pair[1]; li.appendChild(span);
      });
      list.appendChild(li);
      if (r.note) {
        var why = document.createElement("li");
        why.className = "why"; why.textContent = r.note; list.appendChild(why);
      }
    });
    list.hidden = false;
    say("Filled " + counts.filled + ". Already filled " + counts.already + ". Not found " + counts.missing + ". To check " + counts.flag + ". Look over the page, then submit it yourself.");
  }

  async function copyStructure() {
    var status = $("structure-status");
    status.textContent = "";
    try {
      var tab = await activeTab();
      await inject(tab);
      var out = await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, func: function (f) { return window.MWBFill.structure(f); }, args: [form || null] });
      var best = out.map(function (o) { return o.result || ""; }).sort(function (a, b) { return b.length - a.length; })[0];
      if (!best) { status.textContent = "Found no form on this page."; return; }
      await navigator.clipboard.writeText(best);
      status.textContent = "Copied " + Math.round(best.length / 1024) + " KB of layout. Paste it where you send it.";
    } catch (e) {
      status.textContent = "Could not read this tab.";
    }
  }

  $("fill").addEventListener("click", fill);
  $("reread").addEventListener("click", load);
  $("structure").addEventListener("click", copyStructure);
  load();
})();
