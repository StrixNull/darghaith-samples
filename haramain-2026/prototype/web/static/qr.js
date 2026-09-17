/* Tiny QR encoder (ISO 18004), byte + alphanumeric modes, versions 1–20, EC level M.
   No dependencies; written for the Hawnan batch pass. Base45 passes use the
   alphanumeric mode, so a 240-character pass fits a version-9 symbol. */
window.QR = (function () {
  "use strict";
  var TOTAL = [0, 26, 44, 70, 100, 134, 172, 196, 242, 292, 346, 404, 466, 532, 581, 655, 733, 815, 901, 991, 1085];
  var ECM = [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26];
  var NBM = [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16];
  var ALIGN = { 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50], 11: [6, 30, 54], 12: [6, 32, 58], 13: [6, 34, 62], 14: [6, 26, 46, 66], 15: [6, 26, 48, 70], 16: [6, 26, 50, 74], 17: [6, 30, 54, 78], 18: [6, 30, 56, 80], 19: [6, 30, 58, 84], 20: [6, 34, 62, 90] };
  var ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:";
  var EXP = new Uint8Array(512), LOG = new Uint8Array(256);
  (function () { var x = 1; for (var i = 0; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d; } for (var j = 255; j < 512; j++) EXP[j] = EXP[j - 255]; })();
  function mul(a, b) { return (a && b) ? EXP[LOG[a] + LOG[b]] : 0; }
  function genPoly(n) { var g = [1]; for (var i = 0; i < n; i++) { var ng = new Array(g.length + 1).fill(0); for (var j = 0; j < g.length; j++) { ng[j] ^= g[j]; ng[j + 1] ^= mul(g[j], EXP[i]); } g = ng; } return g; }
  function rs(data, n) { var g = genPoly(n), res = new Array(n).fill(0); for (var i = 0; i < data.length; i++) { var f = data[i] ^ res[0]; res.shift(); res.push(0); if (f) for (var j = 0; j < n; j++) res[j] ^= mul(g[j + 1], f); } return res; }
  function utf8(s) { return Array.from(new TextEncoder().encode(s)); }

  function makeBits() { var bits = []; return { bits: bits, put: function (v, n) { for (var i = n - 1; i >= 0; i--) bits.push((v >>> i) & 1); } }; }
  function encodeData(text) {
    var alnum = true; for (var i = 0; i < text.length; i++) if (ALNUM.indexOf(text[i]) < 0) { alnum = false; break; }
    var bytes = alnum ? null : utf8(text);
    var n = alnum ? text.length : bytes.length;
    var version = -1, cap = 0;
    for (var v = 1; v <= 20; v++) {
      cap = (TOTAL[v] - ECM[v] * NBM[v]) * 8;
      var cnt = alnum ? (v < 10 ? 9 : 11) : (v < 10 ? 8 : 16);
      var need = 4 + cnt + (alnum ? Math.floor(n / 2) * 11 + (n % 2) * 6 : n * 8);
      if (need <= cap) { version = v; break; }
    }
    if (version < 0) throw new Error("QR: text too long");
    var b = makeBits();
    if (alnum) {
      b.put(2, 4); b.put(n, version < 10 ? 9 : 11);
      for (var k = 0; k + 1 < n; k += 2) b.put(ALNUM.indexOf(text[k]) * 45 + ALNUM.indexOf(text[k + 1]), 11);
      if (n % 2) b.put(ALNUM.indexOf(text[n - 1]), 6);
    } else {
      b.put(4, 4); b.put(n, version < 10 ? 8 : 16);
      for (var m = 0; m < n; m++) b.put(bytes[m], 8);
    }
    var dataCw = cap / 8;
    b.put(0, Math.min(4, cap - b.bits.length));
    while (b.bits.length % 8) b.bits.push(0);
    var cw = [];
    for (var p = 0; p < b.bits.length; p += 8) { var byte = 0; for (var q = 0; q < 8; q++) byte = (byte << 1) | b.bits[p + q]; cw.push(byte); }
    for (var pad = 0; cw.length < dataCw; pad++) cw.push(pad % 2 ? 0x11 : 0xEC);
    return { version: version, codewords: cw };
  }
  function interleave(data, version) {
    var nb = NBM[version], ec = ECM[version], raw = TOTAL[version];
    var numShort = nb - raw % nb, shortLen = Math.floor(raw / nb);
    var blocks = [], k = 0;
    for (var i = 0; i < nb; i++) {
      var len = shortLen - ec + (i < numShort ? 0 : 1);
      var dat = data.slice(k, k + len); k += len;
      var ecc = rs(dat, ec);
      if (i < numShort) dat.push(-1);
      blocks.push(dat.concat(ecc));
    }
    var out = [];
    for (var c = 0; c < blocks[0].length; c++) for (var j = 0; j < nb; j++) if (blocks[j][c] !== -1) out.push(blocks[j][c]);
    return out;
  }

  function Matrix(size) { this.size = size; this.m = new Uint8Array(size * size); this.f = new Uint8Array(size * size); }
  Matrix.prototype.set = function (x, y, dark, fn) { this.m[y * this.size + x] = dark ? 1 : 0; if (fn) this.f[y * this.size + x] = 1; };
  Matrix.prototype.get = function (x, y) { return this.m[y * this.size + x]; };
  Matrix.prototype.isFn = function (x, y) { return this.f[y * this.size + x]; };

  function drawFunctions(mx, version) {
    var s = mx.size, i, j;
    for (i = 0; i < s; i++) { mx.set(6, i, i % 2 === 0, true); mx.set(i, 6, i % 2 === 0, true); }
    function finder(cx, cy) { for (var dy = -4; dy <= 4; dy++) for (var dx = -4; dx <= 4; dx++) { var x = cx + dx, y = cy + dy; if (x < 0 || y < 0 || x >= s || y >= s) continue; var d = Math.max(Math.abs(dx), Math.abs(dy)); mx.set(x, y, d !== 2 && d !== 4, true); } }
    finder(3, 3); finder(s - 4, 3); finder(3, s - 4);
    var al = ALIGN[version] || [];
    for (i = 0; i < al.length; i++) for (j = 0; j < al.length; j++) {
      if ((i === 0 && j === 0) || (i === 0 && j === al.length - 1) || (i === al.length - 1 && j === 0)) continue;
      for (var dy = -2; dy <= 2; dy++) for (var dx = -2; dx <= 2; dx++) mx.set(al[i] + dx, al[j] + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1, true);
    }
    drawFormat(mx, 0);
    if (version >= 7) {
      var rem = version; for (i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
      var bits = (version << 12) | rem;
      for (i = 0; i < 18; i++) { var bit = (bits >>> i) & 1, a = s - 11 + i % 3, b = Math.floor(i / 3); mx.set(a, b, bit, true); mx.set(b, a, bit, true); }
    }
  }
  function drawFormat(mx, mask) {
    var s = mx.size, data = (0 << 3) | mask, rem = data, i; // EC level M = 00
    for (i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    var bits = ((data << 10) | rem) ^ 0x5412;
    function g(i) { return (bits >>> i) & 1; }
    for (i = 0; i <= 5; i++) mx.set(8, i, g(i), true);
    mx.set(8, 7, g(6), true); mx.set(8, 8, g(7), true); mx.set(7, 8, g(8), true);
    for (i = 9; i < 15; i++) mx.set(14 - i, 8, g(i), true);
    for (i = 0; i < 8; i++) mx.set(s - 1 - i, 8, g(i), true);
    for (i = 8; i < 15; i++) mx.set(8, s - 15 + i, g(i), true);
    mx.set(8, s - 8, true, true);
  }
  function drawData(mx, cw) {
    var s = mx.size, i = 0, total = cw.length * 8;
    for (var right = s - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (var vert = 0; vert < s; vert++) for (var j = 0; j < 2; j++) {
        var x = right - j, upward = ((right + 1) & 2) === 0, y = upward ? s - 1 - vert : vert;
        if (!mx.isFn(x, y) && i < total) { mx.set(x, y, (cw[i >>> 3] >>> (7 - (i & 7))) & 1, false); i++; }
      }
    }
  }
  function maskBit(k, x, y) {
    switch (k) {
      case 0: return (x + y) % 2 === 0; case 1: return y % 2 === 0; case 2: return x % 3 === 0; case 3: return (x + y) % 3 === 0;
      case 4: return (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0; case 5: return (x * y) % 2 + (x * y) % 3 === 0;
      case 6: return ((x * y) % 2 + (x * y) % 3) % 2 === 0; default: return ((x + y) % 2 + (x * y) % 3) % 2 === 0;
    }
  }
  function applyMask(mx, k) { var s = mx.size; for (var y = 0; y < s; y++) for (var x = 0; x < s; x++) if (!mx.isFn(x, y) && maskBit(k, x, y)) mx.m[y * s + x] ^= 1; }
  function penalty(mx) {
    var s = mx.size, score = 0, x, y, dark = 0;
    function runs(getter) { for (var a = 0; a < s; a++) { var run = 1, hist = [0, 0, 0, 0, 0, 0, 0]; for (var b = 0; b < s; b++) { var c = getter(a, b), same = b > 0 && c === getter(a, b - 1); if (same) { run++; if (run === 5) score += 3; else if (run > 5) score += 1; } else run = 1; } } }
    runs(function (a, b) { return mx.get(b, a); }); runs(function (a, b) { return mx.get(a, b); });
    for (y = 0; y < s - 1; y++) for (x = 0; x < s - 1; x++) { var c = mx.get(x, y); if (c === mx.get(x + 1, y) && c === mx.get(x, y + 1) && c === mx.get(x + 1, y + 1)) score += 3; }
    var pat = [1, 0, 1, 1, 1, 0, 1];
    function finderLike(get) { for (var a = 0; a < s; a++) for (var b = 0; b + 10 < s + 4; b++) { var ok1 = true, ok2 = true; for (var i = 0; i < 7; i++) { if (get(a, b + 4 + i) !== pat[i]) ok1 = false; if (get(a, b + i) !== pat[i]) ok2 = false; } if (ok1) { var l = true; for (var q = 0; q < 4; q++) if (get(a, b + q) !== 0) l = false; if (l) score += 40; } if (ok2) { var r = true; for (var q2 = 0; q2 < 4; q2++) if (get(a, b + 7 + q2) !== 0) r = false; if (r) score += 40; } } }
    finderLike(function (a, b) { return b >= s ? 0 : mx.get(b, a); }); finderLike(function (a, b) { return b >= s ? 0 : mx.get(a, b); });
    for (y = 0; y < s; y++) for (x = 0; x < s; x++) dark += mx.get(x, y);
    var k = Math.floor(Math.abs(dark * 100 / (s * s) - 50) / 5); score += k * 10;
    return score;
  }

  function encode(text) {
    var enc = encodeData(text), version = enc.version, size = version * 4 + 17;
    var cw = interleave(enc.codewords, version);
    var best = null, bestScore = Infinity;
    for (var k = 0; k < 8; k++) {
      var mx = new Matrix(size);
      drawFunctions(mx, version); drawFormat(mx, k); drawData(mx, cw); applyMask(mx, k);
      var sc = penalty(mx);
      if (sc < bestScore) { bestScore = sc; best = mx; }
    }
    return { size: size, version: version, get: function (x, y) { return best.get(x, y) === 1; } };
  }
  function draw(canvas, text, opts) {
    opts = opts || {};
    var q = encode(text), margin = opts.margin == null ? 3 : opts.margin, px = opts.px || Math.max(2, Math.floor((opts.width || 260) / (q.size + margin * 2)));
    var side = (q.size + margin * 2) * px;
    canvas.width = side; canvas.height = side;
    canvas.style.width = canvas.style.height = (opts.cssWidth || side) + "px";
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = opts.light || "#ffffff"; ctx.fillRect(0, 0, side, side);
    ctx.fillStyle = opts.dark || "#1a1a1a";
    for (var y = 0; y < q.size; y++) for (var x = 0; x < q.size; x++) if (q.get(x, y)) ctx.fillRect((x + margin) * px, (y + margin) * px, px, px);
    return q;
  }
  return { encode: encode, draw: draw };
})();
