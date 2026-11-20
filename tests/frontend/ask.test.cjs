const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname, '../../src/actions_tracker/templates/static/ask.js'), 'utf8');

function load() {
  const ctx = {};
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return ctx.ActionsAsk;
}

// a stand-in for the SDK client: streams the given text in pieces, then the final message
function fakeClient(pieces, { stop = 'end_turn', fail = null } = {}) {
  const calls = [];
  return {
    calls,
    beta: { messages: { stream(params) {
      calls.push(params);
      let aborted = false;
      return {
        abort() { aborted = true; },
        async *[Symbol.asyncIterator]() {
          if (fail) throw fail;
          for (const text of pieces) {
            if (aborted) return;
            yield { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text } };
          }
        },
        async finalMessage() { return { stop_reason: stop, content: [{ type: 'text', text: pieces.join('') }] }; },
      };
    } } },
  };
}

test('data text: the stamp, then the non-empty sections as "- " lines', () => {
  const { dataText } = load();
  const t = dataText({ stamp: 'Th 5 20/11 19:30 ET',
    live: ['NFL PIT 11–31 CIN · 4th 10:53 · CIN -4,5 đang thắng 15,5'],
    decisions: ['Hôm nay 20:15 NFL BUF@HOU · spread HOU +5,5 · Cách của bạn'],
    method: [] });
  const lines = t.split('\n');
  assert.equal(lines[0], 'Dữ liệu Actions Expert Tracker (Th 5 20/11 19:30 ET):');
  assert.ok(t.indexOf('Đang đá:') < t.indexOf('Kèo:'));
  assert.ok(t.includes('- NFL PIT 11–31 CIN · 4th 10:53 · CIN -4,5 đang thắng 15,5'));
  assert.ok(!t.includes('Cách của bạn:'));
});

test('data text: long data is cut to the limit and ends with "…"', () => {
  const { dataText, LIMIT } = load();
  const many = Array.from({ length: 400 }, (_, i) => `Hôm nay 20:15 NFL TEAM${i}@HOME · spread HOME -3,5 · Cách của bạn · 8 expert`);
  const t = dataText({ stamp: 'x', live: [], decisions: many, method: [] });
  assert.ok(t.length <= LIMIT, `${t.length} > ${LIMIT}`);
  assert.ok(t.endsWith('\n…'));
});

test('request: Opus 5.5, low effort, refusal fallback on, rules as system, fresh data only in the new question', () => {
  const { params, MODEL } = load();
  const history = [{ role: 'user', content: 'Hôm nay đặt gì?' }, { role: 'assistant', content: '- HOU +5,5' }];
  const p = params({ question: 'Còn NCAAF?', data: 'Dữ liệu Actions Expert Tracker (x):\nKèo:\n- a', history });
  assert.equal(MODEL, 'claude-opus-5-5');
  assert.equal(p.model, 'claude-opus-5-5');
  assert.deepEqual(JSON.parse(JSON.stringify(p.output_config)), { effort: 'low' });
  assert.deepEqual(JSON.parse(JSON.stringify(p.betas)), ['server-side-fallback-2026-07-01']);
  assert.equal(p.fallbacks, 'default');
  assert.ok(p.max_tokens >= 16000);
  assert.match(p.system, /banh/);
  assert.equal(p.messages.length, 3);
  assert.equal(p.messages[0].content, 'Hôm nay đặt gì?');
  const last = p.messages[2];
  assert.equal(last.role, 'user');
  assert.ok(last.content.startsWith('Dữ liệu Actions Expert Tracker (x):'));
  assert.ok(last.content.endsWith('Câu hỏi: Còn NCAAF?'));
});

test('request: only the last 3 questions and answers go along', () => {
  const { params } = load();
  const history = Array.from({ length: 10 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', content: String(i) }));
  const p = params({ question: 'q', data: 'd', history });
  assert.deepEqual([...p.messages.slice(0, -1).map((m) => m.content)], ['4', '5', '6', '7', '8', '9']);
});

test('ask: streams the answer text and returns it with the turn added to the history', async () => {
  const { ask } = load();
  const client = fakeClient(['- **HOU +5,5**', ' đang thắng 3']);
  const seen = [];
  const run = ask({ client, question: 'Đang thắng hay thua?', data: 'd', history: [], onText: (t) => seen.push(t) });
  const res = await run.done;
  assert.deepEqual(seen, ['- **HOU +5,5**', '- **HOU +5,5** đang thắng 3']);
  assert.equal(res.text, '- **HOU +5,5** đang thắng 3');
  assert.deepEqual(JSON.parse(JSON.stringify(res.history)),
    [{ role: 'user', content: 'Đang thắng hay thua?' }, { role: 'assistant', content: '- **HOU +5,5** đang thắng 3' }]);
  assert.equal(client.calls.length, 1);
});

test('ask: a refusal says so and is not kept in the history', async () => {
  const { ask } = load();
  const res = await ask({ client: fakeClient([''], { stop: 'refusal' }), question: 'q', data: 'd', history: [] }).done;
  assert.equal(res.text, 'Claude không trả lời câu này.');
  assert.equal(res.history.length, 0);
});

test('answer blocks: bullets, headings, bold, and "đang thắng"/"đang thua" toned', () => {
  const { blocks } = load();
  const b = JSON.parse(JSON.stringify(blocks('## Hôm nay\n- **HOU +5,5** đang thắng 3\n\nNCAAF đang thua 7\n1. x')));
  assert.deepEqual(b.map((x) => x.tag), ['h', 'li', 'p', 'li']);
  assert.deepEqual(b[1].parts, [{ text: 'HOU +5,5', bold: true }, { text: ' ' }, { text: 'đang thắng', tone: 'up' }, { text: ' 3' }]);
  assert.deepEqual(b[2].parts, [{ text: 'NCAAF ' }, { text: 'đang thua', tone: 'down' }, { text: ' 7' }]);
});

test('errors: short Vietnamese text by kind; a bad key is flagged so the page asks for a new one', () => {
  const { errorText } = load();
  class APIError extends Error { constructor(status) { super('x'); this.status = status; } }
  class AuthenticationError extends APIError {}
  class PermissionDeniedError extends APIError {}
  class RateLimitError extends APIError {}
  class APIConnectionError extends Error {}
  class APIUserAbortError extends Error {}
  const A = { APIError, AuthenticationError, PermissionDeniedError, RateLimitError, APIConnectionError, APIUserAbortError };
  assert.deepEqual({ ...errorText(new AuthenticationError(401), A) }, { text: 'API key sai hoặc đã bị xoá.', badKey: true });
  assert.equal(errorText(new RateLimitError(429), A).text, 'Hỏi nhiều quá, đợi chút rồi hỏi lại.');
  assert.equal(errorText(new APIConnectionError(), A).text, 'Mất mạng, hỏi lại nhé.');
  assert.equal(errorText(new APIUserAbortError(), A).text, 'Đã dừng.');
  assert.match(errorText(new APIError(400), A).text, /Lỗi 400/);
  assert.equal(errorText(new Error('boom'), A).text, 'Lỗi, hỏi lại nhé.');
});
