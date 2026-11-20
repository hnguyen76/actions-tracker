/* "?" button: ask Claude about the page. The question and a short text summary of the page data go into a
   claude.ai new-chat link (prefilled, the owner presses send); the same text is also copied to the clipboard in
   case the Claude app opens without it. claude.ai keeps about 14,000 characters of the q parameter. */
(function (root) {
  "use strict";
  const LIMIT = 6000;  // characters of prompt: well inside what claude.ai keeps, and a link iPhone opens quickly
  const DEFAULT_QUESTION = "Tóm tắt nhanh tình hình hôm nay.";
  const INSTRUCTION = "Trả lời ngắn gọn bằng tiếng Việt.";
  const QUICK = ["Hôm nay đặt gì?", "Đang thắng hay thua?", "Cách của bạn đang sao?"];

  // question, then "Dữ liệu … (stamp):" with the non-empty sections, then one instruction line
  function buildPrompt({ question, stamp, live = [], decisions = [], method = [] }) {
    const ask = String(question || "").trim() || DEFAULT_QUESTION;
    const data = [`Dữ liệu Actions Expert Tracker (${stamp}):`];
    for (const [title, rows] of [["Đang đá:", live], ["Kèo:", decisions], ["Cách của bạn:", method]]) {
      if (!rows || !rows.length) continue;
      data.push(title, ...rows.map((r) => "- " + r));
    }
    const fixed = ask.length + INSTRUCTION.length + 4;  // the question, the instruction and the blank lines
    let body = data.join("\n");
    if (fixed + body.length > LIMIT) {
      const keep = [];
      let size = 0;
      for (const row of data) {
        if (fixed + size + row.length + 1 > LIMIT - 2) break;
        keep.push(row);
        size += row.length + 1;
      }
      body = [...keep, "…"].join("\n");
    }
    return [ask, "", body, "", INSTRUCTION].join("\n");
  }

  const link = (prompt) => "https://claude.ai/new?q=" + encodeURIComponent(prompt);

  root.ActionsAsk = { buildPrompt, link, QUICK, LIMIT };
})(typeof window !== "undefined" ? window : globalThis);
