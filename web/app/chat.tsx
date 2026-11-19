'use client';

import { FormEvent, KeyboardEvent, PointerEvent as ReactPointerEvent, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { BrandMark, Button, Card, ListenButton, RatingButtons, ReadingAnswer, TypingIndicator } from './ui';
import { capTranscript, selectRecorderMimeType } from './speech-tools.mjs';
import { startTypingWaitTimers } from './chat-timers.mjs';
import { canStartSheetDrag, shouldCloseSheetDrag } from './sheet-drag.mjs';
import { ChartDiagram, ShareChartButton } from './chart-diagram';
import { selectVisibleChartMessages } from './chart-diagram-data.mjs';

type Profile = { display_name: string | null; label: string; birth_date?: string; birth_time?: string; birth_time_unknown?: boolean; location?: string };
type HistoryEntry = { id: number; question_text: string; answer_text: string | null; status: string; rating: number | null; facts_used: string[]; highlighted_houses?: number[]; created_at: string };
type MessageState = 'greeting' | 'typing' | 'streaming' | 'done' | 'out_of_balance' | 'error' | 'pending';
type ChatMessage = { key: string; role: 'user' | 'assistant'; text: string; questionId?: number; facts?: string[]; highlightedHouses?: number[]; rating?: number | null; state?: MessageState; retryText?: string; waitingStage?: 'waking' | 'waiting' };
type DailyInsight = { id: number; run_date: string; answer_text: string; facts_used: string[]; streak_days: number; llm_provider: string; llm_model: string };

const PAGE_SIZE = 20;
const suggestions = [
  'When might my career gain momentum?',
  'What relationship themes stand out?',
  'What strengths can I lean on?',
];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      credentials: 'same-origin',
      headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
    });
  } catch {
    throw new Error('Couldn’t reach the stars. Check your connection and try again.');
  }
  if (!response.ok) {
    if (response.status === 401) throw new Error('Your session has ended. Please sign in again.');
    if (response.status === 403) throw new Error('Question credits are not available right now.');
    throw new Error('Couldn’t load this just now. Please try again.');
  }
  return response.status === 204 ? undefined as T : response.json();
}

function fromHistory(entries: HistoryEntry[]): ChatMessage[] {
  return [...entries].reverse().flatMap((entry) => {
    const user: ChatMessage = { key: `q-${entry.id}`, role: 'user', text: entry.question_text, questionId: entry.id };
    let reply: ChatMessage;
    if (entry.status === 'draft') {
      reply = { key: `a-${entry.id}`, role: 'assistant', text: 'I saved your question. Add questions and I’ll answer it automatically.', questionId: entry.id, facts: [], highlightedHouses: entry.highlighted_houses || [], state: 'out_of_balance', retryText: entry.question_text };
    } else if (entry.status === 'failed' || entry.status === 'retry_failed') {
      reply = { key: `a-${entry.id}`, role: 'assistant', text: 'Couldn’t reach the stars. Tap to retry.', questionId: entry.id, facts: entry.facts_used || [], rating: entry.rating, state: 'error', retryText: entry.question_text };
    } else if (entry.status === 'pending') {
      reply = { key: `a-${entry.id}`, role: 'assistant', text: '', questionId: entry.id, facts: entry.facts_used || [], state: 'pending', retryText: entry.question_text };
    } else {
      reply = { key: `a-${entry.id}`, role: 'assistant', text: entry.answer_text || '', questionId: entry.id, facts: entry.facts_used || [], highlightedHouses: entry.highlighted_houses || [], rating: entry.rating, state: 'done' };
    }
    return [user, reply];
  });
}

function groupFacts(facts: string[]) {
  const groups: Record<string, string[]> = { 'Planets & chart': [], Houses: [], 'Dasha periods': [] };
  for (const raw of facts) {
    const match = raw.match(/^\s*([FM]\d{3})\s*:\s*(.*)$/i);
    const id = match?.[1]?.toUpperCase();
    const text = match?.[2]?.trim() || raw;
    let label = text;
    let group = 'Planets & chart';
    if (/current (?:mahadasha|antardasha|pratyantardasha)/i.test(text)) {
      group = 'Dasha periods';
      label = text.replace(/^Current /i, '').replace(/\bfrom\b/i, '·').replace(/\bto\b/i, '–');
    } else if (/\b(?:mahadasha|antardasha|pratyantardasha|dasha dates|timing window|timing layer)\b/i.test(text)) {
      group = 'Dasha periods';
    } else if (/^(?:transiting\s+)?(?:Sun|Moon|Mars|Mercury|Jupiter|Venus|Saturn|Rahu|Ketu)\s+in\s+house\b/i.test(text)) {
      group = 'Planets & chart';
    } else if (/\bhouse\s+\d+\b|\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth)\s+house\b/i.test(text)) {
      group = 'Houses';
    }
    // The identifier is intentionally not exposed in the sheet.
    void id;
    groups[group].push(label);
  }
  return Object.entries(groups).filter(([, items]) => items.length > 0);
}

export function FactsSheet({ facts, onClose, language = 'English' }: { facts: string[]; onClose: () => void; language?: string }) {
  const dragRef = useRef<{ pointerId: number; origin: 'handle' | 'header'; startY: number; startedAt: number } | null>(null);
  const groups = groupFacts(facts);
  useLayoutEffect(() => {
    const body = document.body;
    const html = document.documentElement;
    const scrollY = window.scrollY;
    const previous = {
      bodyPosition: body.style.position,
      bodyTop: body.style.top,
      bodyLeft: body.style.left,
      bodyRight: body.style.right,
      bodyWidth: body.style.width,
      bodyOverflow: body.style.overflow,
      htmlOverflow: html.style.overflow,
    };
    body.style.position = 'fixed';
    body.style.top = `-${scrollY}px`;
    body.style.left = '0';
    body.style.right = '0';
    body.style.width = '100%';
    body.style.overflow = 'hidden';
    html.style.overflow = 'hidden';
    return () => {
      body.style.position = previous.bodyPosition;
      body.style.top = previous.bodyTop;
      body.style.left = previous.bodyLeft;
      body.style.right = previous.bodyRight;
      body.style.width = previous.bodyWidth;
      body.style.overflow = previous.bodyOverflow;
      html.style.overflow = previous.htmlOverflow;
      window.scrollTo(0, scrollY);
    };
  }, []);
  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);
  function dragStart(event: ReactPointerEvent<HTMLDivElement>) {
    if ((event.target as Element).closest('button')) return;
    const origin = (event.target as Element).closest('[data-sheet-drag-zone="handle"]') ? 'handle' : 'header';
    if (!canStartSheetDrag(origin)) return;
    dragRef.current = { pointerId: event.pointerId, origin, startY: event.clientY, startedAt: performance.now() };
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* Pointer capture is optional on older browsers. */ }
  }
  function dragEnd(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (shouldCloseSheetDrag({
      origin: drag.origin,
      startY: drag.startY,
      endY: event.clientY,
      startedAt: drag.startedAt,
      endedAt: performance.now(),
    })) onClose();
  }
  function dragCancel(event: ReactPointerEvent<HTMLDivElement>) {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null;
  }
  return <div className="fixed inset-0 z-50 bg-black/65 backdrop-blur-sm" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-labelledby="facts-sheet-title" className="facts-sheet absolute inset-0 flex flex-col overflow-hidden border-line bg-[#100d13] sm:inset-y-0 sm:left-auto sm:right-0 sm:w-[min(100%,460px)] sm:border-l sm:shadow-2xl">
      <div onPointerDown={dragStart} onPointerUp={dragEnd} onPointerCancel={dragCancel} onLostPointerCapture={dragCancel} className="facts-sheet-header shrink-0 border-b border-line px-5 pb-4 pt-[max(1rem,env(safe-area-inset-top))] sm:px-7 sm:pt-7" style={{ touchAction: 'none', userSelect: 'none', WebkitUserSelect: 'none' }}>
        <div data-sheet-drag-zone="handle" className="-mx-5 mb-2 flex h-7 items-center justify-center px-5 sm:hidden"><div className="h-1 w-10 rounded-full bg-[#594557]"/></div>
        <div className="flex items-start justify-between gap-4"><div><p className="text-[10px] font-semibold uppercase tracking-[.2em] text-star">Chart notes</p><h2 id="facts-sheet-title" className="mt-1 font-display text-2xl">Where this came from</h2><ListenButton text={groups.map(([title, items]) => `${title}. ${items.join('. ')}`).join('. ')} language={language} className="mt-2"/></div><button onClick={onClose} aria-label="Close chart facts" className="grid size-10 shrink-0 place-items-center rounded-full border border-line text-lg text-muted hover:bg-panel-hover hover:text-ink">×</button></div>
        <p className="mt-2 text-xs text-muted sm:hidden">Swipe down to close</p><p className="mt-2 hidden text-xs text-muted sm:block">Computed chart details and plain-English meanings used for this reply.</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5 sm:px-7" style={{ overflowY: 'auto', overscrollBehavior: 'contain', touchAction: 'pan-y', WebkitOverflowScrolling: 'touch' }}>{groups.length ? <div className="space-y-6">{groups.map(([title, items]) => <section key={title}><h3 className="mb-2 text-xs font-semibold uppercase tracking-[.14em] text-[#ed8fc0]">{title}</h3><ul className="space-y-2">{items.map((item, index) => <li key={`${title}-${index}`} className="rounded-xl border border-line-soft bg-[#17121b] px-4 py-3 text-sm leading-6 text-ink-soft">{item}</li>)}</ul></section>)}</div> : <div className="grid min-h-48 place-items-center text-center text-sm text-muted">Chart notes will appear with a completed reading.</div>}</div>
      <div className="shrink-0 border-t border-line px-5 py-4 text-center text-xs text-muted sm:hidden" style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}>Swipe down to close</div>
    </section>
  </div>;
}

function HistorySheet({ entries, hasOlder, loading, onOlder, onSelect, onClose }: { entries: HistoryEntry[]; hasOlder: boolean; loading: boolean; onOlder: () => void; onSelect: (id: number) => void; onClose: () => void }) {
  return <div className="fixed inset-0 z-40 bg-black/65 backdrop-blur-sm" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}><section role="dialog" aria-modal="true" aria-labelledby="history-title" className="absolute inset-0 flex flex-col overflow-hidden border-line bg-[#100d13] sm:inset-y-0 sm:left-auto sm:right-0 sm:w-[min(100%,420px)] sm:border-l sm:shadow-2xl"><div className="flex items-center justify-between border-b border-line px-5 py-4 sm:px-6"><div><p className="text-[10px] uppercase tracking-[.2em] text-star">Your conversations</p><h2 id="history-title" className="mt-1 font-display text-2xl">History</h2></div><button onClick={onClose} aria-label="Close history" className="grid size-10 place-items-center rounded-full border border-line text-lg text-muted">×</button></div><div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">{entries.length ? <div className="space-y-2">{entries.slice().sort((a,b)=>b.id-a.id).map(item=><button key={item.id} onClick={()=>onSelect(item.id)} className="w-full rounded-2xl border border-line bg-panel p-4 text-left transition hover:border-magenta/40"><div className="flex items-center justify-between gap-3"><span className="text-[11px] text-muted">{new Date(item.created_at).toLocaleDateString()}</span><span className={`rounded-full px-2.5 py-1 text-[10px] ${item.status==='answered'?'bg-success/10 text-success':item.status==='draft'?'bg-star/10 text-star':'bg-panel-raised text-muted'}`}>{item.status==='answered'?'Answered':item.status==='draft'?'Saved':'Retry available'}</span></div><p className="mt-2 line-clamp-2 font-display text-lg leading-6 text-ink">{item.question_text}</p><p className="mt-2 line-clamp-2 text-xs leading-5 text-muted">{item.answer_text || (item.status === 'draft' ? 'Waiting for questions to be added.' : 'Open this reply in the chat thread.')}</p></button>)}</div> : <div className="grid min-h-64 place-items-center px-6 text-center"><div><BrandMark/><h3 className="mt-4 font-display text-xl">A fresh beginning</h3><p className="mt-2 text-sm text-muted">Your conversations will be saved here.</p></div></div>}{hasOlder && <button disabled={loading} onClick={onOlder} className="mt-4 w-full rounded-xl border border-line py-3 text-xs text-muted hover:text-ink disabled:opacity-50">{loading?'Loading…':'Load older conversations'}</button>}</div></section></div>;
}

export function ChatApp({ profile, chartFacts = [], language = 'English', balance: initialBalance, onBalance, onLogout, initialQuestion, focusQuestionId, openAddQuestions, onKeyboardChange, onNavigate }: { profile: Profile; chartFacts?: string[]; language?: string; balance: number; onBalance: (balance: number) => void; onLogout: () => void; initialQuestion?: string; focusQuestionId?: number | null; openAddQuestions?: boolean; onKeyboardChange?: (open: boolean) => void; onNavigate?: (route: 'home' | 'chat' | 'chart' | 'history' | 'profile') => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [hasOlder, setHasOlder] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [balance, setBalance] = useState(initialBalance);
  const [draft, setDraft] = useState('');
  const [micSupported, setMicSupported] = useState(false);
  const [voiceState, setVoiceState] = useState<'idle'|'requesting'|'recording'|'transcribing'|'too_short'|'denied'|'no_mic'|'empty'|'error'>('idle');
  const [voiceMessage, setVoiceMessage] = useState('');
  const [voiceTrimmed, setVoiceTrimmed] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(typeof navigator !== 'undefined' ? !navigator.onLine : false);
  const [isKeyboardOpen, setIsKeyboardOpen] = useState(false);
  const [showNewMessage, setShowNewMessage] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [factsFor, setFactsFor] = useState<ChatMessage | null>(null);
  const [chartFor, setChartFor] = useState<ChatMessage | null>(null);
  const [creditOpen, setCreditOpen] = useState(false);
  const [creditBusy, setCreditBusy] = useState(false);
  const [creditError, setCreditError] = useState('');
  const [creditMessage, setCreditMessage] = useState('');
  const [composerError, setComposerError] = useState('');
  const [dailyInsight, setDailyInsight] = useState<DailyInsight | null>(null);
  const [dailyInsightLoading, setDailyInsightLoading] = useState(true);
  const [dailyInsightError, setDailyInsightError] = useState('');
  const threadRef = useRef<HTMLDivElement>(null);
  const dailyInsightRef = useRef<HTMLElement>(null);
  const insightViewedRef = useRef<number | null>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recordingChunksRef = useRef<Blob[]>([]);
  const recordStartedRef = useRef(0);
  const cancelledRecordingRef = useRef(false);
  const retryAudioRef = useRef<{ blob: Blob; duration: number } | null>(null);
  const atBottomRef = useRef(true);
  const restoreScrollRef = useRef<number | null>(null);
  const loadingOlderRef = useRef(false);
  const messagesRef = useRef(messages);
  const focusedHistoryIdRef = useRef<number | null>(null);
  messagesRef.current = messages;
  const chartVisible = selectVisibleChartMessages(messages);

  useEffect(() => {
    setMicSupported(typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined');
  }, []);

  useEffect(() => {
    if (voiceState !== 'recording') return;
    const timer = window.setInterval(() => {
      const seconds = (Date.now() - recordStartedRef.current) / 1000;
      setRecordSeconds(Math.min(30, seconds));
      if (seconds >= 30 && recorderRef.current?.state === 'recording') recorderRef.current.stop();
    }, 150);
    return () => window.clearInterval(timer);
  }, [voiceState]);

  useEffect(() => () => {
    streamRef.current?.getTracks().forEach(track => track.stop());
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
  }, []);

  const setWallet = useCallback((value: number) => { setBalance(value); onBalance(value); }, [onBalance]);
  const loadEntries = useCallback(async (offset = 0) => {
    return api<HistoryEntry[]>(`/history?limit=${PAGE_SIZE}&offset=${offset}`);
  }, []);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const [items, wallet] = await Promise.all([loadEntries(0), api<{ balance: number }>('/wallet')]);
        if (!live) return;
        setEntries(items); setHistoryOffset(items.length); setHasOlder(items.length === PAGE_SIZE); setWallet(wallet.balance);
        const chat = fromHistory(items);
        setMessages(chat.length ? chat : [{ key: 'greeting', role: 'assistant', text: "What's on your mind today?", state: 'greeting' }]);
        void (async () => {
          try {
            await api('/events', { method: 'POST', body: JSON.stringify({ event: 'session_start' }) });
            const insight = await api<DailyInsight>('/insight/today');
            if (live) setDailyInsight(insight);
          } catch {
            if (live) setDailyInsightError('Today’s insight could not load just now. Please try again shortly.');
          } finally { if (live) setDailyInsightLoading(false); }
        })();
      } catch (error: unknown) {
        if (error instanceof Error && error.message.includes('session has ended')) onLogout();
        else setComposerError('We couldn’t load your conversations. Pull to retry or refresh the page.');
        setMessages([{ key: 'greeting', role: 'assistant', text: "What's on your mind today?", state: 'greeting' }]);
      } finally { if (live) setLoadingHistory(false); }
    })();
    return () => { live = false; };
  }, [loadEntries, onLogout, setWallet]);

  useEffect(() => {
    if (!initialQuestion?.trim()) return;
    setDraft(initialQuestion);
    if (composerRef.current) {
      composerRef.current.style.height = 'auto';
      composerRef.current.style.height = `${Math.min(composerRef.current.scrollHeight, 104)}px`;
    }
  }, [initialQuestion]);

  useEffect(() => {
    if (openAddQuestions) { setCreditError(''); setCreditOpen(true); }
  }, [openAddQuestions]);

  useEffect(() => {
    if (!focusQuestionId || loadingHistory || focusedHistoryIdRef.current === focusQuestionId) return;
    focusedHistoryIdRef.current = focusQuestionId;
    let cancelled = false;
    void (async () => {
      let allEntries = entries;
      let offset = historyOffset;
      let stillHasOlder = hasOlder;
      while (!allEntries.some(entry => entry.id === focusQuestionId)) {
        const older = await loadEntries(offset).catch(() => [] as HistoryEntry[]);
        if (!older.length) { stillHasOlder = false; break; }
        allEntries = [...allEntries, ...older];
        offset += older.length;
        stillHasOlder = older.length === PAGE_SIZE;
        if (!stillHasOlder) break;
      }
      if (cancelled || !allEntries.some(entry => entry.id === focusQuestionId)) return;
      setEntries(allEntries);
      setMessages(fromHistory(allEntries));
      setHistoryOffset(offset);
      setHasOlder(stillHasOlder);
      window.setTimeout(() => document.getElementById(`chat-question-${focusQuestionId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 100);
    })();
    return () => { cancelled = true; };
  }, [entries, focusQuestionId, hasOlder, historyOffset, loadEntries, loadingHistory]);

  useEffect(() => {
    if (!dailyInsight || !dailyInsightRef.current || insightViewedRef.current === dailyInsight.id) return;
    const markViewed = () => {
      if (insightViewedRef.current === dailyInsight.id) return;
      insightViewedRef.current = dailyInsight.id;
      void api('/events', { method: 'POST', body: JSON.stringify({ event: 'insight_viewed' }) }).catch(() => {});
    };
    if (typeof IntersectionObserver === 'undefined') { markViewed(); return; }
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { markViewed(); observer.disconnect(); }
    }, { root: threadRef.current, threshold: 0.5 });
    observer.observe(dailyInsightRef.current);
    return () => observer.disconnect();
  }, [dailyInsight]);

  useEffect(() => {
    const updateOnline = () => setOffline(!navigator.onLine);
    window.addEventListener('online', updateOnline); window.addEventListener('offline', updateOnline);
    const updateViewport = () => {
      const viewport = window.visualViewport;
      const keyboardOffset = viewport ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop) : 0;
      document.documentElement.style.setProperty('--keyboard-offset', `${keyboardOffset}px`);
      const keyboardOpen = window.matchMedia('(max-width: 767px)').matches && keyboardOffset > 100;
      setIsKeyboardOpen(keyboardOpen);
      onKeyboardChange?.(keyboardOpen);
    };
    updateViewport(); window.visualViewport?.addEventListener('resize', updateViewport); window.visualViewport?.addEventListener('scroll', updateViewport);
    return () => { window.removeEventListener('online', updateOnline); window.removeEventListener('offline', updateOnline); window.visualViewport?.removeEventListener('resize', updateViewport); window.visualViewport?.removeEventListener('scroll', updateViewport); document.documentElement.style.removeProperty('--keyboard-offset'); onKeyboardChange?.(false); };
  }, [onKeyboardChange]);

  useLayoutEffect(() => {
    const thread = threadRef.current;
    if (!thread) return;
    if (restoreScrollRef.current !== null) {
      const oldHeight = restoreScrollRef.current;
      thread.scrollTop += thread.scrollHeight - oldHeight;
      restoreScrollRef.current = null;
      return;
    }
    if (atBottomRef.current) {
      thread.scrollTop = thread.scrollHeight;
      setShowNewMessage(false);
    } else if (messages.length > 0) setShowNewMessage(true);
  }, [messages]);

  const loadOlder = useCallback(async () => {
    if (loadingOlderRef.current || !hasOlder) return;
    const thread = threadRef.current;
    loadingOlderRef.current = true; setLoadingOlder(true);
    if (thread) restoreScrollRef.current = thread.scrollHeight;
    try {
      const older = await loadEntries(historyOffset);
      setEntries(current => [...current, ...older.filter(item => !current.some(existing => existing.id === item.id))]);
      setHistoryOffset(current => current + older.length); setHasOlder(older.length === PAGE_SIZE);
      const olderMessages = fromHistory(older);
      setMessages(current => {
        const existing = new Set(current.map(item => item.key));
        const prefix = olderMessages.filter(item => !existing.has(item.key));
        if (!prefix.length) restoreScrollRef.current = null;
        return [...prefix, ...current.filter(item => item.key !== 'greeting')];
      });
    } catch { restoreScrollRef.current = null; setComposerError('Older conversations could not load. Try again.'); }
    finally { loadingOlderRef.current = false; setLoadingOlder(false); }
  }, [hasOlder, historyOffset, loadEntries]);

  function updateMessage(key: string, update: (message: ChatMessage) => ChatMessage) {
    setMessages(current => current.map(message => message.key === key ? update(message) : message));
  }

  function openFacts(message: Pick<ChatMessage, 'facts'>) {
    void api('/events', { method: 'POST', body: JSON.stringify({ event: 'facts_sheet_opened' }) }).catch(() => {});
    setFactsFor({ key: 'facts-sheet', role: 'assistant', text: '', facts: message.facts || [] });
  }

  async function reconcileQuestion(questionText: string, messageKey: string) {
    try {
      const recent = await loadEntries(0);
      const match = recent.find(item => item.question_text === questionText);
      if (!match) return;
      setEntries(current => [match, ...current.filter(item => item.id !== match.id)]);
      const replyKey = `live-${messageKey}`;
      setMessages(current => {
        const userMessage = current.find(item => item.key === messageKey);
        if (match.status === 'answered') {
          const assistant: ChatMessage = { key: `a-${match.id}`, role: 'assistant', text: match.answer_text || '', questionId: match.id, facts: match.facts_used, rating: match.rating, state: 'done' };
          return [...current.filter(item => item.key !== replyKey && item.key !== `q-${messageKey}`), ...(userMessage ? [{ ...userMessage, key: `q-${match.id}`, questionId: match.id }] : []), assistant];
        }
        const state: MessageState = match.status === 'draft' ? 'out_of_balance' : match.status === 'failed' ? 'error' : 'pending';
        const assistant: ChatMessage = { key: `a-${match.id}`, role: 'assistant', text: state === 'out_of_balance' ? 'I saved your question. Add questions and I’ll answer it automatically.' : state === 'error' ? 'Couldn’t reach the stars. Tap to retry.' : '', questionId: match.id, facts: match.facts_used || [], state, retryText: match.question_text };
        return [...current.filter(item => item.key !== replyKey && item.key !== `q-${messageKey}`), ...(userMessage ? [{ ...userMessage, key: `q-${match.id}`, questionId: match.id }] : []), assistant];
      });
    } catch { /* The inline retry remains available when synchronization is temporarily offline. */ }
  }

  async function streamAnswer(options: { userKey: string; assistantKey: string; questionText: string; draftId?: number; retryId?: number }) {
    setBusy(true); setComposerError(''); setCreditMessage(''); atBottomRef.current = true; setShowNewMessage(false);
    let activeAssistantKey = options.assistantKey;
    updateMessage(activeAssistantKey, item => ({ ...item, state: 'typing', text: '', waitingStage: undefined, retryText: options.questionText }));
    const controller = new AbortController();
    let timedOut = false;
    let cancelWaitTimers = () => {};
    cancelWaitTimers = startTypingWaitTimers(
      stage => setMessages(current => current.map(item => item.role === 'assistant' && item.state === 'typing' && item.retryText === options.questionText ? { ...item, waitingStage: stage } : item)),
      () => {
        timedOut = true;
        setMessages(current => current.map(item => item.role === 'assistant' && (item.state === 'typing' || item.state === 'pending') && item.retryText === options.questionText ? { ...item, state: 'error', text: 'Couldn’t reach the stars. Tap to retry.', waitingStage: undefined, retryText: options.questionText } : item));
        controller.abort();
        void loadEntries(0).then(recent => {
          const match = recent.find(item => item.question_text === options.questionText);
          if (!match) return;
          setEntries(current => [match, ...current.filter(item => item.id !== match.id)]);
          setMessages(current => current.map(item => item.key === options.assistantKey || item.key === `a-${match.id}` ? { ...item, key: `a-${match.id}`, questionId: match.id, state: 'error' as const, text: 'Couldn’t reach the stars. Tap to retry.', retryText: options.questionText, facts: match.facts_used || [] } : item).map(item => item.key === options.userKey ? { ...item, key: `q-${match.id}`, questionId: match.id } : item));
        }).catch(() => {});
      },
    );
    try {
      const body = options.retryId ? { retry_id: options.retryId } : options.draftId ? { draft_id: options.draftId } : { question_text: options.questionText };
      const response = await fetch('/api/ask', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: controller.signal });
      if (response.status === 402) {
        const payload = await response.json();
        setWallet(payload.wallet_balance ?? 0);
        setMessages(current => {
          const actualQuestionKey = `q-${payload.question_id}`; const actualReplyKey = `a-${payload.question_id}`;
          const user = current.find(item => item.key === options.userKey) || { key: actualQuestionKey, role: 'user' as const, text: options.questionText, questionId: payload.question_id };
          const reply: ChatMessage = { key: actualReplyKey, role: 'assistant', text: 'I saved your question. Add questions and I’ll answer it automatically.', questionId: payload.question_id, state: 'out_of_balance', retryText: options.questionText };
          return [...current.filter(item => item.key !== options.userKey && item.key !== options.assistantKey && item.key !== actualQuestionKey && item.key !== actualReplyKey), { ...user, key: actualQuestionKey, questionId: payload.question_id }, reply];
        });
        try { const recent = await loadEntries(0); setEntries(current => [...recent, ...current.filter(item => !recent.some(entry => entry.id === item.id))]); } catch { /* Local thread already shows the saved question. */ }
        return;
      }
      if (!response.ok || !response.body) throw new Error('network');
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''; let failed = false; let streamId: number | undefined;
      async function appendWordByWord(text: string) {
        const words = text.match(/\S+\s*/g) || [text];
        for (const word of words) {
          updateMessage(activeAssistantKey, item => ({ ...item, state: 'streaming', text: item.text + word, waitingStage: undefined }));
          await new Promise(resolve => window.setTimeout(resolve, 24));
        }
      }
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n'); buffer = events.pop() || '';
        for (const event of events) {
          const eventName = event.match(/^event: (.+)$/m)?.[1]; const raw = event.match(/^data: (.+)$/m)?.[1]; if (!raw) continue;
          const payload = JSON.parse(raw);
          if (eventName === 'started') {
            streamId = payload.question_id; setWallet(payload.wallet_balance ?? balance);
            const stableQuestion = `q-${streamId}`; const stableReply = `a-${streamId}`;
            activeAssistantKey = stableReply;
            setMessages(current => current.map(message => message.key === options.userKey ? { ...message, key: stableQuestion, questionId: streamId } : message.key === options.assistantKey ? { ...message, key: stableReply, questionId: streamId } : message));
          }
          if (eventName === 'meta') {
            streamId = payload.question_id; setWallet(payload.wallet_balance ?? balance);
            const stableReply = `a-${streamId}`;
            activeAssistantKey = stableReply;
            setMessages(current => current.map(message => message.key === options.assistantKey || message.key === stableReply ? { ...message, key: stableReply, questionId: streamId, facts: payload.facts_used || [], highlightedHouses: payload.highlighted_houses || [], state: 'typing' } : message));
          }
          if (eventName === 'chunk' && payload.text) { cancelWaitTimers(); await appendWordByWord(payload.text); }
          if (eventName === 'complete') {
            setWallet(payload.wallet_balance ?? balance);
            const stableReply = `a-${payload.question_id}`;
            cancelWaitTimers();
            setMessages(current => current.map(message => message.key === options.assistantKey || message.key === stableReply ? { ...message, key: stableReply, questionId: payload.question_id, text: payload.answer_text || message.text, facts: payload.facts_used || message.facts || [], highlightedHouses: payload.highlighted_houses || message.highlightedHouses || [], state: 'done', waitingStage: undefined } : message));
          }
          if (eventName === 'failed') {
            failed = true; setWallet(payload.wallet_balance ?? balance);
            const stableReply = `a-${payload.question_id || streamId}`;
            activeAssistantKey = stableReply;
            cancelWaitTimers();
            setMessages(current => current.map(message => message.key === options.assistantKey || message.key === stableReply ? { ...message, key: stableReply, questionId: payload.question_id || streamId, text: 'Couldn’t reach the stars. Tap to retry.', state: 'error', waitingStage: undefined, retryText: options.questionText } : message));
          }
        }
      }
      if (streamId) {
        try { const recent = await loadEntries(0); setEntries(current => [...recent, ...current.filter(item => !recent.some(entry => entry.id === item.id))]); } catch { /* The streamed reply is still displayed. */ }
      }
      if (failed) updateMessage(activeAssistantKey, item => ({ ...item, state: 'error' }));
    } catch {
      if (!timedOut) {
        updateMessage(activeAssistantKey, item => ({ ...item, state: 'error', text: 'Couldn’t reach the stars. Tap to retry.', waitingStage: undefined, retryText: options.questionText }));
        await reconcileQuestion(options.questionText, options.userKey);
      }
    } finally { cancelWaitTimers(); setBusy(false); }
  }

  async function sendQuestion(text: string) {
    const clean = text.trim(); if (!clean || busy) return;
    const local = `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const replyKey = `live-${local}`;
    atBottomRef.current = true; setShowNewMessage(false); setComposerError(''); setDraft('');
    if (composerRef.current) composerRef.current.style.height = 'auto';
    setMessages(current => [...current.filter(item => item.key !== 'greeting'), { key: local, role: 'user', text: clean }, { key: replyKey, role: 'assistant', text: '', state: 'typing', retryText: clean }]);
    await streamAnswer({ userKey: local, assistantKey: replyKey, questionText: clean });
  }

  async function retryMessage(message: ChatMessage) {
    if (busy || !message.retryText) return;
    const existingId = message.questionId;
    const assistantKey = message.key;
    const userKey = existingId ? `q-${existingId}` : `local-retry-${Date.now()}`;
    if (!existingId) setMessages(current => current.some(item => item.key === userKey) ? current : [...current, { key: userKey, role: 'user', text: message.retryText! }]);
    await streamAnswer({ userKey, assistantKey, questionText: message.retryText, retryId: existingId });
  }

  async function resumeDraft(id: number, userText: string) {
    const replyKey = `a-${id}`;
    setCreditMessage('Questions added. I’m answering your saved question now.');
    await streamAnswer({ userKey: `q-${id}`, assistantKey: replyKey, questionText: userText, draftId: id });
  }

  async function addQuestions() {
    setCreditBusy(true); setCreditError('');
    try {
      const wallet = await api<{ balance: number }>('/wallet/add', { method: 'POST', body: JSON.stringify({ amount: 10 }) });
      setWallet(wallet.balance); setCreditOpen(false); setCreditMessage('10 free test questions added.');
      const allRecent = await api<HistoryEntry[]>('/history?limit=100&offset=0');
      setEntries(current => [...allRecent, ...current.filter(item => !allRecent.some(entry => entry.id === item.id))]);
      const oldestDraft = allRecent.filter(item => item.status === 'draft').sort((a,b)=>a.id-b.id)[0];
      if (oldestDraft) {
        if (!messagesRef.current.some(message => message.key === `q-${oldestDraft.id}`)) setMessages(current => [...current, { key: `q-${oldestDraft.id}`, role: 'user', text: oldestDraft.question_text, questionId: oldestDraft.id }]);
        if (!messagesRef.current.some(message => message.key === `a-${oldestDraft.id}`)) setMessages(current => [...current, { key: `a-${oldestDraft.id}`, role: 'assistant', text: '', state: 'typing', questionId: oldestDraft.id, retryText: oldestDraft.question_text }]);
        await resumeDraft(oldestDraft.id, oldestDraft.question_text);
      }
    } catch (error: unknown) { setCreditError(error instanceof Error ? error.message : 'Question credits are unavailable right now.'); }
    finally { setCreditBusy(false); }
  }

  async function rateAnswer(id: number, value: number) {
    try {
      await api(`/questions/${id}/rating`, { method: 'POST', body: JSON.stringify({ rating: value }) });
      setMessages(current => current.map(message => message.questionId === id && message.role === 'assistant' ? { ...message, rating: value } : message));
      setEntries(current => current.map(entry => entry.id === id ? { ...entry, rating: value } : entry));
    } catch { setComposerError('Your rating could not be saved. Please try again.'); }
  }

  function jumpToQuestion(id: number) {
    setHistoryOpen(false); atBottomRef.current = false; setShowNewMessage(false);
    window.setTimeout(() => document.getElementById(`chat-question-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 80);
  }

  function onComposerKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && window.matchMedia('(pointer: fine)').matches) {
      event.preventDefault(); void sendQuestion(draft);
    }
  }

  function onComposerChange(value: string) {
    setDraft(value);
    const textarea = composerRef.current;
    if (textarea) { textarea.style.height = 'auto'; textarea.style.height = `${Math.min(textarea.scrollHeight, 104)}px`; }
  }

  async function transcribeRecording(blob: Blob, duration: number) {
    retryAudioRef.current = { blob, duration };
    setVoiceState('transcribing'); setVoiceMessage('Transcribing your recording…'); setVoiceTrimmed(false);
    const data = new FormData();
    const extension = blob.type.includes('mp4') ? 'm4a' : blob.type.includes('ogg') ? 'ogg' : blob.type.includes('wav') ? 'wav' : 'webm';
    data.append('file', blob, `recording.${extension}`);
    data.append('duration_seconds', String(duration));
    try {
      const response = await fetch('/api/speech/transcribe', { method: 'POST', credentials: 'same-origin', body: data });
      if (!response.ok) {
        setVoiceState('error');
        setVoiceMessage(response.status === 429 ? 'Please wait a minute before trying voice again.' : response.status === 413 ? 'That recording was too large. Try a shorter clip.' : 'Couldn’t reach transcription. Check your connection and try again.');
        return;
      }
      const result = await response.json() as { transcript?: string; truncated?: boolean };
      const capped = capTranscript(result.transcript || '');
      if (!capped.text) { setVoiceState('empty'); setVoiceMessage('I couldn’t hear anything. Try again.'); return; }
      onComposerChange(capped.text);
      setVoiceTrimmed(capped.truncated || !!result.truncated);
      setVoiceState('idle');
      setVoiceMessage(capped.truncated || result.truncated ? 'Transcript trimmed to 250 characters. Review and edit it before sending.' : 'Transcript added to your message. Review and edit it before sending.');
      retryAudioRef.current = null;
    } catch {
      setVoiceState('error'); setVoiceMessage('Couldn’t reach transcription. Check your connection and try again.');
    }
  }

  async function startRecording() {
    setVoiceMessage(''); setVoiceState('requesting'); cancelledRecordingRef.current = false;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = selectRecorderMimeType(type => MediaRecorder.isTypeSupported(type));
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      recorderRef.current = recorder; recordingChunksRef.current = []; recordStartedRef.current = Date.now(); setRecordSeconds(0);
      recorder.ondataavailable = event => { if (event.data.size) recordingChunksRef.current.push(event.data); };
      recorder.onstop = () => {
        stream.getTracks().forEach(track => track.stop()); streamRef.current = null;
        if (cancelledRecordingRef.current) return;
        const duration = (Date.now() - recordStartedRef.current) / 1000;
        if (duration < 1) { setVoiceState('too_short'); setVoiceMessage('That was very short. Hold the mic for at least a second and try again.'); return; }
        const blob = new Blob(recordingChunksRef.current, { type: recorder.mimeType || mimeType || 'audio/webm' });
        if (!blob.size) { setVoiceState('empty'); setVoiceMessage('I couldn’t hear anything. Try again.'); return; }
        void transcribeRecording(blob, Math.min(30, duration));
      };
      recorder.start(250); setVoiceState('recording');
    } catch (error) {
      streamRef.current?.getTracks().forEach(track => track.stop()); streamRef.current = null;
      const name = error instanceof DOMException ? error.name : '';
      if (name === 'NotAllowedError' || name === 'PermissionDeniedError' || name === 'SecurityError') { setVoiceState('denied'); setVoiceMessage('Microphone access is blocked. Allow it for this site in your browser’s site settings, then try again.'); }
      else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') { setVoiceState('no_mic'); setVoiceMessage('No microphone was found. Connect one and try again.'); }
      else { setVoiceState('error'); setVoiceMessage('The microphone could not start. Check browser permissions and try again.'); }
    }
  }

  function stopRecording() { if (recorderRef.current?.state === 'recording') recorderRef.current.stop(); }
  function cancelRecording() {
    cancelledRecordingRef.current = true;
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
    streamRef.current?.getTracks().forEach(track => track.stop()); streamRef.current = null;
    recordingChunksRef.current = []; setVoiceState('idle'); setVoiceMessage('');
  }

  return <main className="chat-frame fixed inset-0 z-10 flex h-[100dvh] flex-col overflow-hidden bg-void text-ink md:left-64">
    <header className="z-20 flex shrink-0 items-center justify-between gap-2 border-b border-line/80 bg-[#0b090e]/95 px-3 py-2.5 backdrop-blur-md sm:px-5" style={{ paddingTop: 'max(.65rem, env(safe-area-inset-top))' }}>
      <div className="flex min-w-0 items-center gap-2.5"><BrandMark small/><div className="min-w-0"><p className="truncate font-display text-base leading-5">Melooha</p><p className="max-w-32 truncate text-[10px] text-muted sm:max-w-none">{profile.display_name || profile.label}</p></div></div>
      <div className="flex shrink-0 items-center gap-1.5"><button onClick={()=>onNavigate ? onNavigate('history') : setHistoryOpen(true)} aria-label="Conversation history" className="grid size-9 place-items-center rounded-full border border-line text-sm text-muted hover:bg-panel-hover hover:text-ink">◷</button><div className="flex items-center gap-1 rounded-full border border-line bg-panel px-2 py-1 sm:gap-2 sm:px-3"><span className="whitespace-nowrap text-[10px] text-muted sm:text-xs"><strong className="text-ink">{balance}</strong><span className="hidden sm:inline"> questions left</span><span className="sm:hidden"> left</span></span><button onClick={()=>{setCreditError('');setCreditOpen(true);}} className="rounded-full bg-magenta px-2.5 py-1 text-[10px] font-semibold text-white hover:bg-magenta-bright sm:text-xs">Add</button></div><button onClick={onLogout} aria-label="Sign out" className="grid size-9 place-items-center rounded-full border border-line text-xs text-muted hover:bg-panel-hover text-ink-soft sm:hidden">↪</button><button onClick={onLogout} aria-label="Sign out" className="hidden rounded-full px-2 py-2 text-[11px] text-muted hover:text-ink sm:block">Sign out</button></div>
    </header>

    <div ref={threadRef} onScroll={event => { const element = event.currentTarget; const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 100; atBottomRef.current = nearBottom; if (nearBottom) setShowNewMessage(false); else if (messages.length && !atBottomRef.current) setShowNewMessage(current => current); if (element.scrollTop < 50 && hasOlder && !loadingOlderRef.current) void loadOlder(); }} className="thread-scroll relative min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 sm:px-5">
      <div className="mx-auto flex min-h-full w-full max-w-[760px] flex-col justify-end pb-8 pt-5" style={{ paddingBottom: 'calc(7.25rem + env(safe-area-inset-bottom) + var(--keyboard-offset, 0px))' }}>
        {loadingHistory && <div className="mb-5 flex items-center gap-3"><BrandMark small/><div className="h-12 w-48 animate-pulse rounded-2xl bg-panel"/></div>}
        {hasOlder && <div className="mb-5 text-center"><button disabled={loadingOlder} onClick={()=>void loadOlder()} className="rounded-full border border-line bg-panel px-4 py-2 text-[11px] text-muted hover:text-ink disabled:opacity-50">{loadingOlder?'Loading older messages…':'↑ Load earlier messages'}</button></div>}
        <section ref={dailyInsightRef} aria-label="Today for you" onClick={()=>{if(dailyInsight)openFacts({facts:dailyInsight.facts_used});}} className="mb-6 cursor-pointer rounded-[1.4rem] border border-magenta/25 bg-[linear-gradient(135deg,#241522,#151119_65%)] p-4 shadow-[0_16px_55px_-38px_#e52a91] sm:p-5">
          <div className="flex items-start justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-[.19em] text-[#ef9bc8]">Today for you</p><h2 className="mt-1 font-display text-xl">A note for today</h2></div><span className="shrink-0 rounded-full border border-line bg-void/50 px-3 py-1.5 text-[10px] font-medium text-ink-soft">✧ {dailyInsight?.streak_days ?? 0} day streak</span></div>
          {dailyInsightLoading ? <p className="mt-3 text-sm text-muted">Gathering today’s chart notes…</p> : dailyInsight ? <><div className="mt-2"><ReadingAnswer text={dailyInsight.answer_text} facts={dailyInsight.facts_used}/></div><button onClick={event=>{event.stopPropagation();openFacts({ facts: dailyInsight.facts_used });}} className="mt-3 inline-flex min-h-9 items-center gap-1.5 rounded-full border border-line bg-panel/80 px-3 py-1.5 text-[11px] font-medium text-ink-soft hover:border-magenta/40 hover:text-white"><span aria-hidden="true">✧</span> See chart facts</button></> : <div className="mt-3"><p role="status" className="text-sm text-muted">{dailyInsightError || 'Today’s note is not ready yet.'}</p><button onClick={event=>{event.stopPropagation();setDailyInsightLoading(true);setDailyInsightError('');void api<DailyInsight>('/insight/today').then(setDailyInsight).catch(()=>setDailyInsightError('Today’s insight could not load just now. Please try again shortly.')).finally(()=>setDailyInsightLoading(false));}} className="mt-2 rounded-full border border-line px-3 py-2 text-xs text-ink-soft hover:border-magenta/40">Try again</button></div>}
        </section>
        {messages.map((message, messageIndex) => message.role === 'user' ? <div key={message.key} id={message.questionId ? `chat-question-${message.questionId}` : undefined} className="mb-5 flex justify-end"><div className="max-w-[86%] rounded-[1.35rem] rounded-br-md border border-[#814b72]/30 bg-[#422039] px-4 py-3 text-sm leading-6 text-[#fff5fb] shadow-[0_10px_35px_-25px_#e52a91] sm:max-w-[78%]">{message.text}</div></div> : <div key={message.key} id={message.questionId ? `chat-reply-${message.questionId}` : undefined} className="mb-6 flex items-start gap-2.5 sm:gap-3"><BrandMark small/><div className="min-w-0 max-w-[90%] flex-1 sm:max-w-[86%]">
          {message.state === 'typing' || message.state === 'pending' ? <TypingIndicator stage={message.waitingStage}/> : <div className="rounded-[1.35rem] rounded-tl-md border border-line bg-[#151119] px-4 py-3.5 text-sm leading-7 text-ink-soft shadow-[0_12px_40px_-34px_#d4a2cc] sm:px-5 sm:py-4">
            {message.state === 'greeting' ? <><p className="font-display text-lg leading-7 text-ink">What&apos;s on your mind today?</p><div className="mt-4 flex flex-wrap gap-2">{suggestions.map(item=><button key={item} disabled={busy} onClick={()=>void sendQuestion(item)} className="rounded-full border border-line bg-[#1c1721] px-3.5 py-2 text-left text-[11px] leading-4 text-ink-soft transition hover:border-magenta/50 hover:text-white disabled:opacity-50">{item}<span className="ml-1 text-magenta-bright">↗</span></button>)}</div></> : message.state === 'error' ? <><p className="text-ink">Couldn’t reach the stars.</p><p className="mt-1 text-xs text-muted">This one was free; you were not charged.</p><Button variant="secondary" onClick={()=>void retryMessage(message)} disabled={busy || !message.retryText} className="mt-3 min-h-9 px-3.5 text-xs">↻ Tap to retry</Button></> : message.state === 'out_of_balance' ? <><p className="text-ink">I saved your question. Add questions and I&apos;ll answer it automatically.</p><Button onClick={()=>{setCreditError('');setCreditOpen(true);}} className="mt-3 min-h-9 px-3.5 text-xs">Add questions · free test credits</Button></> : <>{message.state === 'done' && chartVisible[messageIndex] && <div className="mb-3 w-full max-w-[250px] overflow-hidden rounded-xl" style={{ width: 250, aspectRatio: '1 / 1' }}><ChartDiagram facts={chartFacts.length ? chartFacts : message.facts || []} highlightHouses={message.highlightedHouses || []} size="small" language={language} showLabels={false} onExpand={()=>setChartFor(message)} onFactSelect={selected=>openFacts({...message,facts:[selected]})}/></div>}<ReadingAnswer text={message.text} facts={message.facts || []}/></>}
          </div>}
          {message.state === 'done' && <div className="mt-2 flex flex-wrap items-center gap-2 pl-1">{message.questionId && <RatingButtons rating={message.rating ?? null} onRate={value=>void rateAnswer(message.questionId!, value)}/>}<button onClick={()=>openFacts(message)} className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-line bg-panel px-3 py-1.5 text-[11px] font-medium text-ink-soft hover:border-magenta/40 hover:text-white"><span aria-hidden="true">✧</span> See chart facts</button><ListenButton text={message.text} language={language}/></div>}
        </div></div>)}
        {composerError && <div role="status" className="mb-5 rounded-xl border border-danger/20 bg-danger/10 px-4 py-2.5 text-xs text-danger">{composerError}<button onClick={()=>setComposerError('')} className="ml-2 underline">Dismiss</button></div>}
        <div aria-live="polite" className="sr-only">{busy?'Melooha is responding.':''}</div>
      </div>
      {showNewMessage && <button onClick={()=>{atBottomRef.current=true;threadRef.current?.scrollTo({top:threadRef.current.scrollHeight,behavior:'smooth'});setShowNewMessage(false);}} className="sticky bottom-3 left-1/2 z-10 mx-auto -mt-16 mb-3 rounded-full border border-magenta/35 bg-[#251522] px-4 py-2 text-xs font-medium text-[#f2b0d0] shadow-xl">↓ New message</button>}
    </div>

    <div className={`composer-shell fixed inset-x-0 z-30 border-t border-line/80 bg-[#0c0a0f]/95 px-3 pb-2.5 pt-2 backdrop-blur-xl sm:px-5 sm:pb-4 md:left-64 ${isKeyboardOpen ? 'bottom-[var(--keyboard-offset,0px)]' : 'bottom-[calc(4rem+env(safe-area-inset-bottom))] md:bottom-[var(--keyboard-offset,0px)]'}`} style={{ paddingBottom: 'max(.65rem, env(safe-area-inset-bottom))' }}>
      <div className="mx-auto max-w-[760px]">{offline && <div role="status" className="mb-2 flex items-center gap-2 text-[11px] text-star"><span className="size-1.5 rounded-full bg-star"/>You’re offline. Your typed question stays here until you reconnect.</div>}{creditMessage && <div role="status" className="mb-2 text-[11px] text-success">{creditMessage}</div>}
        {(voiceState === 'recording' || voiceState === 'requesting' || voiceState === 'transcribing' || voiceMessage) && <div role="status" aria-live="polite" className="mb-2 flex min-h-8 flex-wrap items-center gap-2 text-[11px] text-ink-soft">{voiceState === 'recording' && <><span className="size-2 animate-pulse rounded-full bg-magenta-bright"/><span>Recording · {Math.floor(recordSeconds)}s / 30s</span><button type="button" onClick={stopRecording} className="ml-auto min-h-8 rounded-full border border-line px-3">Stop</button><button type="button" onClick={cancelRecording} className="min-h-8 rounded-full border border-line px-3 text-muted">Cancel</button></>}{voiceState === 'requesting' && <><span className="size-3 animate-spin rounded-full border-2 border-magenta/30 border-t-magenta"/>Waiting for microphone permission…</>}{voiceState === 'transcribing' && <><span className="size-3 animate-spin rounded-full border-2 border-magenta/30 border-t-magenta"/>Transcribing…</>}{voiceMessage && voiceState !== 'recording' && voiceState !== 'requesting' && voiceState !== 'transcribing' && <><span className={voiceState === 'error' || voiceState === 'denied' || voiceState === 'no_mic' ? 'text-danger' : voiceTrimmed ? 'text-star' : 'text-muted'}>{voiceMessage}</span>{voiceState === 'error' && retryAudioRef.current && <button type="button" onClick={()=>void transcribeRecording(retryAudioRef.current!.blob, retryAudioRef.current!.duration)} className="min-h-8 rounded-full border border-line px-3 text-ink-soft">Retry</button>}{(voiceState === 'too_short' || voiceState === 'empty' || voiceState === 'denied' || voiceState === 'no_mic') && micSupported && <button type="button" onClick={()=>void startRecording()} className="min-h-8 rounded-full border border-line px-3 text-ink-soft">Try again</button>}</>}</div>}
        <form onSubmit={(event: FormEvent)=>{event.preventDefault();void sendQuestion(draft);}} className="flex items-end gap-2 rounded-[1.45rem] border border-line bg-[#17131b] p-2 pl-4 shadow-[0_10px_45px_-30px_#e52a91] focus-within:border-magenta/50"><label htmlFor="chat-composer" className="sr-only">Message Melooha</label><textarea ref={composerRef} id="chat-composer" rows={1} value={draft} onChange={event=>onComposerChange(event.target.value)} onKeyDown={onComposerKey} placeholder={voiceState === 'transcribing' ? 'Transcribing…' : offline?'Waiting for your connection…':'Message Melooha…'} className="max-h-[104px] min-h-8 flex-1 resize-none bg-transparent py-1.5 text-sm leading-6 text-ink placeholder:text-muted-dark outline-none" aria-label="Message Melooha" aria-busy={voiceState === 'transcribing'}/>{micSupported && voiceState !== 'recording' && <button type="button" aria-label="Record voice message" title="Record voice message" disabled={busy || voiceState === 'requesting' || voiceState === 'transcribing'} onClick={()=>void startRecording()} className="grid size-10 shrink-0 place-items-center rounded-full border border-line text-base text-ink-soft transition hover:border-magenta/50 hover:text-white disabled:opacity-40">🎙</button>}<button type="submit" aria-label="Send message" disabled={!draft.trim() || busy || offline} className="grid size-10 shrink-0 place-items-center rounded-full bg-magenta text-lg text-white transition hover:bg-magenta-bright disabled:cursor-not-allowed disabled:opacity-40">↑</button></form><p className="mt-1 hidden text-center text-[10px] text-muted-dark sm:block">Enter to send · Shift + Enter for a new line</p></div>
    </div>

    {historyOpen && <HistorySheet entries={entries} hasOlder={hasOlder} loading={loadingOlder} onOlder={()=>void loadOlder()} onSelect={jumpToQuestion} onClose={()=>setHistoryOpen(false)}/>}
    {factsFor && <FactsSheet facts={factsFor.facts || []} language={language} onClose={()=>setFactsFor(null)}/>}
    {chartFor && <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm" onMouseDown={event=>{if(event.target===event.currentTarget)setChartFor(null);}}><section role="dialog" aria-modal="true" aria-label="Chart diagram" className="absolute inset-0 flex flex-col overflow-y-auto border-line bg-[#100d13] p-5 sm:inset-y-6 sm:left-1/2 sm:right-auto sm:w-[min(92vw,620px)] sm:-translate-x-1/2 sm:rounded-3xl sm:border sm:p-7"><header className="flex items-center justify-between"><div><p className="text-[10px] uppercase tracking-[.2em] text-star">Your chart</p><h2 className="font-display text-2xl">Chart houses</h2></div><button onClick={()=>setChartFor(null)} aria-label="Close chart" className="grid size-10 place-items-center rounded-full border border-line text-lg text-muted">×</button></header><ChartDiagram facts={chartFacts.length?chartFacts:chartFor.facts||[]} highlightHouses={chartFor.highlightedHouses||[]} size="large" language={language} className="mx-auto mt-5 w-full max-w-[500px]"/><ShareChartButton className="mt-4" facts={chartFacts.length?chartFacts:chartFor.facts||[]} firstName={profile.display_name?.split(/\s+/)[0]||'My'} birthDetails={[profile.birth_date||'',profile.birth_time_unknown?'Birth time unknown':profile.birth_time||'',profile.location||'']} language={language}/></section></div>}
    {creditOpen && <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur-sm" onMouseDown={event=>{if(event.target===event.currentTarget)setCreditOpen(false);}}><Card role="dialog" aria-modal="true" aria-labelledby="credits-title" className="w-full max-w-sm p-6"><div className="flex items-start justify-between"><div><p className="text-[10px] uppercase tracking-[.2em] text-star">Question balance</p><h2 id="credits-title" className="mt-2 font-display text-2xl">Add questions</h2></div><button aria-label="Close" onClick={()=>setCreditOpen(false)} className="grid size-9 place-items-center rounded-full border border-line text-lg text-muted">×</button></div><p className="mt-3 text-sm leading-6 text-muted">Add 10 questions. Your saved question will start automatically once they’re added.</p><div className="mt-5 rounded-2xl border border-line bg-void-soft p-4"><div className="flex justify-between text-sm"><span className="text-muted">Current balance</span><strong>{balance}</strong></div><div className="my-3 h-px bg-line"/><div className="flex justify-between text-sm"><span className="text-muted">10 test questions</span><strong className="text-[#ef91c4]">Free</strong></div></div><p className="mt-3 text-xs text-muted-dark">Price: Free test credits. No payment is taken.</p>{creditError && <p role="alert" className="mt-3 rounded-lg bg-danger/10 p-3 text-xs text-danger">{creditError}</p>}<div className="mt-6 flex gap-3"><Button variant="secondary" onClick={()=>setCreditOpen(false)} className="flex-1">Cancel</Button><Button onClick={()=>void addQuestions()} disabled={creditBusy} className="flex-1">{creditBusy?'Adding…':'Add 10 free'}</Button></div></Card></div>}
  </main>;
}
