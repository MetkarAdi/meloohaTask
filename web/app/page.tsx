'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { BrandMark, Button, Card, Eyebrow, Field, inputClass } from './ui';
import { AccountProfile, Workspace } from './workspace';
import { LocationField, PlaceSuggestion } from './location-field';

type Profile = AccountProfile;
type View = 'loading' | 'auth' | 'onboarding' | 'workspace';
type ApiProblem = Error & { status?: number };

function apiProblemStatus(problem: unknown): number | undefined {
  return problem instanceof Error ? (problem as ApiProblem).status : undefined;
}

function apiProblemMessage(problem: unknown, fallback: string): string {
  return problem instanceof Error ? problem.message : fallback;
}

async function api<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, credentials: 'same-origin', headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers } });
  if (!response.ok) {
    const error = Object.assign(new Error('Something went wrong. Please try again.'), { status: response.status });
    if (response.status === 409) error.message = 'An account already uses this email. Try signing in.';
    if (response.status === 401) error.message = 'Email or password did not match.';
    throw error;
  }
  return response.status === 204 ? undefined as T : response.json();
}

export default function Home() {
  const [view, setView] = useState<View>('loading');
  const [profile, setProfile] = useState<Profile | null>(null);
  const [balance, setBalance] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'signup'>('signup');
  const [email, setEmail] = useState(''); const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState(''); const [birthDate, setBirthDate] = useState(''); const [birthTime, setBirthTime] = useState('12:00'); const [unknownTime, setUnknownTime] = useState(false); const [location, setLocation] = useState('');
  const [selectedPlace, setSelectedPlace] = useState<PlaceSuggestion | null>(null);

  const refreshData = useCallback(async () => {
    await api<{ user: { id: number }; question_balance: number }>('/me');
    const wallet = await api<{ balance: number }>('/wallet');
    setBalance(wallet.balance);
    try { setProfile(await api<Profile>('/profile')); setView('workspace'); }
    catch (problem: unknown) { if (apiProblemStatus(problem) === 404) setView('onboarding'); else throw problem; }
  }, []);

  useEffect(() => { refreshData().catch((problem: unknown) => { if (apiProblemStatus(problem) === 401) setView('auth'); else { setError('We couldn’t connect just now. Please refresh and try again.'); setView('auth'); } }); }, [refreshData]);

  async function submitAuth(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { await api(`/auth/${authMode === 'signup' ? 'register' : 'login'}`, { method: 'POST', body: JSON.stringify({ email, password }) }); await refreshData(); window.history.replaceState({ meloohaRoute: 'home' }, '', `${window.location.pathname}${window.location.search}#home`); }
    catch (problem: unknown) { setError(apiProblemMessage(problem, 'We could not sign you in. Please try again.')); }
    finally { setBusy(false); }
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const saved = await api<Profile>('/profile', { method: 'POST', body: JSON.stringify({ display_name: displayName.trim(), birth_date: birthDate, birth_time: unknownTime ? '12:00:00' : `${birthTime}:00`, birth_time_unknown: unknownTime, timezone: 'Asia/Kolkata', location, latitude: selectedPlace?.latitude, longitude: selectedPlace?.longitude, label: 'My birth chart' }) });
      setProfile(saved); await refreshData(); window.history.replaceState({ meloohaRoute: 'home' }, '', `${window.location.pathname}${window.location.search}#home`);
    } catch { setError('We could not save those details. Check them and try again.'); }
    finally { setBusy(false); }
  }

  const logout = useCallback(async () => {
    try { await api('/auth/logout', { method: 'POST' }); } catch { /* The session may already be closed. */ }
    setProfile(null); setView('auth');
  }, []);

  return <main className="relative z-10 min-h-screen">
    {view === 'loading' && <div className="mx-auto grid min-h-screen max-w-md place-items-center px-6"><Card className="w-full p-8 text-center"><BrandMark/><h1 className="mt-4 font-display text-2xl">Finding your place among the stars</h1><p className="mt-2 text-sm text-muted">Loading your chart space…</p><div className="mx-auto mt-5 h-1 w-32 overflow-hidden rounded bg-panel-raised"><div className="h-full w-1/2 animate-pulse rounded bg-magenta-bright"/></div></Card></div>}

    {view === 'auth' && <div className="mx-auto grid min-h-screen max-w-6xl items-center gap-12 px-5 py-12 md:grid-cols-[1.1fr_.9fr] md:px-10"><div className="max-w-2xl"><BrandMark/><Eyebrow className="mt-8">A quieter kind of guidance</Eyebrow><h1 className="mt-4 font-display text-hero leading-[.98] text-ink">Your chart,<br/><span className="text-[#e989bb]">in conversation.</span></h1><p className="mt-6 max-w-lg text-base leading-7 text-muted">Thoughtful Vedic astrology, grounded in your birth chart. A little more room to reflect.</p><div className="mt-9 flex flex-wrap gap-3 text-xs text-ink-soft"><span className="rounded-full border border-line px-4 py-2">✦ Lahiri sidereal</span><span className="rounded-full border border-line px-4 py-2">✧ Chart facts behind each reply</span></div></div>
      <Card className="p-6 sm:p-9"><Eyebrow>Start your chart space</Eyebrow><h2 className="mt-3 font-display text-3xl">{authMode === 'signup' ? 'A little space to wonder.' : 'Welcome back.'}</h2><p className="mt-2 text-sm text-muted">{authMode === 'signup' ? 'Create an account and get one question to begin.' : 'Sign in to continue your conversation.'}</p>{error && <p role="alert" className="mt-5 rounded-xl border border-danger/25 bg-danger/10 p-3 text-sm text-danger">{error}</p>}<form onSubmit={submitAuth} className="mt-7 space-y-5"><Field label="Email"><input className={inputClass} type="email" autoComplete="email" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@example.com"/></Field><Field label="Password" hint="At least 8 characters"><input className={inputClass} type="password" autoComplete={authMode === 'signup' ? 'new-password' : 'current-password'} minLength={8} required value={password} onChange={e=>setPassword(e.target.value)} placeholder="••••••••"/></Field><Button type="submit" disabled={busy} className="w-full">{busy ? 'One moment…' : authMode === 'signup' ? 'Create my account' : 'Sign in'} <span aria-hidden="true">→</span></Button></form><p className="mt-6 text-center text-sm text-muted">{authMode === 'signup' ? 'Already have an account?' : 'New to this space?'} <button onClick={()=>{setAuthMode(authMode === 'signup' ? 'login' : 'signup');setError('');}} className="font-semibold text-[#ef91c4] underline-offset-4 hover:underline">{authMode === 'signup' ? 'Sign in' : 'Create an account'}</button></p><p className="mt-6 text-center text-xs text-muted-dark">Your name and email are never shared as chat context.</p></Card>
    </div>}

    {view === 'onboarding' && <div className="mx-auto grid min-h-screen max-w-6xl items-center gap-10 px-5 py-10 md:grid-cols-[.8fr_1.2fr] md:px-10"><div><BrandMark/><Eyebrow className="mt-8">First, your birth details</Eyebrow><h1 className="mt-4 font-display text-heading leading-tight">Let’s find the sky you were born under.</h1><p className="mt-4 text-sm leading-6 text-muted">We use your birth details to calculate chart facts. You can mark your time unknown if you’re unsure.</p><div className="mt-8 rounded-2xl border border-magenta/20 bg-magenta-wash/50 p-5 text-sm leading-6 text-ink-soft">✧ Your name helps us greet you. Your chart facts guide each answer.</div></div><Card className="p-6 sm:p-8"><div className="mb-6 flex items-center gap-3"><BrandMark small/><div><p className="font-semibold">Your chart profile</p><p className="text-xs text-muted">About two minutes</p></div></div>{error && <p role="alert" className="mb-5 rounded-xl border border-danger/25 bg-danger/10 p-3 text-sm text-danger">{error}</p>}<form onSubmit={saveProfile} className="grid gap-5 sm:grid-cols-2"><Field label="What should we call you?"><input required className={inputClass} value={displayName} onChange={e=>setDisplayName(e.target.value)} placeholder="Your name" autoComplete="given-name"/></Field><LocationField value={location} onChange={value=>{setLocation(value);setSelectedPlace(null);}} onSelect={setSelectedPlace}/><Field label="Birth date"><input required type="date" className={inputClass} value={birthDate} onChange={e=>setBirthDate(e.target.value)}/></Field><Field label="Birth time"><input type="time" disabled={unknownTime} required={!unknownTime} className={`${inputClass} disabled:opacity-45`} value={unknownTime ? '' : birthTime} onChange={e=>setBirthTime(e.target.value)}/></Field><label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-void-soft p-4 text-sm text-ink-soft sm:col-span-2"><input type="checkbox" checked={unknownTime} onChange={e=>setUnknownTime(e.target.checked)} className="mt-1 accent-[#c71c76]"/><span><strong className="font-medium text-ink">I don’t know my exact birth time</strong><span className="mt-1 block text-xs leading-5 text-muted">We’ll use an approximate time. Time-dependent placements may be less precise.</span></span></label><Button disabled={busy} type="submit" className="sm:col-span-2">{busy ? 'Calculating your chart…' : 'Create my chart'} <span>→</span></Button></form></Card></div>}

    {view === 'workspace' && profile && <Workspace profile={profile} balance={balance} onLogout={logout} onProfileChange={setProfile}/>}
  </main>;
}
