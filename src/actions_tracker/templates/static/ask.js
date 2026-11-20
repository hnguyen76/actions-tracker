/* "?" button: ask Claude about the page, answered right here. The owner's own Anthropic API key (kept only in this
   browser's localStorage, never in the repo or the site) calls the Claude API directly through the official SDK
   (anthropic-sdk.js, loaded on first open). Each question goes along with a fresh short text summary of the page. */
(function (root) {
  "use strict";
  const LIMIT = 6000;   // characters of data text sent with each question
  const KEEP = 6;       // earlier messages sent along: the last 3 questions and answers
  const MODEL = "claude-opus-5-5";
  const REFUSED = "Claude không trả lời câu này.";
  const RULES = [
    "Bạn trả lời câu hỏi của chủ dashboard Actions Expert Tracker: picks của expert Action Network (NFL, NCAAF, NBA), " +
      "\"Cách của bạn\" (cách đặt riêng của chủ dashboard) và tỉ số các trận đang đá.",
    "Chỉ dùng dữ liệu gửi kèm câu hỏi mới nhất (mới nhất là đúng nhất). Không có trong dữ liệu thì nói \"Không có trong dữ liệu\".",
    "Tiếng Việt có dấu, thật ngắn: số và kèo trước, tối đa 6 dòng, gạch đầu dòng \"- \", không mở bài, không giải thích dài.",
    "Giữ thuật ngữ cá cược tiếng Anh: spread, total, moneyline, favorite, underdog, fade, over, under. Viết \"banh\", không viết \"bóng\".",
    "Kèo ghi \"Theo dõi — chưa đặt tiền\" là quy tắc đang thử nghiệm: không khuyên đặt tiền thật cho kèo đó.",
    "Giờ là giờ ET. Viết số thập phân bằng dấu phẩy như dữ liệu.",
  ].join("\n");

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

  // the Messages request: the rules as the system prompt, the last few turns, then the fresh data with the question.
  // Low effort keeps chat answers quick; "default" fallbacks let the API retry a declined answer on another model.
  function params({ question, data, history = [] }) {
    return {
      model: MODEL,
      max_tokens: 64000,
      output_config: { effort: "low" },
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      system: RULES,
      messages: [...history.slice(-KEEP), { role: "user", content: `${data}\n\nCâu hỏi: ${String(question).trim()}` }],
    };
  }

  // stream one answer: onText gets the whole answer so far; done resolves { text, history } (history unchanged on a refusal)
  function ask({ client, question, data, history = [], onText }) {
    const stream = client.beta.messages.stream(params({ question, data, history }));
    const done = (async () => {
      let text = "";
      for await (const event of stream) {
        if (event.type === "content_block_delta" && event.delta && event.delta.type === "text_delta") {
          text += event.delta.text;
          if (onText) onText(text);
        }
      }
      const final = await stream.finalMessage();
      if (final.stop_reason === "refusal") return { text: REFUSED, history: history.slice() };
      if (!text) text = (final.content || []).filter((b) => b.type === "text").map((b) => b.text).join("");
      return { text, history: [...history, { role: "user", content: String(question).trim() }, { role: "assistant", content: text }] };
    })();
    return { abort: () => stream.abort(), done };
  }

  // answer text -> lines to draw: tag h (heading), li (bullet) or p, each with parts {text, bold?, tone?}
  function blocks(text) {
    const out = [];
    for (const raw of String(text).split("\n")) {
      let line = raw.trim();
      if (!line) continue;
      let tag = "p";
      const head = /^#{1,6}\s+/.exec(line), bullet = /^([-•*]|\d+\.)\s+/.exec(line);
      if (head) { tag = "h"; line = line.slice(head[0].length); } else if (bullet) { tag = "li"; line = line.slice(bullet[0].length); }
      const parts = [];
      line.split(/\*\*(.+?)\*\*/g).forEach((piece, i) => {
        if (!piece) return;
        if (i % 2) { parts.push({ text: piece, bold: true }); return; }
        piece.split(/(đang thắng|đang thua)/g).forEach((bit) => {
          if (!bit) return;
          if (bit === "đang thắng") parts.push({ text: bit, tone: "up" });
          else if (bit === "đang thua") parts.push({ text: bit, tone: "down" });
          else parts.push({ text: bit });
        });
      });
      out.push({ tag, parts });
    }
    return out;
  }

  // SDK error -> short text; badKey tells the page to ask for the key again
  function errorText(err, A) {
    const is = (name) => A && typeof A[name] === "function" && err instanceof A[name];
    if (is("APIUserAbortError")) return { text: "Đã dừng." };
    if (is("AuthenticationError")) return { text: "API key sai hoặc đã bị xoá.", badKey: true };
    if (is("PermissionDeniedError")) return { text: "API key không được phép dùng.", badKey: true };
    if (is("RateLimitError")) return { text: "Hỏi nhiều quá, đợi chút rồi hỏi lại." };
    if (is("APIConnectionError")) return { text: "Mất mạng, hỏi lại nhé." };
    if (is("APIError")) {
      if (err.status === 400 && /credit/i.test(err.message || "")) return { text: "Hết tiền API: nạp thêm ở Claude Console." };
      return { text: `Lỗi ${err.status || ""}, hỏi lại nhé.`.replace(" ,", ",") };
    }
    return { text: "Lỗi, hỏi lại nhé." };
  }

  root.ActionsAsk = { dataText, params, ask, blocks, errorText, MODEL, LIMIT };
})(typeof window !== "undefined" ? window : globalThis);
