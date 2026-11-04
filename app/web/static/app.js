// No frameworks and no network except this app's own routes. All text goes in as text, never as HTML.
(function () {
  "use strict";
  var token = document.querySelector('meta[name="csrf"]').content;

  // A button or tick box that posts a form reloads the page, and the browser would start again at the top. Keep the
  // place on the page for a moment, and put it back when the same page loads again. A link with an anchor keeps its own.
  var SCROLL_KEY = "mwb-scroll";
  function rememberScroll() {
    try { sessionStorage.setItem(SCROLL_KEY, JSON.stringify({ path: location.pathname, y: window.scrollY, at: Date.now() })); } catch (e) { /* storage may be off */ }
  }
  function restoreScroll() {
    try {
      var raw = sessionStorage.getItem(SCROLL_KEY);
      if (!raw) { return; }
      sessionStorage.removeItem(SCROLL_KEY);
      var saved = JSON.parse(raw);
      if (saved.path === location.pathname && Date.now() - saved.at < 10000 && !location.hash) { window.scrollTo(0, saved.y); }
    } catch (e) { /* nothing to restore */ }
  }
  restoreScroll();
  document.addEventListener("submit", rememberScroll);

  function say(el, msg, isReason) {
    var s = el.closest("p, div, form, section");
    var out = s && s.querySelector("[data-status]");
    if (out) {
      out.textContent = msg;
      if (isReason) { out.dataset.reason = "1"; } else { delete out.dataset.reason; }
    }
  }
  // Why a button is off, next to it. Cleared again when the button works, but never over a message about a copy.
  function reasonFor(btn, msg) {
    var s = btn.closest("p, div, form, section");
    var out = s && s.querySelector("[data-status]");
    if (!out) { return; }
    if (msg) { say(btn, msg, true); } else if (out.dataset.reason) { say(btn, ""); }
  }
  function legacyCopy(text) {
    return new Promise(function (resolve, reject) {
      var t = document.createElement("textarea");
      t.value = text; t.className = "hidden-text"; document.body.appendChild(t); t.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(t);
      ok ? resolve() : reject(new Error("copy failed"));
    });
  }
  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).catch(function () { return legacyCopy(text); });
    }
    return legacyCopy(text);
  }
  // Copy text that is not known until a request finishes. Safari only allows the clipboard write inside the
  // click, so hand it a promise; other browsers wait for the text first.
  function copyLater(promise) {
    if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
      var item = new ClipboardItem({ "text/plain": promise.then(function (t) { return new Blob([t], { type: "text/plain" }); }) });
      return navigator.clipboard.write([item]).catch(function () { return promise.then(copy); });
    }
    return promise.then(copy);
  }
  // Text typed on the client page (a change request or a pasted reply) is never thrown away by a reload.
  function hasTyped() {
    // Text that came with the page (directions saved with the call) is not unsent text until it is changed.
    var typed = Array.prototype.some.call(document.querySelectorAll("textarea[data-keep]"), function (t) {
      return t.value.trim() !== "" && t.value !== t.defaultValue;
    });
    // An answer being edited counts only when it differs from the text it started with.
    return typed || Array.prototype.some.call(document.querySelectorAll("textarea[data-answer-text]"), function (t) {
      return !t.closest(".aedit").hidden && t.value !== t.dataset.start;
    });
  }
  // Typed boxes (the pasted reply, directions) are kept in this tab as they are typed, so a reload or a click on a link
  // does not lose them. Never on disk and never in a client file. The key names the page and the box.
  function typedKey(t) {
    return t.id ? "mwb-typed:" + location.pathname + location.search.replace(/[?&](saved|hid|hidout|titled|options|gone)=[^&]*/g, "") + "#" + t.id : "";
  }
  function forgetTyped(t) {
    var k = typedKey(t);
    if (!k) { return; }
    try { window.sessionStorage.removeItem(k); } catch (e) { /* nothing to forget */ }
  }
  function post(url, body) {
    return fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify(body || {})
    });
  }

  // Theme: light or dark, saved in this browser. Until one is chosen the page follows the system setting.
  function nextTheme() {
    var root = document.documentElement, now = root.getAttribute("data-theme");
    if (now !== "light" && now !== "dark") {
      now = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    var t = now === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", t);
    try { window.localStorage.setItem("theme", t); } catch (e) { /* not saved, still applied */ }
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) { return; }
    if (b.hasAttribute("data-theme-toggle")) {
      nextTheme();
    } else if (b.dataset.copyUrl) {
      var box = b.closest("[data-copy-box]");
      var picked = box ? Array.prototype.map.call(box.querySelectorAll('input[name="output"]:checked'), function (c) { return c.value; }) : [];
      if (picked.length === 0) { say(b, "Tick at least one output first."); return; }
      var dirs = box.querySelector("[data-directions]"), dflags = box.querySelector("[data-copy-flags]");
      var okDirs = Array.prototype.map.call(dflags.querySelectorAll(".flagrow input:checked"), function (c) { return c.value; })
        .concat(confirmedWords(box));
      var reply = post(b.dataset.copyUrl, { outputs: picked, directions: dirs ? dirs.value : "", confirm: okDirs, places: placesPayload(box) }).then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) { var err = new Error(j.detail || j.error || "Not allowed yet."); err.flags = j.flags || []; err.ask = j.ask || []; throw err; }
          return j.text;
        });
      });
      copyLater(reply).then(function () {
        say(b, "Copied. Paste it into this client's chat in claude.ai.");
        dflags.textContent = ""; dflags.hidden = true;
        var chip = document.querySelector("[data-tx-status]");
        if (chip) { chip.textContent = "Copied, waiting for Claude"; chip.className = "status status-copied"; }
        // The directions are copied and saved with the call, so they are no longer unsent text. They stay in the box,
        // and a second copy sends them again until the user clears them.
        if (dirs) { dirs.defaultValue = dirs.value; forgetTyped(dirs); }
        if (box.dataset.afterCopy) {
          window.setTimeout(function () { if (!hasTyped()) { window.location.href = box.dataset.afterCopy; } }, 900);
        }
      }).catch(function (err) {
        if (err.flags && err.flags.length) { renderFlags(box, err.flags, err.message, err.ask); refreshButton(box); } else { say(b, err.message || "Could not copy."); }
      });
    } else if (b.dataset.changeUrl) {
      var cbox = b.closest("[data-change]"), ctext = cbox.querySelector("[data-change-text]"), cflags = cbox.querySelector("[data-change-flags]");
      var okWords = Array.prototype.map.call(cflags.querySelectorAll(".flagrow input:checked"), function (c) { return c.value; });
      var asked = post(b.dataset.changeUrl, { text: ctext.value, version: Number(cbox.dataset.version), latest: Number(cbox.dataset.latest), confirm: okWords, places: placesPayload(cbox) }).then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) { var err = new Error(j.error || "Not copied."); err.flags = j.flags || []; err.ask = j.ask || []; err.stale = !!j.stale; throw err; }
          return j.text;
        });
      });
      copyLater(asked).then(function () {
        renderFlags(cbox, []);
        keepTyped(cbox, "");           // the text is copied, so it is no longer kept for a reload
        say(b, "Copied. Paste it into this client's chat in claude.ai.");
      }).catch(function (err) {
        if (err.flags && err.flags.length) { renderFlags(cbox, err.flags, err.message, err.ask); refreshButton(cbox); } else { say(b, err.message || "Could not copy."); }
        if (err.stale) {
          // The page was built before a newer version was saved. The typed text is kept for the reload this asks for.
          keepTyped(cbox, ctext.value);
          var stale = document.querySelector("[data-stale-version]");
          if (stale) { stale.hidden = false; }
        }
      });
    } else if (b.dataset.copyText) {
      if (Number(b.dataset.unknown || 0) > 0 && !window.confirm("This output has unknown placeholders. Copy anyway?")) { return; }
      var src = document.querySelector(b.dataset.copyText);
      copy(src.textContent).then(function () { say(b, "Copied."); if (b.dataset.copiedKey) { markCopied(b); } }).catch(function () { say(b, "Could not copy."); });
    } else if (b.dataset.answerSave) {
      saveAnswer(b.closest(".arow"));
    } else if (b.dataset.answerCancel) {
      closeAnswer(b.closest(".arow"), true);
    } else if (b.dataset.hideWord) {
      hideWord(b);
    } else if (b.dataset.all) {
      document.querySelectorAll('[data-flag] > .choice input[type=radio][value="' + b.dataset.all + '"]').forEach(function (r) { r.checked = true; });
      document.querySelectorAll("[data-places]").forEach(function (p) { p.hidden = true; });
      gate();
    }
  });

  // Flagged words in a change request, in directions or in a message. The list is refreshed shortly after typing stops.
  // Each word is ticked to send it as written, or hidden. By default Hide covers this transcript only, and a box
  // beside the words makes it cover the client from now on. A name hidden for this transcript that is also plain
  // text in it (a month kept at review, say) is listed place by place, each with its own two choices. Copy stays off
  // until every flagged word and every place is dealt with. The server checks again when copying, so a stale list
  // never lets one through.
  function changeButton(box) { return box.querySelector("[data-change-url], [data-copy-url], #msg-copy"); }
  function flagBox(box) { return box.querySelector("[data-change-flags], [data-copy-flags], [data-msg-flags]"); }
  function typedField(box) { return box.querySelector("[data-change-text], [data-directions], [data-msg-text]"); }
  function openFlags(box) {
    var fl = flagBox(box);
    return Array.prototype.some.call(fl.querySelectorAll(".flagrow input[type=checkbox]"), function (c) { return !c.checked; }) ||
      Array.prototype.some.call(fl.querySelectorAll("[data-place-choice]"), function (f) { return !f.querySelector("input:checked"); });
  }
  function refreshButton(box) {
    if (box.hasAttribute("data-review-box")) { return; }
    var btn = changeButton(box), open = openFlags(box);
    if (box.hasAttribute("data-change")) {
      var empty = box.querySelector("[data-change-text]").value.trim() === "";
      btn.disabled = empty || open;
      reasonFor(btn, empty ? "Type a change first" : (open ? "Choose or tick each flagged word first" : ""));
    } else if (box.hasAttribute("data-outgoing")) {
      btn.disabled = typedField(box).value.trim() === "" || open;
      reasonFor(btn, open ? "Choose or tick each flagged word first" : "");
    } else {
      syncCopy(box);
    }
  }
  // Words the reviewer already ticked on the review page, kept with the directions.
  function confirmedWords(box) {
    try { return JSON.parse(box.dataset.confirmed || "[]"); } catch (e) { return []; }
  }
  // The choice made for each place that needs one, keyed by where the word starts in the typed text.
  function placeKey(start, word) { return start + "|" + word; }
  function placesPayload(box) {
    var out = [], chosen = box._places || {};
    (box._ask || []).forEach(function (a) {
      a.places.forEach(function (p) {
        var c = chosen[placeKey(p.start, a.word)];
        if (c) { out.push({ start: p.start, word: a.word, choice: c }); }
      });
    });
    return out;
  }
  // The review page posts the choices with its form, so they are mirrored into hidden fields.
  function mirrorPlaces(box) {
    var holder = box.querySelector("[data-place-inputs]");
    if (!holder) { return; }
    holder.textContent = "";
    placesPayload(box).forEach(function (p) {
      var inp = document.createElement("input");
      inp.type = "hidden"; inp.name = "dir_place"; inp.value = p.start + "|" + p.choice + "|" + p.word;
      holder.appendChild(inp);
    });
  }
  function clientOnly(box) {
    var tx = document.getElementById("msg-tx");
    return box.hasAttribute("data-outgoing") && tx && tx.value === "";
  }
  function renderFlags(box, words, message, ask) {
    var fl = flagBox(box), kept = {}, wide = false, prior = fl.querySelector("[data-also-future]");
    if (prior) { wide = prior.checked; }
    confirmedWords(box).forEach(function (w) { kept[w] = true; });
    Array.prototype.forEach.call(fl.querySelectorAll(".flagrow input:checked"), function (c) { kept[c.value] = true; });
    ask = ask || [];
    box._ask = ask;
    var old = box._places || {}, next = {}, askWords = {};
    ask.forEach(function (a) {
      askWords[a.word] = true;
      a.places.forEach(function (p) {
        var k = placeKey(p.start, a.word);
        if (old[k]) { next[k] = old[k]; } else if (box._autoHide === a.word) { next[k] = "hide"; }
      });
    });
    box._places = next;
    mirrorPlaces(box);
    fl.textContent = "";
    if (!words.length) { fl.hidden = true; return; }
    var plain = words.filter(function (w) { return !askWords[w]; });
    var p = document.createElement("p");
    p.textContent = message || "These capitalized words are not hidden. Tick a word to send it as written, or hide it. Hide keeps your words as typed and uses a code only in what is sent.";
    fl.appendChild(p);
    plain.forEach(function (w) {
      var row = document.createElement("div"), label = document.createElement("label"), input = document.createElement("input"),
          span = document.createElement("span"), hide = document.createElement("button");
      row.className = "flagrow"; label.className = "check"; input.type = "checkbox"; input.value = w; input.checked = !!kept[w];
      if (box.hasAttribute("data-review-box")) { input.name = "dir_confirm"; }
      span.textContent = w;
      hide.type = "button"; hide.className = "textbtn"; hide.dataset.hideWord = w; hide.textContent = "Hide";
      hide.setAttribute("aria-label", "Hide " + w);
      label.appendChild(input); label.appendChild(span); row.appendChild(label); row.appendChild(hide); fl.appendChild(row);
    });
    if (plain.length) {
      var also = document.createElement("label"), box2 = document.createElement("input"), txt = document.createElement("span");
      also.className = "check alsofuture"; box2.type = "checkbox"; box2.setAttribute("data-also-future", "");
      if (clientOnly(box)) {
        box2.checked = true; box2.disabled = true;
        txt.textContent = "This message is about no transcript, so Hide applies to this client from now on";
      } else {
        box2.checked = wide;
        txt.textContent = "Also hide in future transcripts for this client";
      }
      also.appendChild(box2); also.appendChild(txt); fl.appendChild(also);
    }
    ask.forEach(function (a) {
      var wrap = document.createElement("div"), head = document.createElement("p");
      wrap.className = "askword";
      head.textContent = a.word + " is hidden as " + a.code + " in places in this transcript and written as plain text in others. Choose for each place in your text.";
      wrap.appendChild(head);
      a.places.forEach(function (pl, i) {
        var row = document.createElement("div"), ctx = document.createElement("p"), mark = document.createElement("mark"),
            set = document.createElement("fieldset"), legend = document.createElement("legend"), key = placeKey(pl.start, a.word);
        row.className = "askplace";
        ctx.className = "placectx";
        mark.className = "tag tag-unknown"; mark.textContent = a.word;
        ctx.appendChild(document.createTextNode("\u2026" + pl.before)); ctx.appendChild(mark); ctx.appendChild(document.createTextNode(pl.after + "\u2026"));
        set.className = "choice"; set.setAttribute("data-place-choice", "");
        legend.className = "sr"; legend.textContent = "Place " + (i + 1) + " of " + a.places.length + " for " + a.word;
        set.appendChild(legend);
        [["hide", "Hide as " + a.code], ["send", "Send as written"]].forEach(function (o) {
          var lab = document.createElement("label"), r = document.createElement("input");
          r.type = "radio"; r.name = "place-" + (box.id || "box") + "-" + key; r.value = o[0]; r.checked = box._places[key] === o[0];
          r.dataset.placeKey = key;
          lab.appendChild(r); lab.appendChild(document.createTextNode(" " + o[1])); set.appendChild(lab);
        });
        row.appendChild(ctx); row.appendChild(set); wrap.appendChild(row);
      });
      fl.appendChild(wrap);
    });
    fl.hidden = false;
  }
  document.addEventListener("change", function (e) {
    var r = e.target.closest("input[data-place-key]");
    if (!r) { return; }
    var box = r.closest("[data-change], [data-copy-box], [data-review-box], [data-outgoing]");
    box._places = box._places || {};
    box._places[r.dataset.placeKey] = r.value;
    mirrorPlaces(box);
    if (box._onChoice) { box._onChoice(); }
    if (box.hasAttribute("data-review-box")) { preview(box); }
    refreshButton(box);
  });
  // A short line beside the box: a result or a refusal. The review page and the message page use [data-box-msg]; the other boxes use their own status.
  function boxNote(box, msg, isError) {
    var out = box.querySelector("[data-box-msg]") || box.querySelector("[data-status]");
    if (!out) { return; }
    out.textContent = msg || "";
    if (out.hasAttribute("data-box-msg")) { out.hidden = !msg; }
    out.classList.toggle("error", !!isError && !!msg);
    if (out.hasAttribute("data-status")) { delete out.dataset.reason; }
  }
  function previewReply(box, field) {
    var url = box.dataset.previewUrl;
    if (box.hasAttribute("data-review-box")) {
      // The review page sends its own form (the choices made so far), so a name hidden place by place is known here too.
      var data = new URLSearchParams(new FormData(box.closest("form")));
      data.set("directions", field.value);
      data.delete("dir_place");     // the list of places must not shrink as choices are made, so it is asked without them
      return fetch(url, { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": token }, body: data });
    }
    return post(url, { text: field.value });
  }
  function preview(box) {
    var field = typedField(box), url = box.dataset.previewUrl;
    if (!field || !url) { return; }
    var n = box._seq = (box._seq || 0) + 1;
    if (field.value.trim() === "") { renderFlags(box, []); refreshButton(box); return; }
    previewReply(box, field).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); }).then(function (res) {
      if (n !== box._seq) { return; }
      if (!res.ok || !res.j.flags) {
        if (box.hasAttribute("data-review-box")) { boxNote(box, res.j.error || res.j.detail || "The directions could not be checked.", true); }
        return;
      }
      if (box.hasAttribute("data-review-box")) { boxNote(box, ""); }
      renderFlags(box, res.j.flags, null, res.j.ask); refreshButton(box);
    }).catch(function () {});
  }
  // Hide beside a flagged word changes only what is sent. By default it covers this transcript only. The box keeps the
  // words as typed, and the server (or, on the review page, the save) replaces the word with its code. It never
  // rewrites the transcript or an output.
  function hideWord(btn) {
    var box = btn.closest("[data-change], [data-copy-box], [data-review-box], [data-outgoing]"), word = btn.dataset.hideWord;
    var also = box.querySelector("[data-also-future]"), wide = !!(also && also.checked);
    box._autoHide = word;
    if (box.hasAttribute("data-review-box")) {
      var line = document.createElement("p"), inp = document.createElement("input"), span = document.createElement("span");
      line.className = "hidline"; line.setAttribute("role", "status");
      inp.type = "hidden"; inp.name = wide ? "dir_hide_client" : "dir_hide"; inp.value = word;
      span.textContent = word + (wide ? " will be hidden for this client from now on" : " will be hidden for this transcript");
      line.appendChild(inp); line.appendChild(span);
      box.querySelector("[data-hidden-words]").appendChild(line);
      preview(box);
      return;
    }
    var body = { text: word, client: wide };
    if (box.hasAttribute("data-outgoing")) { body.tx_id = document.getElementById("msg-tx").value; }
    btn.disabled = true;
    post(box.dataset.hideUrl, body).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) { throw new Error(j.error || j.detail || "Could not hide it."); } return j; });
    }).then(function (j) {
      boxNote(box, word + (j.scope === "client" ? ": hidden for this client from now on." : ": hidden for this transcript only.") + " The transcript and outputs are unchanged.");
      if (box._onChoice) { box._onChoice(); } else { preview(box); }
    }).catch(function (err) { btn.disabled = false; boxNote(box, err.message, true); });
  }
  document.addEventListener("input", function (e) {
    var field = e.target.closest("[data-change-text], [data-directions]");
    if (!field) { return; }
    var box = field.closest("[data-change], [data-copy-box], [data-review-box]");
    if (box.hasAttribute("data-change")) { refreshButton(box); keepTyped(box, field.value); }
    window.clearTimeout(box._timer);
    box._timer = window.setTimeout(function () { preview(box); }, 450);
  });
  // The change text is also kept in this tab (never on disk and never in a client file) so a reload that a newer
  // version asks for does not lose it. It is cleared when the box is emptied or the text is copied.
  function keepTyped(box, value) {
    var key = box.dataset.storeKey;
    if (!key) { return; }
    try {
      if (value) { window.sessionStorage.setItem(key, value); } else { window.sessionStorage.removeItem(key); }
    } catch (e) { /* the text just is not kept across a reload */ }
  }
  Array.prototype.forEach.call(document.querySelectorAll("[data-change][data-store-key]"), function (box) {
    var field = box.querySelector("[data-change-text]"), saved = "";
    try { saved = window.sessionStorage.getItem(box.dataset.storeKey) || ""; } catch (e) { saved = ""; }
    if (saved && field.value === "") {
      field.value = saved;
      refreshButton(box);
      box._timer = window.setTimeout(function () { preview(box); }, 0);
    }
  });
  // Review page: the names hidden here depend on the choices made so far, so a new choice or added text checks the
  // directions again. A saved set of flags from a failed save is checked on load too.
  var reviewBox = document.querySelector("[data-review-box]");
  if (reviewBox) {
    var recheck = function () {
      window.clearTimeout(reviewBox._timer);
      reviewBox._timer = window.setTimeout(function () { preview(reviewBox); }, 450);
    };
    document.addEventListener("change", function (e) {
      if (e.target.closest("[data-flag]") || e.target.closest(".extras")) { recheck(); }
    });
    document.addEventListener("input", function (e) { if (e.target.closest(".extras")) { recheck(); } });
    // Choices already made (after a refused save) come back from the hidden fields.
    reviewBox._places = {};
    Array.prototype.forEach.call(reviewBox.querySelectorAll('[data-place-inputs] input[name="dir_place"]'), function (inp) {
      var a = inp.value.split("|"), start = a.shift(), choice = a.shift();
      reviewBox._places[placeKey(Number(start), a.join("|"))] = choice;
    });
    if (typedField(reviewBox).value.trim() !== "") { preview(reviewBox); }
  }
  function syncCopy(box) {
    var btn = box.querySelector("[data-copy-url]");
    var open = openFlags(box), none = box.querySelector('input[name="output"]:checked') === null, locked = btn.hasAttribute("data-locked");
    btn.disabled = locked || none || open;
    reasonFor(btn, locked ? "Finish the review first" : (none ? "Tick at least one output" : (open ? "Tick or hide each flagged word first" : "")));
  }
  document.addEventListener("change", function (e) {
    var box = e.target.closest("[data-change]");
    if (!box || e.target.type !== "checkbox") { return; }
    refreshButton(box);
  });
  // Ask Claude for this: tick that output in the request controls, open them and put the cursor on Copy for Claude.
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[data-ask]");
    if (!a) { return; }
    var det = document.querySelector("#request-more");
    var tick = det && det.querySelector('input[name="output"][value="' + a.dataset.ask + '"]');
    if (!tick) { return; }
    e.preventDefault();
    // Arriving from one output's button asks for that output only, not for what was ticked before.
    det.querySelectorAll('input[name="output"]').forEach(function (c) { c.checked = false; });
    det.open = true; tick.checked = true;
    var box = det.querySelector("[data-copy-box]");
    // The directions sent last time are not sent again by accident: they move to a "Last sent" line with Use again,
    // and the box starts empty.
    var dirs = box.querySelector("[data-directions]"), last = box.querySelector("[data-last-sent]");
    if (dirs && last && dirs.value.trim() !== "") {
      last.querySelector("[data-last-text]").textContent = dirs.value;
      last.hidden = false;
      dirs.value = ""; dirs.defaultValue = "";
      renderFlags(box, []);
    }
    syncCopy(box);
    det.scrollIntoView({ block: "center" });
    var go = box.querySelector("[data-copy-url]");
    if (go && !go.disabled) { go.focus(); } else { tick.focus(); }
  });
  document.addEventListener("click", function (e) {
    var u = e.target.closest("button[data-use-again]");
    if (!u) { return; }
    var box = u.closest("[data-copy-box]"), last = box.querySelector("[data-last-sent]"), dirs = box.querySelector("[data-directions]");
    dirs.value = last.querySelector("[data-last-text]").textContent;
    last.hidden = true;
    dirs.focus();
    preview(box);
  });
  // Restore what was typed in a kept box before the page was left or reloaded, and keep it up to date from now on.
  Array.prototype.forEach.call(document.querySelectorAll("textarea[data-keep]:not([data-change-text])"), function (t) {
    var key = typedKey(t), saved = "";
    if (!key) { return; }
    try { saved = window.sessionStorage.getItem(key) || ""; } catch (e) { saved = ""; }
    if (saved && saved !== t.value && t.value === t.defaultValue) {
      t.value = saved;
      t.dispatchEvent(new Event("input", { bubbles: true }));
    }
    t.addEventListener("input", function () {
      try {
        if (t.value.trim() !== "" && t.value !== t.defaultValue) { window.sessionStorage.setItem(key, t.value); }
        else { window.sessionStorage.removeItem(key); }
      } catch (e) { /* the text just is not kept across a reload */ }
    });
    if (t.form) { t.form.addEventListener("submit", function () { forgetTyped(t); }); }
  });
  // Leaving by any other way (a sidebar link, a tab, a reload, closing the tab) asks first while typed text is unsaved.
  // A form the person submits on purpose is not a loss, so it passes.
  var submitting = false;
  document.addEventListener("submit", function () { submitting = true; window.setTimeout(function () { submitting = false; }, 1500); });
  window.addEventListener("beforeunload", function (e) {
    if (!submitting && hasTyped()) { e.preventDefault(); e.returnValue = ""; }
  });
  document.addEventListener("click", function (e) {
    var g = e.target.closest("a[data-leave-guard]");
    if (g && hasTyped()) {
      if (!window.confirm("You typed text that is not copied or saved yet. Leave this page and lose it?")) { e.preventDefault(); }
      else { submitting = true; window.setTimeout(function () { submitting = false; }, 1500); }     // already asked, so no second prompt
    }
  });

  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[data-confirm-link]");
    if (a && !window.confirm(a.dataset.confirmLink)) { e.preventDefault(); }
    else if (a) { reviewLeaving = true; }
  });

  // The review page holds the only copy of the pasted text, so ask before leaving it without saving.
  var reviewLeaving = false;
  if (document.querySelector("[data-gate-form]")) {
    window.addEventListener("beforeunload", function (e) {
      if (!reviewLeaving) { e.preventDefault(); e.returnValue = ""; }
    });
    document.querySelector("[data-gate-form]").addEventListener("submit", function (e) {
      if (!e.defaultPrevented) { reviewLeaving = true; }
    });
  }

  document.addEventListener("submit", function (e) {
    var f = e.target, msg = f.dataset.confirm || (e.submitter && e.submitter.dataset.confirm);
    if (msg && !window.confirm(msg)) { e.preventDefault(); }
  });

  // Copy for Claude stays off until at least one output is ticked and every flagged word in the directions is ticked.
  document.addEventListener("change", function (e) {
    var box = e.target.closest("[data-copy-box]");
    if (box && (e.target.name === "output" || e.target.closest("[data-copy-flags]"))) { syncCopy(box); }
  });

  // Choosing a transcript or a version in a select goes straight there. Without a script the form's own button does it.
  // Typed text that is not copied or saved yet is asked about first, and the select goes back if the answer is no.
  var LEAVE = "You typed text that is not copied or saved yet. Leave this page and lose it?";
  document.addEventListener("change", function (e) {
    var sel = e.target.closest("select[data-nav-select]");
    if (!sel) { return; }
    if (hasTyped()) {
      if (!window.confirm(LEAVE)) { sel.value = sel.dataset.current; return; }
      submitting = true; window.setTimeout(function () { submitting = false; }, 1500);
    }
    var params = new URLSearchParams();
    new FormData(sel.form).forEach(function (v, k) { if (v !== "") { params.append(k, v); } });
    var col = sel.closest("section.col, .fpanel");
    window.location.href = sel.form.getAttribute("action") + "?" + params.toString() + (col ? "#" + col.id : "");
  });

  // Scrub this: selecting text in the transcript or in an output fills in the form beside it. Nothing is hidden until
  // the button is used.
  // The selection is snapped out to whole words, then lowercase words at both ends are dropped, so a drag that grabs
  // "Ruiz said" or half a name offers the name only. Words with a digit or an @ (an email, an address) always count.
  // With no capitalised word and nothing with a digit or @ left, there is nothing to offer.
  var WORD = /[\p{L}\p{N}\p{M}_'\u2019@-]/u;
  function wordAt(t, i) {
    var c = t.charAt(i);
    if (c === "") { return false; }
    if (c === ".") { return i > 0 && WORD.test(t.charAt(i - 1)) && WORD.test(t.charAt(i + 1)); }
    return WORD.test(c);
  }
  function snapWords(text, a, b) {
    while (a > 0 && wordAt(text, a - 1)) { a -= 1; }
    while (b < text.length && wordAt(text, b)) { b += 1; }
    var piece = text.slice(a, b), tokens = [], re = /\S+/g, m;
    while ((m = re.exec(piece)) !== null) {
      var raw = m[0], lead = raw.search(WORD), end = raw.length;
      if (lead === -1) { continue; }
      while (end > lead && !wordAt(raw, end - 1)) { end -= 1; }
      tokens.push({ s: m.index + lead, e: m.index + end, w: raw.slice(lead, end) });
    }
    var lower = function (t) { return /^[\p{Ll}'\u2019-]+$/u.test(t.w); };
    while (tokens.length && lower(tokens[0])) { tokens.shift(); }
    while (tokens.length && lower(tokens[tokens.length - 1])) { tokens.pop(); }
    if (!tokens.length) { return ""; }
    return piece.slice(tokens[0].s, tokens[tokens.length - 1].e).replace(/\s+/g, " ");
  }
  function selectedHideText() {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) { return ""; }
    var range = sel.getRangeAt(0), node = range.commonAncestorContainer, el = node.nodeType === 1 ? node : node.parentElement;
    var src = el && el.closest("[data-hide-source]");
    if (!src) { return ""; }
    // Text that is already highlighted is already hidden from Claude, so there is nothing to hide.
    var marks = src.querySelectorAll("mark.tag");
    for (var i = 0; i < marks.length; i += 1) { if (range.intersectsNode(marks[i])) { return ""; } }
    var before = document.createRange(), upto = document.createRange();
    before.selectNodeContents(src); before.setEnd(range.startContainer, range.startOffset);
    upto.selectNodeContents(src); upto.setEnd(range.endContainer, range.endOffset);
    return snapWords(src.textContent, before.toString().length, upto.toString().length);
  }
  function guessType(t) {
    if (t.indexOf("@") !== -1) { return "EMAIL"; }
    return /\d/.test(t) && /[A-Za-z]/.test(t) ? "ADDRESS" : "PERSON";
  }
  // A small button beside the selection: Scrub 'text', with the type to choose. It fills the Scrub this form and submits
  // it, so the same confirm and the same server route are used.
  var pop = null;
  function hidePop() { if (pop) { pop.hidden = true; } }
  function showPop(text, rect, form) {
    if (!pop) {
      pop = document.createElement("div");
      pop.className = "hidepop"; pop.setAttribute("role", "group"); pop.setAttribute("aria-label", "Scrub the selected text");
      var type = document.createElement("select"), btn = document.createElement("button");
      type.setAttribute("aria-label", "It is a");
      [["PERSON", "Person"], ["EMAIL", "Email"], ["ADDRESS", "Address"]].forEach(function (o) { type.add(new Option(o[1], o[0])); });
      btn.type = "button"; btn.className = "secondary";
      pop.appendChild(type); pop.appendChild(btn);
      pop.addEventListener("mousedown", function (e) { if (e.target.tagName !== "SELECT") { e.preventDefault(); } });
      btn.addEventListener("click", function () {
        var f = pop._form, field = f.querySelector("[data-hide-text]");
        field.value = pop._text; f.querySelector("[data-hide-type]").value = type.value;
        hidePop();
        f.requestSubmit();
      });
      document.body.appendChild(pop);
    }
    pop._text = text; pop._form = form;
    var shown = text.length > 28 ? text.slice(0, 27) + "\u2026" : text;
    pop.querySelector("select").value = guessType(text);
    pop.querySelector("button").textContent = "Scrub '" + shown + "'";
    pop.hidden = false;
    var w = pop.offsetWidth, h = pop.offsetHeight;
    var left = Math.max(8, Math.min(rect.left, window.innerWidth - w - 8));
    var top = rect.bottom + 8 + h > window.innerHeight ? Math.max(8, rect.top - h - 8) : rect.bottom + 8;
    pop.style.left = left + "px"; pop.style.top = top + "px";
  }
  function offerHide(e) {
    var field = document.querySelector("[data-hide-text]");
    if (!field) { return; }
    if (e && pop && pop.contains(e.target)) { return; }
    var t = selectedHideText();
    if (!t) { hidePop(); return; }
    t = t.slice(0, 200);
    field.value = t;
    document.querySelector("[data-hide-type]").value = guessType(t);
    var out = document.querySelector("[data-hide-status]");
    if (out) { out.textContent = "Selected text filled in. Check the type, then press Scrub this."; }
    showPop(t, window.getSelection().getRangeAt(0).getBoundingClientRect(), field.form);
  }
  ["mouseup", "touchend", "keyup"].forEach(function (name) {
    document.addEventListener(name, function (e) { window.setTimeout(function () { offerHide(e); }, 0); });
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") { hidePop(); } });
  window.addEventListener("scroll", hidePop, true);

  document.addEventListener("input", function (e) {
    var f = e.target.closest("[data-filter]");
    if (f) {
      var q = f.value.toLowerCase();
      document.querySelectorAll(f.dataset.filter).forEach(function (ul) {
        ul.querySelectorAll("li").forEach(function (li) {
          li.hidden = q !== "" && li.textContent.toLowerCase().indexOf(q) === -1;
        });
      });
    }
    if (e.target.matches('[data-flag] input[type=radio]')) {
      var item = e.target.closest("[data-flag]"), places = item.querySelector("[data-places]");
      if (places && e.target.closest(".choice") === item.querySelector(":scope > .choice")) { places.hidden = e.target.value !== "each"; }
      gate();
    }
  });

  function gate() {
    var save = document.querySelector("[data-gate-save]");
    if (!save) { return; }
    var all = Array.prototype.every.call(document.querySelectorAll("[data-flag]"), function (li) {
      var chosen = li.querySelector(":scope > .choice input[type=radio]:checked");
      if (chosen === null) { return false; }
      if (chosen.value !== "each") { return true; }
      return Array.prototype.every.call(li.querySelectorAll("[data-place]"), function (pl) {
        return pl.querySelector("input[type=radio]:checked") !== null;
      });
    });
    save.disabled = !all;
    var hint = document.querySelector("[data-gate-hint]");
    if (hint) { hint.hidden = !save.disabled; }
  }

  // Narrow the call selector by title or date. The list is rebuilt, because Safari ignores hidden options. The chosen
  // call always stays in it, and the filter box is not part of the form, so typing in it goes nowhere.
  document.addEventListener("input", function (e) {
    var f = e.target.closest("[data-tx-filter]");
    if (!f) { return; }
    var sel = document.querySelector(f.dataset.txFilter);
    if (!sel._all) {
      sel._all = Array.prototype.map.call(sel.options, function (o) { return { value: o.value, text: o.text, id: o.dataset.id }; });
    }
    var q = f.value.trim().toLowerCase(), cur = sel.dataset.current, found = 0, curShown = q === "";
    sel._all.forEach(function (o) {
      var hit = q !== "" && o.text.toLowerCase().indexOf(q) !== -1;
      if (hit) { found += 1; }
      if (o.value === cur && (hit || q === "")) { curShown = true; }
    });
    sel.textContent = "";
    // The select must never show a call that does not match as if it were chosen. When the open call is filtered out,
    // the first option says how many calls match, and choosing one of them goes to it.
    if (!curShown) {
      var first = new Option(found === 0 ? "No matches" : "Choose one of " + found + " match" + (found === 1 ? "" : "es"), "", true, true);
      first.disabled = true; sel.add(first);
    }
    sel._all.forEach(function (o) {
      if (q === "" || o.text.toLowerCase().indexOf(q) !== -1) {
        var opt = new Option(o.text, o.value, false, curShown && o.value === cur);
        opt.dataset.id = o.id; sel.add(opt);
      }
    });
    var count = document.querySelector("[data-tx-count]");
    if (count) {
      count.textContent = q === "" ? "" : (found === 0 ? "No matches" : found + (found === 1 ? " match" : " matches"));
    }
  });

  // Settings save in place and say so next to the button. Without a script the form posts and the page reloads.
  document.addEventListener("submit", function (e) {
    var f = e.target.closest("form[data-save-form]");
    if (!f || !window.fetch) { return; }
    e.preventDefault();
    var out = f.querySelector("[data-save-status]");
    out.textContent = "Saving";
    fetch(f.action, { method: "POST", credentials: "same-origin", headers: { Accept: "application/json" },
                      body: new URLSearchParams(new FormData(f)) }).then(function (r) {
      return r.json().then(function (j) {
        var cb = f.hasAttribute("data-connector") ? f.querySelector('input[type="checkbox"]') : null;
        out.textContent = r.ok ? "Saved." + (cb ? (cb.checked ? " The connector can save outputs." : " The connector is off.") : "") : (j.error || j.detail || "Not saved.");
      });
    }).catch(function () { out.textContent = "Not saved."; });
  });
  // A checkbox that saves on its own (the connector switch) saves as soon as it changes, and says so beside it.
  document.addEventListener("change", function (e) {
    var f = e.target.closest("form[data-autosave]");
    // Names is ticked while First names and Last names both are, and sets both when it changes.
    if (f && e.target.matches("[data-name-all]")) {
      f.querySelectorAll("[data-name-part]").forEach(function (c) { c.checked = e.target.checked; });
    } else if (f && e.target.matches("[data-name-part]")) {
      var all = f.querySelector("[data-name-all]");
      if (all) { all.checked = Array.prototype.every.call(f.querySelectorAll("[data-name-part]"), function (c) { return c.checked; }); }
    }
    if (f && (e.target.type === "checkbox" || e.target.tagName === "SELECT")) { f.requestSubmit(); }
    // The standing instructions for Claude name the save tool only while the connector is on.
    var shown = document.getElementById("claude-instructions");
    if (shown && e.target.name === "mcp_enabled") { shown.textContent = e.target.checked ? shown.dataset.on : shown.dataset.off; }
  });

  // Outgoing message: live scrubbed preview and copy. Flagged words and places that need a choice are listed like in the
  // other boxes. Copy stays off until each is dealt with.
  var box = document.querySelector("[data-outgoing]");
  if (box) {
    box.addEventListener("submit", function (e) { e.preventDefault(); });
    var base = box.dataset.outgoing, text = document.getElementById("msg-text"), kind = document.getElementById("msg-kind"),
        tx = document.getElementById("msg-tx"), prev = document.getElementById("msg-preview"),
        err = document.getElementById("msg-error"), timer = null;
    var payload = function () { return { text: text.value, kind: kind.value, tx_id: tx.value, places: placesPayload(box) }; };
    var render = function (segs) {
      prev.textContent = "";
      segs.forEach(function (s) {
        if (s[1]) { var m = document.createElement("mark"); m.className = "tag tag-" + s[1].toLowerCase(); m.textContent = s[0]; prev.appendChild(m); }
        else { prev.appendChild(document.createTextNode(s[0])); }
      });
    };
    var refresh = function () {
      if (!text.value.trim()) { prev.textContent = ""; renderFlags(box, []); refreshButton(box); err.classList.add("hidden"); return; }
      post(base + "/preview", payload()).then(function (r) { return r.json(); }).then(function (j) {
        err.classList.toggle("hidden", !j.error); err.textContent = j.error || "";
        if (j.error) { prev.textContent = ""; return; }
        render(j.segments);
        renderFlags(box, j.flags, null, j.ask); refreshButton(box);
      }).catch(function () { err.classList.remove("hidden"); err.textContent = "Preview failed."; });
    };
    box._onChoice = refresh;
    [text, kind, tx].forEach(function (el) {
      ["input", "change"].forEach(function (ev) {
        el.addEventListener(ev, function () { window.clearTimeout(timer); timer = window.setTimeout(refresh, 350); });
      });
    });
    document.getElementById("msg-copy").addEventListener("click", function () {
      var b = this, body = payload();
      body.confirm = box.querySelector(".flagrow") ? "1" : "";       // every flagged word is ticked by now
      var reply = post(base + "/copy", body).then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) {
            err.classList.remove("hidden"); err.textContent = j.error || "Not copied.";
            if (j.flags && j.flags.length) { renderFlags(box, j.flags, j.error, j.ask); refreshButton(box); }
            throw new Error(j.error || "Not copied.");
          }
          return j.text;
        });
      });
      copyLater(reply).then(function () { say(b, "Copied."); }).catch(function () { say(b, "Not copied."); });
    });
  }
  // Intake forms: one copy box per answer. The answers copied so far are marked, kept in this tab only (question
  // numbers, never the text), and forgotten when a new version of the form is saved because the key holds the version.
  function copiedKey(list) { return "mwb-copied:" + list.dataset.tx + ":" + list.dataset.slug + ":v" + list.dataset.version; }
  function copiedList(list) {
    try { return JSON.parse(window.sessionStorage.getItem(copiedKey(list)) || "[]"); } catch (e) { return []; }
  }
  function paintCopied(list) {
    var done = copiedList(list);
    Array.prototype.forEach.call(list.querySelectorAll(".arow"), function (row) {
      row.classList.toggle("copied", done.indexOf(Number(row.dataset.n)) >= 0);
    });
  }
  function markCopied(b) {
    var row = b.closest(".arow"), list = row.closest("[data-answers]"), done = copiedList(list), n = Number(row.dataset.n);
    if (done.indexOf(n) < 0) { done.push(n); }
    try { window.sessionStorage.setItem(copiedKey(list), JSON.stringify(done)); } catch (e) { /* marks are only a help */ }
    paintCopied(list);
  }
  Array.prototype.forEach.call(document.querySelectorAll("[data-answers]"), paintCopied);

  // Editing one answer in place. Without a script the Edit link opens the edit page at that question.
  function openAnswer(row) {
    row.querySelector(".abox > .answer, .abox > .empty") && (row.querySelector(".abox > .answer, .abox > .empty").hidden = true);
    var ed = row.querySelector(".aedit"), ta = ed.querySelector("textarea");
    ed.hidden = false; ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  }
  function closeAnswer(row, discard) {
    var ed = row.querySelector(".aedit"), ta = ed.querySelector("textarea"), msg = ed.querySelector("[data-answer-msg]");
    if (discard) { ta.value = ta.dataset.start; }
    ed.hidden = true; msg.hidden = true;
    var shown = row.querySelector(".abox > .answer, .abox > .empty");
    if (shown) { shown.hidden = false; }
  }
  function saveAnswer(row) {
    var list = row.closest("[data-answers]"), ed = row.querySelector(".aedit"), ta = ed.querySelector("textarea");
    var msg = ed.querySelector("[data-answer-msg]");
    if (ta.value === ta.dataset.start) { closeAnswer(row, true); return; }
    post(list.dataset.answersUrl, { n: Number(row.dataset.n), text: ta.value, version: Number(list.dataset.version) }).then(function (r) {
      return r.json().then(function (j) {
        if (r.ok) { ta.dataset.start = ta.value; window.location.assign(window.location.pathname + window.location.search); return; }
        msg.textContent = j.error || "Not saved."; msg.hidden = false;
        if (j.stale) { var note = list.closest(".fpanel").querySelector("[data-answer-stale]"); if (note) { note.hidden = false; } }
      });
    }).catch(function () { msg.textContent = "Not saved."; msg.hidden = false; });
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[data-answer-edit]");
    if (!a || !a.closest("[data-answers]")) { return; }
    e.preventDefault();
    openAnswer(a.closest(".arow"));
  });
  document.addEventListener("keydown", function (e) {
    var ta = e.target.closest && e.target.closest("textarea[data-answer-text]");
    if (!ta) { return; }
    var row = ta.closest(".arow");
    if (e.key === "Escape") { e.preventDefault(); closeAnswer(row, true); }
    else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); saveAnswer(row); }
  });
  // Pick up outputs saved by the optional connector while this page is open.
  var poll = document.querySelector("[data-poll]");
  if (poll) {
    window.setInterval(function () {
      if (document.hidden) { return; }
      fetch(poll.dataset.poll, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (j) {
        if (j.version > Number(poll.dataset.version)) {
          // Never reload over typed text. Offer the reload instead.
          var note = document.querySelector("[data-new-version]");
          if (hasTyped() && note) { note.hidden = false; } else { location.reload(); }
        }
      }).catch(function () {});
    }, 5000);
  }
  // Typing a new client's name chooses "new client" without a second click.
  var firstName = document.querySelector("#first-name");
  if (firstName) {
    firstName.addEventListener("input", function () {
      var radio = document.querySelector('input[name="client"][value="new"]');
      if (radio) { radio.checked = true; }
    });
  }
  gate();
})();
