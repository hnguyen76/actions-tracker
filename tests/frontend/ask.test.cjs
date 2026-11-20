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

test('prompt: the question first, then the page data by section, then one short instruction', () => {
  const { buildPrompt } = load();
  const p = buildPrompt({ question: 'Hôm nay đặt gì?', stamp: 'Th 5 20/11 19:30 ET',
    live: ['NFL PIT 11–31 CIN · 4th 10:53 · CIN -4,5 đang thắng 15,5'],
    decisions: ['Hôm nay 20:15 NFL BUF@HOU · spread HOU +5,5 · Cách của bạn'],
    method: ['NFL: mùa 41-35 · 53,9% · live 6-4 · ROI +12,0%'] });
  const lines = p.split('\n');
  assert.equal(lines[0], 'Hôm nay đặt gì?');
  assert.ok(p.includes('Dữ liệu Actions Expert Tracker (Th 5 20/11 19:30 ET):'));
  assert.ok(p.indexOf('Đang đá:') < p.indexOf('Kèo:') && p.indexOf('Kèo:') < p.indexOf('Cách của bạn:'));
  assert.ok(p.includes('- NFL PIT 11–31 CIN · 4th 10:53 · CIN -4,5 đang thắng 15,5'));
  assert.equal(lines[lines.length - 1], 'Trả lời ngắn gọn bằng tiếng Việt.');
});

test('prompt: empty sections are left out; no question asks for a quick summary', () => {
  const { buildPrompt } = load();
  const p = buildPrompt({ question: '  ', stamp: 'x', live: [], decisions: ['a'], method: [] });
  assert.equal(p.split('\n')[0], 'Tóm tắt nhanh tình hình hôm nay.');
  assert.ok(!p.includes('Đang đá:') && !p.includes('Cách của bạn:'));
  assert.ok(p.includes('Kèo:\n- a'));
});

test('prompt: long data is cut to fit, keeping the question and the instruction', () => {
  const { buildPrompt, LIMIT } = load();
  const many = Array.from({ length: 400 }, (_, i) => `Hôm nay 20:15 NFL TEAM${i}@HOME · spread HOME -3,5 · Cách của bạn · 8 expert`);
  const p = buildPrompt({ question: 'Q?', stamp: 's', live: [], decisions: many, method: [] });
  assert.ok(p.length <= LIMIT);
  assert.ok(LIMIT <= 12000);          // claude.ai keeps about 14,000 characters of q
  assert.equal(p.split('\n')[0], 'Q?');
  assert.ok(p.endsWith('Trả lời ngắn gọn bằng tiếng Việt.'));
  assert.ok(p.includes('\n…\n'));
});

test('link: a claude.ai new-chat link with the prompt encoded (Vietnamese, &, new lines)', () => {
  const { link } = load();
  const prompt = 'Đội nào & tại sao?\nDòng 2';
  const url = link(prompt);
  assert.ok(url.startsWith('https://claude.ai/new?q='));
  assert.equal(decodeURIComponent(url.slice('https://claude.ai/new?q='.length)), prompt);
  assert.ok(!/[\s&]/.test(url.slice('https://claude.ai/new?q='.length)));
});
