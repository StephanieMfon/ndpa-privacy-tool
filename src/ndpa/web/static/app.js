/* NDPA Privacy Check: small, dependency-free enhancements. Every page works without this file except live progress. */
(function () {
  "use strict";

  // Live progress for a running scan (server-sent events).
  var root = document.querySelector("[data-progress]");
  if (root) {
    var statusEl = root.querySelector("[data-status]");
    var elapsedEl = root.querySelector("[data-elapsed]");
    var started = Date.parse(root.dataset.started);
    var tick = function () {
      var s = Math.max(0, Math.floor((Date.now() - started) / 1000));
      elapsedEl.textContent = Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
    };
    tick();
    setInterval(tick, 1000);
    var apply = function (state) {
      state.stages.forEach(function (s) {
        var li = root.querySelector('[data-stage="' + s.key + '"]');
        if (!li) return;
        li.className = "stage stage-" + s.state;
        li.querySelector("[data-msg]").textContent = s.message || "";
      });
      if (state.position && state.position > 1) {
        statusEl.textContent = (state.position - 1) + (state.position === 2 ? " scan is" : " scans are") + " ahead of this one.";
      } else if (state.status === "queued") {
        statusEl.textContent = "Starting shortly.";
      } else {
        statusEl.textContent = "Scanning now. This usually takes two to three minutes.";
      }
    };
    var source = new EventSource("/scans/" + root.dataset.scan + "/events?after=" + (root.dataset.last || 0));
    source.addEventListener("state", function (e) { apply(JSON.parse(e.data)); });
    source.addEventListener("finished", function () {
      source.close();
      statusEl.textContent = "Finished. Opening the results.";
      setTimeout(function () { window.location.reload(); }, 600);
    });
    source.onerror = function () { statusEl.textContent = "Connection lost. Trying to reconnect…"; };
  }

  // Start-scan form: show that something is happening.
  var form = document.querySelector("[data-scan-form]");
  if (form) {
    var startButton = form.querySelector("button[type=submit]");
    var startLabel = startButton.textContent;
    form.addEventListener("submit", function () {
      startButton.disabled = true;
      startButton.textContent = "Starting…";
    });
    // Going back to this page restores it from the browser's memory: put the button back as it was.
    window.addEventListener("pageshow", function () {
      startButton.disabled = false;
      startButton.textContent = startLabel;
    });
  }

  // Filter the list of checks.
  var filters = document.querySelectorAll("[data-filter]");
  filters.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var want = btn.dataset.filter;
      filters.forEach(function (b) { b.setAttribute("aria-pressed", String(b === btn)); });
      document.querySelectorAll(".check").forEach(function (c) { c.hidden = want !== "all" && c.dataset.tone !== want; });
      document.querySelectorAll("[data-group]").forEach(function (g) {
        g.hidden = !g.querySelector(".check:not([hidden])");
      });
    });
  });

  // A link to a check (for example from "Fix first") opens it.
  var openFromHash = function () {
    var target = null;
    try { target = window.location.hash && document.querySelector(window.location.hash); } catch (e) { /* not a valid selector */ }
    if (target && target.tagName === "DETAILS") target.open = true;
  };
  window.addEventListener("hashchange", openFromHash);
  openFromHash();

  // Copy buttons.
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var done = function () {
        var label = btn.lastChild;
        var old = label.textContent;
        label.textContent = "Copied";
        setTimeout(function () { label.textContent = old; }, 1800);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(btn.dataset.copy).then(done);
    });
  });

  // Compare: exactly two ticked scans enable the button.
  var compare = document.querySelector("[data-compare-form]");
  if (compare) {
    var picks = compare.querySelectorAll("[data-pick]");
    var button = compare.querySelector("[data-compare-button]");
    var hint = document.querySelector("[data-compare-hint]");
    var update = function () {
      var chosen = Array.prototype.filter.call(picks, function (p) { return p.checked; });
      picks.forEach(function (p) { p.disabled = chosen.length >= 2 && !p.checked; });
      button.disabled = chosen.length !== 2;
      if (hint) hint.textContent = chosen.length === 2 ? "Ready to compare." : "Tick two scans to compare them.";
    };
    picks.forEach(function (p) { p.addEventListener("change", update); });
    update();
  }

  // Printing: open every check, and restore afterwards.
  var opened = [];
  window.addEventListener("beforeprint", function () {
    document.querySelectorAll("details:not([open])").forEach(function (d) { d.open = true; opened.push(d); });
  });
  window.addEventListener("afterprint", function () { opened.forEach(function (d) { d.open = false; }); opened = []; });
  document.querySelectorAll("[data-print]").forEach(function (b) { b.addEventListener("click", function () { window.print(); }); });
})();
