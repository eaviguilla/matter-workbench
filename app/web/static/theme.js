// Runs in the head so the saved theme is set before the first paint. "auto" follows the system.
(function () {
  "use strict";
  try {
    var t = window.localStorage.getItem("theme");
    if (t === "light" || t === "dark") { document.documentElement.setAttribute("data-theme", t); }
  } catch (e) { /* storage blocked: stay on the system theme */ }
})();
