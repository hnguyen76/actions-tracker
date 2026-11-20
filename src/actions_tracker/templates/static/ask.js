/* "?" button: opens the "Hỏi Actions" page on claude.ai, where Claude answers inside the page with the owner's own
   Claude account. That page cannot read this site, so the page data travels in the link: a short text summary,
   deflate-compressed and base32-encoded into the link's #name (claude.ai passes on only letters, digits and hyphens
   there). The same text is copied to the clipboard too: pasting it into the Hỏi page works if a link loses its #name.
   The codec block is copied verbatim into artifacts/hoi-actions.html (a test keeps the two the same). */
(function (root) {
  "use strict";
  const PAGE = "https://claude.ai/artifact/3pMbgv9aTTrbptD5dDhwTE";
  const LIMIT = 6000;  // characters of data text: about 2–3 KB once compressed, a link phones open without trouble

  // "Dữ liệu … (stamp):" then the non-empty sections, cut to LIMIT with a final "…"
  function dataText({ stamp, live = [], decisions = [], method = [] }) {
    const lines = [`Dữ liệu Actions Expert Tracker (${stamp}):`];
    for (const [title, rows] of [["Đang đá:", live], ["Kèo:", decisions], ["Cách của bạn:", method]]) {
      if (!rows || !rows.length) continue;
      lines.push(title, ...rows.map((r) => "- " + r));
    }
    const text = lines.join("\n");
    if (text.length <= LIMIT) return text;
    const keep = [];
    let size = 2;  // the final "\n…"
    for (const line of lines) {
      if (size + line.length + 1 > LIMIT) break;
      keep.push(line);
      size += line.length + 1;
    }
    return [...keep, "…"].join("\n");
  }

  /* codec:start (same block in artifacts/hoi-actions.html) */
  const B32 = "abcdefghijklmnopqrstuvwxyz234567";
  function toB32(bytes) {
    let out = "", bits = 0, value = 0;
    for (const byte of bytes) {
      value = (value << 8) | byte;
      bits += 8;
      while (bits >= 5) { out += B32[(value >>> (bits - 5)) & 31]; bits -= 5; }
      value &= (1 << bits) - 1;
    }
    return bits ? out + B32[(value << (5 - bits)) & 31] : out;
  }
  function fromB32(text) {
    const out = [];
    let bits = 0, value = 0;
    for (const ch of text) {
      const i = B32.indexOf(ch);
      if (i < 0) throw new Error("not base32");
      value = (value << 5) | i;
      bits += 5;
      if (bits >= 8) { out.push((value >>> (bits - 8)) & 255); bits -= 8; }
      value &= (1 << bits) - 1;
    }
    return new Uint8Array(out);
  }
  async function squeeze(bytes, stream) {
    return new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(stream)).arrayBuffer());
  }
  // "d1" + base32 of deflate-raw(UTF-8), or "d0" + base32 of plain UTF-8 where the browser cannot compress
  async function encode(text) {
    const raw = new TextEncoder().encode(text);
    if (typeof CompressionStream === "undefined") return "d0" + toB32(raw);
    return "d1" + toB32(await squeeze(raw, new CompressionStream("deflate-raw")));
  }
  async function decode(code) {
    try {
      const m = /^d([01])([a-z2-7]+)$/.exec(String(code || "").replace(/^#/, ""));
      if (!m) return null;
      const bytes = fromB32(m[2]);
      return new TextDecoder("utf-8", { fatal: true })
        .decode(m[1] === "1" ? await squeeze(bytes, new DecompressionStream("deflate-raw")) : bytes);
    } catch (e) {
      return null;
    }
  }
  /* codec:end */

  const link = (code) => PAGE + (code ? "#" + code : "");

  root.ActionsAsk = { dataText, encode, decode, link, PAGE, LIMIT };
})(typeof window !== "undefined" ? window : globalThis);
