'use client';

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { ChatApp, FactsSheet } from './chat';
import { BrandMark, Button, Card, EmptyState, Eyebrow, FactPanel, Field, inputClass, ListenButton, ReadingAnswer } from './ui';
import { hasConversation, isZeroBalance, routeFromHash } from './workspace-state.mjs';
import { ChartDiagram, ShareChartButton } from './chart-diagram';

export type AccountProfile = {
  id: number;
  label: string;
  display_name: string | null;
  birth_date: string;
  birth_time: string;
  birth_time_unknown: boolean;
  timezone: string;
  location: string;
  latitude: number | null;
  longitude: number | null;
  chart_facts: string[];
  chart_style: 'north' | 'south';
};
type Route = 'home' | 'chat' | 'chart' | 'history' | 'profile';
type HistoryEntry = { id: number; question_text: string; answer_text: string | null; status: string; rating: number | null; facts_used: string[]; created_at: string };
type Planet = { name: string; sign: string; house: number; retrograde: boolean; nakshatra: string };
type Period = { lord: string; start_date: string; end_date: string };
type ChartData = { lagna_sign: string; planets: Planet[]; current_mahadasha: Period; current_antardasha: Period; current_pratyantardasha: Period; facts: string[] };
type DailyInsight = { id: number; run_date: string; answer_text: string; facts_used: string[]; streak_days: number };

const SUGGESTIONS = ['When might my career gain momentum?', 'What relationship themes stand out?', 'What strengths can I lean on?'];
const ROUTES: { id: Route; label: string; icon: string }[] = [
  { id: 'home', label: 'Home', icon: '⌂' }, { id: 'chat', label: 'Chat', icon: '☾' },
  { id: 'chart', label: 'My Chart', icon: '✧' }, { id: 'history', label: 'History', icon: '◷' }, { id: 'profile', label: 'Profile', icon: '○' },
];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, credentials: 'same-origin', headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers } });
  } catch { throw new Error('Couldn’t connect right now. Check your connection and try again.'); }
  if (!response.ok) throw new Error(response.status === 401 ? 'Your session has ended. Please sign in again.' : 'We couldn’t load this just now. Please try again.');
  return response.status === 204 ? undefined as T : response.json();
}

function Navigation({ route, onNavigate, hiddenOnMobile = false }: { route: Route; onNavigate: (route: Route) => void; hiddenOnMobile?: boolean }) {
  const links = ROUTES.map(item => <button key={item.id} type="button" onClick={() => onNavigate(item.id)} aria-current={route === item.id ? 'page' : undefined} className={`flex min-h-11 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-xl px-1 text-[10px] font-medium transition md:w-full md:flex-row md:justify-start md:gap-3 md:px-4 md:text-sm ${route === item.id ? 'bg-magenta/15 text-[#f3a1cc]' : 'text-muted hover:bg-panel-hover hover:text-ink'}`}><span aria-hidden="true" className="text-lg leading-5 md:w-6 md:text-center">{item.icon}</span><span className="whitespace-nowrap">{item.label}</span></button>);
  return <>
    <nav aria-label="Main navigation" className={`fixed inset-x-0 bottom-0 z-40 flex h-[calc(4.15rem+env(safe-area-inset-bottom))] items-center gap-1 border-t border-line bg-[#0c0a0f]/95 px-1 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl md:hidden ${hiddenOnMobile ? 'hidden' : ''}`}>{links}</nav>
    <nav aria-label="Main navigation" className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-line bg-[#0c0a0f]/95 px-5 py-7 backdrop-blur-xl md:flex"><a href="#home" onClick={event => { event.preventDefault(); onNavigate('home'); }} className="mb-10 flex items-center gap-3 px-2"><BrandMark small/><span className="font-display text-xl">Meloohā</span></a><div className="flex flex-col gap-2">{links}</div><p className="mt-auto px-3 text-[11px] leading-5 text-muted-dark">Vedic astrology for reflection, grounded in your chart.</p></nav>
  </>;
}

function BalancePill({ balance, onAdd }: { balance: number; onAdd: () => void }) {
  return <div className="flex items-center gap-2 rounded-full border border-line bg-panel px-2 py-1.5"><span className="whitespace-nowrap px-1 text-xs text-muted"><strong className="text-ink">{balance}</strong> questions left</span><button onClick={onAdd} className="min-h-9 rounded-full bg-magenta px-3 text-[11px] font-semibold text-white hover:bg-magenta-bright">Add questions</button></div>;
}

function LoadingCards() {
  return <div aria-label="Loading your home" className="space-y-4"><div className="h-36 animate-pulse rounded-card bg-panel"/><div className="h-48 animate-pulse rounded-card bg-panel"/><div className="h-28 animate-pulse rounded-card bg-panel"/></div>;
}

export function Workspace({ profile: initialProfile, balance: initialBalance, onLogout, onProfileChange }: { profile: AccountProfile; balance: number; onLogout: () => void; onProfileChange: (profile: AccountProfile) => void }) {
  const [route, setRoute] = useState<Route>(() => typeof window === 'undefined' ? 'home' : routeFromHash(window.location.hash) as Route);
  const [profile, setProfile] = useState(initialProfile);
  const [balance, setBalance] = useState(initialBalance);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [chart, setChart] = useState<ChartData | null>(null);
  const [chartLoading, setChartLoading] = useState(true);
  const [chartError, setChartError] = useState('');
  const [chartMeaningFacts, setChartMeaningFacts] = useState<string[] | null>(null);
  const [dailyInsight, setDailyInsight] = useState<DailyInsight | null>(null);
  const [dailyInsightLoading, setDailyInsightLoading] = useState(false);
  const [dailyInsightError, setDailyInsightError] = useState('');
  const dailyInsightRef = useRef<HTMLElement>(null);
  const insightViewedRef = useRef<number | null>(null);
  const [walletLoading, setWalletLoading] = useState(true);
  const [workspaceError, setWorkspaceError] = useState('');
  const [prefill, setPrefill] = useState('');
  const [focusQuestionId, setFocusQuestionId] = useState<number | null>(null);
  const [openAddQuestions, setOpenAddQuestions] = useState(false);
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  const [language, setLanguage] = useState('English');
  const [editingProfile, setEditingProfile] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState('');
  const [editName, setEditName] = useState(initialProfile.display_name || '');
  const [editDate, setEditDate] = useState(initialProfile.birth_date);
  const [editTime, setEditTime] = useState(initialProfile.birth_time.slice(0, 5));
  const [editUnknownTime, setEditUnknownTime] = useState(initialProfile.birth_time_unknown);
  const [editLocation, setEditLocation] = useState(initialProfile.location);
  const [editTimezone, setEditTimezone] = useState(initialProfile.timezone || 'Asia/Kolkata');

  const navigate = useCallback((next: Route, options?: { prefill?: string; focusQuestionId?: number; addQuestions?: boolean }) => {
    if (next !== route) window.history.pushState({ meloohaRoute: next }, '', `${window.location.pathname}${window.location.search}#${next}`);
    setRoute(next);
    setKeyboardOpen(false);
    if (next === 'chat') {
      setPrefill(options?.prefill || '');
      setFocusQuestionId(options?.focusQuestionId ?? null);
      setOpenAddQuestions(Boolean(options?.addQuestions));
    }
  }, [route]);

  useEffect(() => {
    const sync = () => setRoute(routeFromHash(window.location.hash) as Route);
    if (window.location.hash) sync();
    else window.history.replaceState({ meloohaRoute: 'home' }, '', `${window.location.pathname}${window.location.search}#home`);
    window.addEventListener('popstate', sync);
    return () => window.removeEventListener('popstate', sync);
  }, []);

  useEffect(() => {
    try { setLanguage(window.localStorage.getItem('melooha-language') || 'English'); } catch { /* Storage may be disabled. */ }
  }, []);

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true); setHistoryError('');
    try {
      const entries = await api<HistoryEntry[]>('/history?limit=20&offset=0');
      setHistory(entries); setHistoryOffset(entries.length); setHasMoreHistory(entries.length === 20);
    } catch { setHistoryError('Your conversation list could not load. Try again.'); }
    finally { setLoadingHistory(false); }
  }, []);

  const loadChart = useCallback(async () => {
    setChartLoading(true); setChartError('');
    try {
      const data = await api<ChartData>('/chart/calculate', { method: 'POST', body: JSON.stringify({ birth_date: profile.birth_date, birth_time: profile.birth_time, timezone: profile.timezone, location: profile.location, latitude: profile.latitude, longitude: profile.longitude }) });
      setChart(data);
    } catch { setChartError('Your chart could not load just now. Please try again.'); }
    finally { setChartLoading(false); }
  }, [profile.birth_date, profile.birth_time, profile.latitude, profile.location, profile.longitude, profile.timezone]);

  const loadDailyInsight = useCallback(async () => {
    setDailyInsightLoading(true); setDailyInsightError('');
    try { setDailyInsight(await api<DailyInsight>('/insight/today')); }
    catch { setDailyInsightError('Today’s note could not load right now. Please try again.'); }
    finally { setDailyInsightLoading(false); }
  }, []);

  useEffect(() => {
    if (route === 'home' && !dailyInsight && !dailyInsightLoading && !dailyInsightError) void loadDailyInsight();
  }, [dailyInsight, dailyInsightError, dailyInsightLoading, loadDailyInsight, route]);

  useEffect(() => {
    if (route !== 'home' || !dailyInsight || !dailyInsightRef.current || insightViewedRef.current === dailyInsight.id) return;
    const markViewed = () => {
      if (insightViewedRef.current === dailyInsight.id) return;
      insightViewedRef.current = dailyInsight.id;
      void api('/events', { method: 'POST', body: JSON.stringify({ event: 'insight_viewed' }) }).catch(() => {});
    };
    if (typeof IntersectionObserver === 'undefined') { markViewed(); return; }
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { markViewed(); observer.disconnect(); }
    }, { threshold: 0.5 });
    observer.observe(dailyInsightRef.current);
    return () => observer.disconnect();
  }, [dailyInsight, route]);

  const refresh = useCallback(async () => {
    setWorkspaceError(''); setWalletLoading(true);
    try {
      const wallet = await api<{ balance: number }>('/wallet');
      setBalance(wallet.balance);
    } catch { setWorkspaceError('Your question balance could not load. Try again.'); }
    finally { setWalletLoading(false); }
    await Promise.all([loadHistory(), loadChart()]);
  }, [loadChart, loadHistory]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (route === 'home') void api('/events', { method: 'POST', body: JSON.stringify({ event: 'home_viewed' }) }).catch(() => {});
  }, [route]);

  const changeLanguage = (next: string) => {
    setLanguage(next);
    try { window.localStorage.setItem('melooha-language', next); } catch { /* Storage may be disabled. */ }
  };

  async function loadOlderHistory() {
    if (loadingMore || !hasMoreHistory) return;
    setLoadingMore(true); setHistoryError('');
    try {
      const older = await api<HistoryEntry[]>(`/history?limit=20&offset=${historyOffset}`);
      setHistory(current => [...current, ...older]); setHistoryOffset(current => current + older.length); setHasMoreHistory(older.length === 20);
    } catch { setHistoryError('Older conversations could not load. Please retry.'); }
    finally { setLoadingMore(false); }
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault(); setProfileSaving(true); setProfileError('');
    try {
      const locationChanged = editLocation.trim() !== profile.location;
      const updated = await api<AccountProfile>('/profile', { method: 'POST', body: JSON.stringify({ display_name: editName.trim(), birth_date: editDate, birth_time: editUnknownTime ? '12:00:00' : `${editTime}:00`, birth_time_unknown: editUnknownTime, timezone: editTimezone, location: editLocation, latitude: locationChanged ? null : profile.latitude, longitude: locationChanged ? null : profile.longitude, label: profile.label || 'My birth chart', chart_style: profile.chart_style || 'north' }) });
      setProfile(updated); onProfileChange(updated); setEditingProfile(false); await loadChart();
    } catch { setProfileError('Your details could not be saved. Check them and try again.'); }
    finally { setProfileSaving(false); }
  }

  const lastEntry = history[0];
  const savedDraft = history.find(entry => entry.status === 'draft');
  const hasHistory = hasConversation(history);
  const moonSign = chart?.planets.find(planet => planet.name === 'Moon')?.sign;
  const currentDasha = chart ? `${chart.current_mahadasha.lord} / ${chart.current_antardasha.lord} · ${chart.current_antardasha.start_date} – ${chart.current_antardasha.end_date}` : '';
  const headerTitle = useMemo(() => ROUTES.find(item => item.id === route)?.label || 'Home', [route]);
  const content = route === 'home' ? <>
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3"><div><Eyebrow>Your chart space</Eyebrow><h1 className="mt-1 font-display text-3xl">Hello, {profile.display_name || 'there'}.</h1></div><BalancePill balance={balance} onAdd={() => navigate('chat', { addQuestions: true })}/></div>
    {isZeroBalance(balance) && <div role="status" className="mb-5 rounded-2xl border border-star/25 bg-[#211a14] p-4 text-sm leading-6 text-ink-soft"><strong className="text-star">{savedDraft ? 'Your question is saved for later.' : 'No questions left right now.'}</strong> {savedDraft ? 'Add questions and it will be answered automatically.' : 'Your next question will be saved and answered once you add questions.'} <span className="block text-xs text-muted">Price: 10 free test questions in this demo; no payment is taken.</span><button onClick={() => navigate('chat', { addQuestions: true })} className="mt-2 min-h-11 rounded-full bg-magenta px-4 text-xs font-semibold text-white">Add questions</button></div>}
    <Card className="mb-5 p-5 sm:p-6"><Eyebrow>A little space to wonder</Eyebrow><h2 className="mt-2 font-display text-2xl">Ask a question</h2><p className="mt-2 text-sm leading-6 text-muted">Explore a theme in your chart. Nothing is used until you press send in chat.</p><Button onClick={() => navigate('chat')} className="mt-4">Open chat <span aria-hidden="true">→</span></Button><div className="mt-5 flex flex-wrap gap-2">{SUGGESTIONS.map(question => <button key={question} onClick={() => navigate('chat', { prefill: question })} className="min-h-11 rounded-full border border-line bg-void-soft px-4 py-2 text-left text-xs text-ink-soft transition hover:border-magenta/50 hover:text-white">{question} <span className="text-magenta-bright">↗</span></button>)}</div></Card>
    {chartLoading ? <Card className="mb-5 h-36 animate-pulse p-5" aria-label="Loading chart summary"><div className="h-full"/></Card> : chart ? <button onClick={() => navigate('chart')} className="mb-5 block w-full text-left"><Card className="overflow-hidden p-5 transition hover:border-magenta/40 sm:p-6"><div className="flex items-start justify-between gap-3"><div><Eyebrow>Your birth chart</Eyebrow><h2 className="mt-1 font-display text-xl">My Chart</h2></div><span className="text-sm text-[#ef91c4]">View full chart →</span></div><div className="mt-4 grid min-w-0 gap-4 sm:grid-cols-[minmax(0,190px)_minmax(0,1fr)] sm:items-center"><ChartDiagram facts={chart.facts} size="small" language={language} showLabels={false} className="mx-auto w-full max-w-[190px]" onFactSelect={fact=>setChartMeaningFacts([fact])}/><div className="grid min-w-0 gap-3 text-sm"><p className="rounded-xl border border-line bg-void-soft p-3"><span className="block text-[10px] uppercase tracking-wider text-muted">Lagna</span><strong className="mt-1 block">{chart.lagna_sign}</strong></p><p className="rounded-xl border border-line bg-void-soft p-3"><span className="block text-[10px] uppercase tracking-wider text-muted">Moon sign</span><strong className="mt-1 block">{moonSign || '—'}</strong></p><p className="rounded-xl border border-line bg-void-soft p-3"><span className="block text-[10px] uppercase tracking-wider text-muted">Current dasha</span><strong className="mt-1 block truncate">{currentDasha}</strong></p></div></div></Card></button> : <Card className="mb-5 p-5"><p role="alert" className="text-sm text-muted">{chartError}</p><button onClick={() => void loadChart()} className="mt-3 min-h-11 rounded-full border border-line px-4 text-xs text-ink-soft">Retry chart</button></Card>}
    {dailyInsightLoading ? <Card aria-label="Loading today’s insight" className="mb-5 h-36 animate-pulse p-5"><div className="h-full rounded-xl bg-void-soft"/></Card> : dailyInsight ? <Card ref={dailyInsightRef} className="mb-5 overflow-hidden border-star/20 bg-gradient-to-br from-[#211623] to-panel p-5 sm:p-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><Eyebrow>Today for you</Eyebrow><h2 className="mt-1 font-display text-xl">A note for today</h2></div><span className="rounded-full border border-star/20 bg-[#211a14] px-3 py-1.5 text-[11px] text-star">{dailyInsight.streak_days} day{dailyInsight.streak_days === 1 ? '' : 's'} in a row</span></div><div className="mt-3 text-sm leading-6 text-ink-soft"><ReadingAnswer text={dailyInsight.answer_text} facts={dailyInsight.facts_used}/></div><button type="button" onClick={() => setChartMeaningFacts(dailyInsight.facts_used)} className="mt-3 inline-flex min-h-10 items-center gap-2 rounded-full border border-line bg-panel/80 px-4 text-xs font-medium text-ink-soft hover:border-magenta/40 hover:text-white"><span aria-hidden="true">✧</span> See chart facts</button></Card> : <Card className="mb-5 border-line p-5"><div className="flex items-start justify-between gap-3"><div><Eyebrow>Today for you</Eyebrow><h2 className="mt-1 font-display text-lg">Your daily note</h2><p role={dailyInsightError ? 'alert' : undefined} className="mt-2 text-sm text-muted">{dailyInsightError || 'Your chart note is not ready yet.'}</p></div><button type="button" onClick={() => void loadDailyInsight()} className="min-h-10 shrink-0 rounded-full border border-line px-4 text-xs text-ink-soft hover:border-magenta/40">Try again</button></div></Card>}
    {historyError && <div role="alert" className="mb-5 rounded-xl border border-danger/20 bg-danger/10 p-3 text-sm text-danger">{historyError} <button onClick={() => void loadHistory()} className="ml-2 underline">Retry</button></div>}
    {!loadingHistory && lastEntry && <button onClick={() => navigate('chat', { focusQuestionId: lastEntry.id })} className="mb-5 block w-full text-left"><Card className="p-5 transition hover:border-magenta/40"><Eyebrow>Pick up where you left off</Eyebrow><h2 className="mt-1 font-display text-xl">Continue your conversation</h2><p className="mt-3 line-clamp-1 text-sm text-ink-soft">{lastEntry.question_text}</p><p className="mt-1 line-clamp-1 text-xs text-muted">{lastEntry.answer_text || (lastEntry.status === 'draft' ? 'Saved until you add questions.' : 'Your answer is still being prepared.')}</p></Card></button>}
    {!loadingHistory && !hasHistory && !historyError && <Card className="mb-5 p-5"><Eyebrow>A fresh beginning</Eyebrow><h2 className="mt-1 font-display text-xl">Your conversations will live here.</h2><p className="mt-2 text-sm text-muted">Ask your first question whenever you’re ready.</p></Card>}
    <Card className="mb-5 p-5"><div className="flex flex-wrap items-center justify-between gap-4"><div><Eyebrow>Language</Eyebrow><h2 className="mt-1 font-display text-lg">Choose how to explore</h2></div><div role="group" aria-label="Language" className="flex rounded-full border border-line bg-void-soft p-1">{['English', 'Hindi'].map(option => <button key={option} aria-pressed={language === option} onClick={() => changeLanguage(option)} className={`min-h-11 rounded-full px-4 text-xs ${language === option ? 'bg-magenta text-white' : 'text-muted'}`}>{option}</button>)}</div></div></Card>
    <Card className="p-5"><Eyebrow>How Melooha works</Eyebrow><p className="mt-2 max-w-2xl text-sm leading-6 text-muted">Answers are shaped from facts calculated from your own birth chart. You can open <strong className="font-medium text-ink-soft">See chart facts</strong> under any answer to read what it used.</p></Card>
  </> : route === 'chart' ? <>
    <div className="mb-5"><Eyebrow>Free · always available</Eyebrow><h1 className="mt-1 font-display text-3xl">My Chart</h1><p className="mt-2 text-sm text-muted">Your Vedic birth chart, calculated with Lahiri sidereal and whole-sign houses.</p></div>
    {chartLoading ? <LoadingCards/> : chart ? <><Card className="mb-5 overflow-hidden p-5 sm:p-6"><div className="flex flex-wrap items-end justify-between gap-3"><div><Eyebrow>Lagna / Ascendant</Eyebrow><h2 className="mt-1 font-display text-3xl">{chart.lagna_sign}</h2><ListenButton className="mt-2" language={language} text={`Lagna ${chart.lagna_sign}. ${chart.planets.map(item => `${item.name} in house ${item.house}, ${item.sign}${item.retrograde ? ", retrograde" : ""}`).join(". ")}. Current dasha: ${chart.current_mahadasha.lord}, ${chart.current_antardasha.lord}, ${chart.current_pratyantardasha.lord}.`}/></div><p className="text-xs text-muted">{profile.birth_date} · {profile.birth_time_unknown ? 'Birth time unknown' : profile.birth_time.slice(0, 5)} · {profile.location}</p></div><div className="mt-5 grid min-w-0 gap-4 md:grid-cols-[minmax(0,1fr)_230px] md:items-center"><ChartDiagram facts={chart.facts} size="large" language={language} layout={profile.chart_style || 'north'} className="mx-auto w-full max-w-[460px]" onFactSelect={fact=>setChartMeaningFacts([fact])}/><div className="min-w-0 space-y-4"><fieldset className="rounded-xl border border-line bg-void-soft p-3"><legend className="px-1 text-xs text-muted">Chart layout</legend><div className="flex gap-2">{(['north','south'] as const).map(style=><button type="button" key={style} aria-pressed={(profile.chart_style || 'north')===style} onClick={async()=>{const previous=profile;const next={...profile,chart_style:style};setProfile(next);onProfileChange(next);try{const saved=await api<AccountProfile>('/profile',{method:'POST',body:JSON.stringify({...next,chart_style:style})});setProfile(saved);onProfileChange(saved);}catch{setProfile(previous);onProfileChange(previous);}}} className={`min-h-10 flex-1 rounded-full px-3 text-xs capitalize ${(profile.chart_style || 'north')===style?'bg-magenta text-white':'border border-line text-muted'}`}>{style} Indian</button>)}</div></fieldset><ShareChartButton facts={chart.facts} firstName={profile.display_name?.split(/\s+/)[0] || 'My'} birthDetails={[profile.birth_date,profile.birth_time_unknown?'Birth time unknown':profile.birth_time,profile.location]} language={language}/></div></div></Card><Card className="mb-5 overflow-hidden"><div className="border-b border-line p-5"><Eyebrow>Nine planets</Eyebrow><h2 className="mt-1 font-display text-xl">Planet positions</h2></div><div className="overflow-x-auto"><table className="w-full min-w-[540px] text-left text-sm"><thead className="bg-void-soft text-[10px] uppercase tracking-wider text-muted"><tr><th className="px-4 py-3">Planet</th><th className="px-4 py-3">Sign</th><th className="px-4 py-3">House</th><th className="px-4 py-3">Motion</th><th className="px-4 py-3">Nakshatra</th></tr></thead><tbody>{chart.planets.map(planet => <tr key={planet.name} className="border-t border-line-soft"><td className="px-4 py-3 font-medium">{planet.name}</td><td className="px-4 py-3">{planet.sign}</td><td className="px-4 py-3">{planet.house}</td><td className="px-4 py-3">{planet.retrograde ? 'Retrograde' : 'Direct'}</td><td className="px-4 py-3">{planet.nakshatra}</td></tr>)}</tbody></table></div></Card><Card className="mb-5 p-5"><Eyebrow>Current dasha periods</Eyebrow><div className="mt-4 grid gap-3 sm:grid-cols-3">{[['Mahadasha', chart.current_mahadasha], ['Antardasha', chart.current_antardasha], ['Pratyantardasha', chart.current_pratyantardasha]].map(([label, period]) => { const data = period as Period; return <div key={label as string} className="rounded-xl border border-line bg-void-soft p-4"><p className="text-[10px] uppercase tracking-wider text-muted">{label as string}</p><p className="mt-1 font-display text-lg">{data.lord}</p><p className="mt-2 text-xs text-ink-soft">{data.start_date} – {data.end_date}</p></div>; })}</div></Card><FactPanel facts={chart.facts}/></> : <Card className="p-5"><p role="alert" className="text-sm text-muted">{chartError}</p><Button variant="secondary" onClick={() => void loadChart()} className="mt-3">Retry chart</Button></Card>}
  </> : route === 'history' ? <>
    <div className="mb-5"><Eyebrow>Your conversations</Eyebrow><h1 className="mt-1 font-display text-3xl">History</h1><p className="mt-2 text-sm text-muted">Open any question to return to it in your chat thread.</p></div>
    {historyError && <div role="alert" className="mb-4 rounded-xl border border-danger/20 bg-danger/10 p-3 text-sm text-danger">{historyError} <button onClick={() => void loadHistory()} className="ml-2 underline">Retry</button></div>}
    {loadingHistory ? <LoadingCards/> : history.length ? <div className="space-y-3">{history.map(entry => <button key={entry.id} onClick={() => navigate('chat', { focusQuestionId: entry.id })} className="block w-full rounded-2xl border border-line bg-panel p-4 text-left transition hover:border-magenta/40"><div className="flex items-center justify-between gap-3"><span className="text-[11px] text-muted">{new Date(entry.created_at).toLocaleDateString()}</span><span className="rounded-full bg-panel-raised px-2.5 py-1 text-[10px] text-ink-soft">{entry.status === 'answered' ? 'Answered' : entry.status === 'draft' ? 'Saved' : 'In progress'}</span></div><p className="mt-2 font-display text-lg leading-6">{entry.question_text}</p><p className="mt-2 line-clamp-1 text-xs leading-5 text-muted">{entry.answer_text || (entry.status === 'draft' ? 'Waiting for questions to be added.' : 'Open this conversation to continue.')}</p></button>)}{hasMoreHistory && <Button variant="secondary" disabled={loadingMore} onClick={() => void loadOlderHistory()} className="w-full">{loadingMore ? 'Loading…' : 'Load older conversations'}</Button>}</div> : <EmptyState title="No conversations yet">Your past questions and answers will appear here.</EmptyState>}
  </> : <>
    <div className="mb-5"><Eyebrow>Your account</Eyebrow><h1 className="mt-1 font-display text-3xl">Profile</h1></div>
    <Card className="mb-5 p-5"><div className="flex items-start justify-between gap-3"><div><Eyebrow>Your details</Eyebrow><h2 className="mt-1 font-display text-xl">{profile.display_name || 'Your chart profile'}</h2><p className="mt-2 text-sm text-muted">{profile.birth_date} · {profile.birth_time_unknown ? 'Birth time unknown' : profile.birth_time.slice(0, 5)} · {profile.location}</p></div><Button variant="secondary" onClick={() => { setEditName(profile.display_name || ''); setEditDate(profile.birth_date); setEditTime(profile.birth_time.slice(0, 5)); setEditUnknownTime(profile.birth_time_unknown); setEditLocation(profile.location); setEditTimezone(profile.timezone); setEditingProfile(value => !value); }} className="min-h-11 px-4 text-xs">{editingProfile ? 'Cancel' : 'Edit'}</Button></div>
      {editingProfile && <form onSubmit={saveProfile} className="mt-5 grid gap-4 sm:grid-cols-2"><Field label="Name"><input required className={inputClass} value={editName} onChange={event => setEditName(event.target.value)}/></Field><Field label="Birth place"><input required className={inputClass} value={editLocation} onChange={event => setEditLocation(event.target.value)}/></Field><Field label="Birth date"><input required type="date" className={inputClass} value={editDate} onChange={event => setEditDate(event.target.value)}/></Field><Field label="Birth time"><input type="time" disabled={editUnknownTime} required={!editUnknownTime} className={inputClass} value={editUnknownTime ? '' : editTime} onChange={event => setEditTime(event.target.value)}/></Field><Field label="Timezone"><input required className={inputClass} value={editTimezone} onChange={event => setEditTimezone(event.target.value)}/></Field><label className="flex min-h-11 items-center gap-3 text-sm text-ink-soft"><input type="checkbox" checked={editUnknownTime} onChange={event => setEditUnknownTime(event.target.checked)} className="accent-[#c71c76]"/>I don’t know my exact birth time</label>{profileError && <p role="alert" className="text-sm text-danger sm:col-span-2">{profileError}</p>}<Button type="submit" disabled={profileSaving} className="sm:col-span-2">{profileSaving ? 'Saving…' : 'Save birth details'}</Button></form>}
    </Card>
    <Card className="mb-5 p-5"><div className="flex flex-wrap items-center justify-between gap-4"><div><Eyebrow>Language</Eyebrow><p className="mt-1 text-sm text-ink-soft">Preferred language</p></div><div role="group" aria-label="Language" className="flex rounded-full border border-line bg-void-soft p-1">{['English', 'Hindi'].map(option => <button key={option} aria-pressed={language === option} onClick={() => changeLanguage(option)} className={`min-h-11 rounded-full px-4 text-xs ${language === option ? 'bg-magenta text-white' : 'text-muted'}`}>{option}</button>)}</div></div></Card>
    <Card className="mb-5 p-5"><div className="flex items-center justify-between gap-3"><div><Eyebrow>Questions left</Eyebrow><p className="mt-1 text-2xl font-semibold">{walletLoading ? '…' : balance}</p></div><Button variant="secondary" onClick={() => navigate('chat', { addQuestions: true })}>Add questions</Button></div></Card>
    {process.env.NODE_ENV === 'development' && <Card className="mb-5 p-5"><Eyebrow>Development</Eyebrow><Link href="/style" className="mt-2 inline-flex min-h-11 items-center text-sm text-[#ef91c4] underline">Open style guide →</Link></Card>}
    <Button variant="danger" onClick={onLogout} className="w-full">Log out</Button>
  </>;

  if (route === 'chat') return <><ChatApp profile={profile} chartFacts={chart?.facts || profile.chart_facts} language={language} balance={balance} onBalance={setBalance} onLogout={onLogout} initialQuestion={prefill} focusQuestionId={focusQuestionId} openAddQuestions={openAddQuestions} onKeyboardChange={setKeyboardOpen} onNavigate={next => navigate(next)}/><Navigation route={route} onNavigate={next => navigate(next)} hiddenOnMobile={keyboardOpen}/></>;

  return <div className="min-h-screen md:pl-64"><Navigation route={route} onNavigate={next => navigate(next)}/><header className="sticky top-0 z-20 border-b border-line/70 bg-[#0b090e]/90 px-4 py-3 backdrop-blur-md sm:px-8 md:px-10"><div className="mx-auto flex max-w-5xl items-center justify-between"><div className="flex items-center gap-2 md:hidden"><BrandMark small/><span className="font-display">Meloohā</span></div><p className="hidden font-display text-xl md:block">{headerTitle}</p><button onClick={onLogout} className="min-h-11 rounded-full px-3 text-xs text-muted hover:text-ink">Log out</button></div></header><main className="mx-auto max-w-5xl px-4 pb-28 pt-6 sm:px-8 md:px-10 md:pb-12">{workspaceError && <div role="alert" className="mb-4 rounded-xl border border-danger/20 bg-danger/10 p-3 text-sm text-danger">{workspaceError} <button onClick={() => void refresh()} className="ml-2 underline">Retry</button></div>}{route === 'home' && (walletLoading || loadingHistory) ? <LoadingCards/>  : content}{chartMeaningFacts && <FactsSheet facts={chartMeaningFacts} language={language} onClose={()=>setChartMeaningFacts(null)}/>}</main></div>;
}
