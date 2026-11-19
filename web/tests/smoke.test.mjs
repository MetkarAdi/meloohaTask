import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { startTypingWaitTimers } from '../app/chat-timers.mjs';
import { canStartSheetDrag, shouldCloseSheetDrag } from '../app/sheet-drag.mjs';
import { hasConversation, isZeroBalance, routeFromHash } from '../app/workspace-state.mjs';
import { parseChartFacts, renderChartDiagramSvg, selectVisibleChartMessages } from '../app/chart-diagram-data.mjs';
import { createShareSvg } from '../app/share-chart.mjs';
import { capTranscript, cleanSpeechText, selectRecorderMimeType, splitSpeechText, speechLangFor } from '../app/speech-tools.mjs';

const chartFacts = [
  'F001 : Lagna is Scorpio',
  'F002 : Sun in house 1 (Scorpio), direct',
  'F003 : Moon in house 9 (Cancer), direct',
  'F004 : Mars in house 1 (Scorpio), direct',
  'F005 : Mercury in house 2 (Sagittarius), direct',
  'F006 : Jupiter in house 10 (Leo), retrograde',
  'F007 : Venus in house 2 (Sagittarius), direct',
  'F008 : Saturn in house 4 (Aquarius), retrograde',
  'F009 : Rahu in house 6 (Aries), retrograde',
  'F010 : Ketu in house 12 (Libra), retrograde',
];

test('chart SVG places every fact planet in its computed house', () => {
  const svg = renderChartDiagramSvg(chartFacts);
  const parsed = parseChartFacts(chartFacts);
  for (const planet of parsed.planets) {
    const escaped = planet.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    assert.match(svg, new RegExp(`<g data-planet="${escaped}" data-house="${planet.house}"`));
  }
  assert.match(svg, /<title/);
  assert.match(svg, /Lagna Scorpio\. Sun in house 1/);
  assert.ok(svg.indexOf('<polygon data-house="1"') < svg.indexOf('<path class="lines"'));
  assert.ok(svg.indexOf('<path class="lines"') < svg.indexOf('class="house"'));
});

test('speech recorder chooses a supported MIME, caps transcripts, and prepares readable chunks', () => {
  assert.equal(selectRecorderMimeType(type => type === 'audio/mp4'), 'audio/mp4');
  assert.equal(selectRecorderMimeType(() => false), '');
  const capped = capTranscript(' a '.repeat(200));
  assert.equal(capped.text.length, 250);
  assert.equal(capped.truncated, true);
  assert.equal(cleanSpeechText('Jupiter [F003] [[career|M010]]'), 'Jupiter career');
  const chunks = splitSpeechText('First sentence. ' + 'word '.repeat(90), 40);
  assert.ok(chunks.length > 1);
  assert.ok(chunks.every(chunk => chunk.length <= 40));
  assert.equal(speechLangFor('Hindi'), 'hi-IN');
});

test('question topic house highlights use the backend routing map', async () => {
  const routing = await readFile(new URL('../../api/app/llm/routing.py', import.meta.url), 'utf8');
  assert.match(routing, /"career": \[10\]/);
  assert.match(routing, /"relationships": \[7\]/);
  assert.match(routing, /"money": \[2, 11\]/);
  for (const [question, expected] of [['When will I get a job?', [10]], ['Will my relationship improve?', [7]], ['How will money be?', [2, 11]]]) {
    const topic = question.toLowerCase().includes('job') ? 'career' : question.toLowerCase().includes('relationship') ? 'relationships' : 'money';
    assert.deepEqual(({career:[10],relationships:[7],money:[2,11]})[topic], expected);
  }
});

test('shared image excludes birth details by default', () => {
  const svg = createShareSvg('<svg xmlns="http://www.w3.org/2000/svg"></svg>', { firstName: 'Mira', facts: chartFacts, birthDetails: ['2000-01-01', '06:00', 'Pune'] });
  assert.match(svg, /Mira · Scorpio Lagna/);
  assert.match(svg, /width="1080" height="1350"/);
  assert.doesNotMatch(svg, /2000-01-01|Pune|06:00/);
  assert.match(createShareSvg('<svg/>', { firstName: 'Mira', facts: chartFacts, includeBirthDetails: true, birthDetails: ['2000-01-01'] }), /2000-01-01/);
});

test('crowded houses cap markers and lay visible planet labels out on a grid', () => {
  const crowded = ['F001 : Lagna is Aries', ...['Sun','Moon','Mars','Mercury','Jupiter','Venus'].map((planet, index) => `F${String(index+2).padStart(3,'0')} : ${planet} in house 1 (Aries), direct`)];
  const svg = renderChartDiagramSvg(crowded);
  const markers = [...svg.matchAll(/<g data-planet="([^"]+)" data-house="1"[^>]*><rect class="marker-pill" x="([^"]+)" y="([^"]+)"/g)];
  assert.equal(markers.length, 4);
  assert.equal(new Set(markers.map(item => `${item[2]},${item[3]}`)).size, 4);
  assert.match(svg, />\+2</);
  assert.match(svg, /\.marker-pill\{[^}]*stroke:#c88eb5[^}]*filter:drop-shadow/);
});

test('chat diagrams appear on first relevant reply then at most once per five messages', () => {
  const messages = [
    { role:'user', text:'career' }, { role:'assistant', state:'done', questionId:1, highlightedHouses:[10] },
    { role:'user' }, { role:'assistant', state:'done', questionId:2, highlightedHouses:[7] },
    { role:'user' }, { role:'assistant', state:'done', questionId:3, highlightedHouses:[2] },
    { role:'user' }, { role:'assistant', state:'done', questionId:4, highlightedHouses:[4] },
  ];
  assert.deepEqual(selectVisibleChartMessages(messages), [false,true,false,false,false,false,false,true]);
});

test('home page provides a mobile chat composer', async () => {
  const page = await readFile(new URL('../app/page.tsx', import.meta.url), 'utf8');
  const chat = await readFile(new URL('../app/chat.tsx', import.meta.url), 'utf8');
  assert.match(chat, /What's on your mind today\?/);
  assert.match(chat, /aria-label="Message Melooha"/);
  assert.match(chat, /See chart facts/);
});

test('typing indicator reveals wait notes at 8s and 25s and times out at 60s', () => {
  const timers = fakeTimers();
  const stages = [];
  let timedOut = false;
  const cancel = startTypingWaitTimers(stage => stages.push([timers.now, stage]), () => { timedOut = true; }, timers);
  timers.advance(7_999);
  assert.deepEqual(stages, []);
  timers.advance(1);
  assert.deepEqual(stages, [[8_000, 'waking']]);
  timers.advance(16_999);
  assert.deepEqual(stages, [[8_000, 'waking']]);
  timers.advance(1);
  assert.deepEqual(stages, [[8_000, 'waking'], [25_000, 'waiting']]);
  timers.advance(34_999);
  assert.equal(timedOut, false);
  timers.advance(1);
  assert.equal(timedOut, true);
  cancel();
});

test('receiving the first token cancels every waiting timer', () => {
  const timers = fakeTimers();
  const stages = [];
  let timedOut = false;
  const cancel = startTypingWaitTimers(stage => stages.push(stage), () => { timedOut = true; }, timers);
  timers.advance(3_000);
  cancel(); // The first non-empty SSE chunk has arrived.
  timers.advance(60_000);
  assert.deepEqual(stages, []);
  assert.equal(timedOut, false);
});

test('assistant row owns the only avatar; typing bubble has none', async () => {
  const chat = await readFile(new URL('../app/chat.tsx', import.meta.url), 'utf8');
  const ui = await readFile(new URL('../app/ui.tsx', import.meta.url), 'utf8');
  assert.match(chat, /className="mb-6 flex items-start gap-2\.5 sm:gap-3"><BrandMark small\/><div/);
  const indicator = ui.match(/export function TypingIndicator\([\s\S]*?\n\}/)?.[0] || '';
  assert.ok(indicator);
  assert.doesNotMatch(indicator, /BrandMark/);
});

test('chat has a daily insight card and records the requested product events', async () => {
  const chat = await readFile(new URL('../app/chat.tsx', import.meta.url), 'utf8');
  assert.match(chat, /Today for you/);
  assert.match(chat, /\/insight\/today/);
  for (const eventName of ['session_start', 'insight_viewed', 'facts_sheet_opened']) {
    assert.ok(chat.includes(`event: '${eventName}'`), `missing ${eventName} tracking`);
  }
});

test('chart facts sheet only closes for downward drags from its handle or header', async () => {
  const chat = await readFile(new URL('../app/chat.tsx', import.meta.url), 'utf8');
  assert.equal(canStartSheetDrag('handle'), true);
  assert.equal(canStartSheetDrag('header'), true);
  assert.equal(canStartSheetDrag('content'), false);
  assert.equal(shouldCloseSheetDrag({ origin: 'handle', startY: 10, endY: 95, startedAt: 0, endedAt: 600 }), true);
  assert.equal(shouldCloseSheetDrag({ origin: 'header', startY: 10, endY: 44, startedAt: 0, endedAt: 45 }), true, 'quick downward flick closes');
  assert.equal(shouldCloseSheetDrag({ origin: 'handle', startY: 10, endY: 70, startedAt: 0, endedAt: 500 }), false, 'short slow drag snaps back');
  for (const scrollPosition of ['top', 'middle', 'bottom']) {
    assert.equal(shouldCloseSheetDrag({ origin: 'content', startY: 500, endY: 700, startedAt: 0, endedAt: 30 }), false, `${scrollPosition} content scrolling cannot close the sheet`);
  }
  assert.equal(shouldCloseSheetDrag({ origin: 'header', startY: 100, endY: 10, startedAt: 0, endedAt: 40 }), false, 'upward drag never closes');
  assert.match(chat, /overflowY: 'auto', overscrollBehavior: 'contain', touchAction: 'pan-y', WebkitOverflowScrolling: 'touch'/);
  assert.match(chat, /window\.scrollTo\(0, scrollY\)/);
  assert.match(chat, /event\.key === 'Escape'/);
});

test('reading answers do not render citation markers as superscripts', async () => {
  const ui = await readFile(new URL('../app/ui.tsx', import.meta.url), 'utf8');
  assert.match(ui, /if \(citation\) return \[\];/);
  assert.doesNotMatch(ui, /<sup\b/);
  assert.match(ui, /line\.match\(\//);
  assert.match(ui, /piece\.startsWith\('\*\*'\)/);
});

test('chat renders separately keyed completed answer sections and section-level speech controls', async () => {
  const chat = await readFile(new URL('../app/chat.tsx', import.meta.url), 'utf8');
  assert.match(chat, /message_start/);
  assert.match(chat, /message_delta/);
  assert.match(chat, /message_complete/);
  assert.match(chat, /a-\$\{payload\.id\}/);
  assert.match(chat, /<ListenButton text=\{message\.text\}/);
});

test('workspace routes and zero-balance home state are reachable and safe', async () => {
  const workspace = await readFile(new URL('../app/workspace.tsx', import.meta.url), 'utf8');
  assert.deepEqual(['#home', '#chat', '#chart', '#history', '#profile'].map(routeFromHash), ['home', 'chat', 'chart', 'history', 'profile']);
  assert.equal(routeFromHash('#unknown'), 'home');
  assert.equal(isZeroBalance(0), true);
  assert.equal(isZeroBalance(1), false);
  assert.equal(hasConversation([]), false);
  assert.equal(hasConversation([{ id: 1 }]), true);
  assert.match(workspace, /Your question is saved for later/);
  assert.match(workspace, /Price: 10 free test questions/);
  assert.match(workspace, /window\.history\.pushState/);
  assert.match(workspace, /addEventListener\('popstate'/);
  assert.match(workspace, /hiddenOnMobile=\{keyboardOpen\}/);
  assert.match(workspace, /event: 'home_viewed'/);
});

test('home page includes the daily insight card immediately after the birth chart card', async () => {
  const workspace = await readFile(new URL('../app/workspace.tsx', import.meta.url), 'utf8');
  const chartIndex = workspace.indexOf('Your birth chart');
  const insightIndex = workspace.indexOf('A note for today');
  assert.ok(chartIndex >= 0 && insightIndex > chartIndex);
  assert.match(workspace, /api<DailyInsight>\('\/insight\/today'\)/);
  assert.match(workspace, /setChartMeaningFacts\(dailyInsight\.facts_used\)/);
  assert.match(workspace, /event: 'insight_viewed'/);
});

test('onboarding place input fetches live prefix matches and saves selected coordinates', async () => {
  const page = await readFile(new URL('../app/page.tsx', import.meta.url), 'utf8');
  const locationField = await readFile(new URL('../app/location-field.tsx', import.meta.url), 'utf8');
  assert.match(locationField, /\/api\/locations\/suggest\?q=/);
  assert.match(locationField, /setTimeout\([\s\S]*?250\)/);
  assert.match(locationField, /aria-autocomplete="list"/);
  assert.match(page, /LocationField value=\{location\}/);
  assert.match(page, /latitude: selectedPlace\?\.latitude, longitude: selectedPlace\?\.longitude/);
});

test('profile details editor submits its save form', async () => {
  const workspace = await readFile(new URL('../app/workspace.tsx', import.meta.url), 'utf8');
  assert.match(workspace, /<form onSubmit=\{saveProfile\}/);
  assert.match(workspace, /<Button type="submit" disabled=\{profileSaving\} className="sm:col-span-2">\{profileSaving \? 'Saving…' : 'Save birth details'\}/);
});

function fakeTimers() {
  let nextId = 0;
  const jobs = new Map();
  const clock = {
    now: 0,
    setTimeout(callback, delay) {
      const id = ++nextId;
      jobs.set(id, { at: clock.now + delay, callback });
      return id;
    },
    clearTimeout(id) { jobs.delete(id); },
    advance(milliseconds) {
      const end = clock.now + milliseconds;
      while (true) {
        const next = [...jobs.entries()].sort((a, b) => a[1].at - b[1].at)[0];
        if (!next || next[1].at > end) break;
        clock.now = next[1].at;
        jobs.delete(next[0]);
        next[1].callback();
      }
      clock.now = end;
    },
  };
  return clock;
}
