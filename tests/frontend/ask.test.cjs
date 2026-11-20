const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname, '../../src/actions_tracker/templates/static/ask.js'), 'utf8');
const page = fs.readFileSync(path.resolve(__dirname, '../../artifacts/hoi-actions.html'), 'utf8');

function load() {
  const ctx = { Blob, Response, TextEncoder, TextDecoder, CompressionStream, DecompressionStream, Uint8Array };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return ctx.ActionsAsk;
}

const codec = (text) => {
  const m = /\/\* codec:start[^*]*\*\/[\s\S]*?\/\* codec:end \*\//.exec(text);
  return m && m[0].replace(/^[ \t]+/gm, '');
};

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
  assert.ok(t.startsWith('Dữ liệu Actions Expert Tracker (x):'));
});

test('link code: letters and digits only, much shorter than the text, and decodes back exactly', async () => {
  const { dataText, encode, decode } = load();
  const rows = Array.from({ length: 30 }, (_, i) => `Hôm nay 20:15 NFL TEAM${i}@HOME · spread HOME -3,5 · Cách của bạn · đang thắng 7,5`);
  const text = dataText({ stamp: 'Th 5 20/11 19:30 ET', live: ['NFL PIT 11–31 CIN'], decisions: rows, method: ['NFL cả mùa 41-35-2'] });
  const code = await encode(text);
  assert.match(code, /^d1[a-z2-7]+$/);
  assert.ok(code.length < text.length, `${code.length} vs ${text.length}`);
  assert.equal(await decode(code), text);
  assert.equal(await decode('#' + code), text);
});

test('link code: works without compression too, and bad codes give null', async () => {
  const { encode, decode } = load();
  const ctx = { Blob, Response, TextEncoder, TextDecoder, Uint8Array };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  const code = await ctx.ActionsAsk.encode('Kèo: CIN -4,5 ✓');
  assert.match(code, /^d0[a-z2-7]+$/);
  assert.equal(await decode(code), 'Kèo: CIN -4,5 ✓');
  assert.equal(await decode(''), null);
  assert.equal(await decode('summary'), null);
  assert.equal(await decode('d1zzzz'), null);
  assert.ok(encode);
});

test('link: the Hỏi page with the code as its #name', () => {
  const { link, PAGE } = load();
  assert.match(PAGE, /^https:\/\/claude\.ai\/artifact\/[A-Za-z0-9]+$/);
  assert.equal(link('d1abc'), PAGE + '#d1abc');
  assert.equal(link(''), PAGE);
});

test('the Hỏi page decodes with the very same codec block as the dashboard', () => {
  assert.ok(codec(source), 'ask.js has a codec block');
  assert.equal(codec(page), codec(source));
});
