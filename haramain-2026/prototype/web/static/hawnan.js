/* Shared helpers for the Hawnan pages. No framework, no build step, no CDN.
   Digits are always Western: we never call locale-aware number formatting. */
window.H = (function () {
  "use strict";
  var SIM_AR = "بيانات تصاريح محاكاة معلنة", SIM_EN = "Simulated permit data (declared)";
  async function api(path, opts) {
    opts = opts || {};
    var headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    var r = await fetch(path, { method: opts.method || "GET", headers: headers, body: opts.body != null ? JSON.stringify(opts.body) : undefined, credentials: "same-origin" });
    var data = null; try { data = await r.json(); } catch (e) { data = {}; }
    if (!r.ok) { var err = new Error(typeof data.detail === "string" ? data.detail : (r.status + " " + r.statusText)); err.status = r.status; err.data = data; throw err; }
    return data;
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function hhmm(ts) { var d = ts == null ? new Date() : new Date(ts * 1000); return pad2(d.getHours()) + ":" + pad2(d.getMinutes()); }
  function madinah(ts) { var d = new Date((ts == null ? Date.now() : ts * 1000) + 3 * 3600 * 1000); return pad2(d.getUTCHours()) + ":" + pad2(d.getUTCMinutes()); }
  function fill(tpl, vars) { return String(tpl || "").replace(/\{(\w+)\}/g, function (m, k) { return k in vars ? vars[k] : m; }); }
  var store = {
    get: function (k, d) { try { var v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
    del: function (k) { try { localStorage.removeItem(k); } catch (e) {} }
  };
  function qs(k) { return new URLSearchParams(location.search).get(k); }
  function setDir(lang, dir) { document.documentElement.lang = lang; document.documentElement.dir = dir; }
  function banner() {
    if (document.querySelector(".banner-sim")) return;
    var b = document.createElement("div"); b.className = "banner-sim"; b.setAttribute("role", "note");
    b.innerHTML = '<span class="dot"></span><span dir="rtl" lang="ar">' + SIM_AR + '</span><span class="sep">·</span><span dir="ltr" lang="en">' + SIM_EN + "</span>";
    document.body.prepend(b);
  }
  function fonts() {
    // Optional: Google Fonts when the device is online; the system font stack is the fallback (demo hotspot has no internet).
    if (!navigator.onLine) return;
    window.addEventListener("load", function () {
      var l = document.createElement("link"); l.rel = "stylesheet";
      l.href = "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&display=swap";
      document.head.appendChild(l);
    });
  }
  function el(id) { return document.getElementById(id); }
  function poll(fn, ms) { var stop = false; (async function loop() { while (!stop) { try { await fn(); } catch (e) { /* page shows its own offline state */ } await new Promise(function (r) { setTimeout(r, ms); }); } })(); return function () { stop = true; }; }
  function ago(ts) { var s = Math.max(0, Math.round(Date.now() / 1000 - ts)); return s < 60 ? s + " s" : Math.round(s / 60) + " min"; }
  fonts();
  document.addEventListener("DOMContentLoaded", banner);
  return { api: api, esc: esc, hhmm: hhmm, madinah: madinah, fill: fill, store: store, qs: qs, setDir: setDir, banner: banner, el: el, poll: poll, ago: ago, SIM_AR: SIM_AR, SIM_EN: SIM_EN };
})();
