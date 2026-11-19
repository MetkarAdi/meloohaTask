'use client';

import { forwardRef, useEffect, useState } from 'react';
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react';
import { cleanSpeechText, speechLangFor, splitSpeechText } from './speech-tools.mjs';

export function BrandMark({ small = false }: { small?: boolean }) {
  return <span className={`grid shrink-0 place-items-center rounded-full border border-magenta/30 bg-magenta-wash text-magenta-bright shadow-[0_0_30px_#c71c7620] ${small ? 'size-9 text-lg' : 'size-11 text-xl'}`} aria-hidden="true">✳</span>;
}

export type TypingStage = 'dots' | 'waking' | 'waiting';
export function TypingIndicator({ stage = 'dots' }: { stage?: TypingStage }) {
  return <div className="rounded-2xl rounded-tl-md border border-line bg-[#151119] px-4 py-3.5"><div className="flex h-3 items-center gap-1.5" aria-label="Melooha is typing"><i className="typing-dot"/><i className="typing-dot [animation-delay:180ms]"/><i className="typing-dot [animation-delay:360ms]"/></div>{stage === 'waking' && <p className="mt-2 text-xs text-muted">Waking up the stars… this can take a little longer sometimes.</p>}{stage === 'waiting' && <p className="mt-2 text-xs text-muted">Still working on it, thanks for waiting.</p>}</div>;
}

export function Eyebrow({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <p className={`text-caption font-semibold uppercase tracking-[.2em] text-star ${className}`}>{children}</p>;
}

export const Card = forwardRef<HTMLElement, HTMLAttributes<HTMLElement> & { children: ReactNode }>(function Card({ children, className = '', ...props }, ref) {
  return <section ref={ref} className={`rounded-card border border-line bg-panel/90 shadow-[0_20px_80px_-52px_#e52a9150] backdrop-blur-sm ${className}`} {...props}>{children}</section>;
});

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'quiet' | 'danger' };
export function Button({ variant = 'primary', className = '', type = 'button', ...props }: ButtonProps) {
  const styles = {
    primary: 'border border-magenta-bright/30 bg-magenta text-white shadow-[0_8px_30px_-12px_#e52a9170] hover:bg-magenta-bright',
    secondary: 'border border-line bg-panel-raised text-ink hover:border-magenta/50 hover:bg-panel-hover',
    quiet: 'border border-transparent bg-transparent text-muted hover:bg-panel-hover hover:text-ink',
    danger: 'border border-danger/20 bg-danger/10 text-danger hover:bg-danger/15',
  };
  return <button type={type} className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-full px-5 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-45 ${styles[variant]} ${className}`} {...props} />;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="block text-sm font-medium text-ink-soft"><span className="mb-2 block">{label}</span>{children}{hint && <span className="mt-2 block text-xs leading-5 text-muted">{hint}</span>}</label>;
}

export const inputClass = 'min-h-12 w-full rounded-xl border border-line bg-void-soft px-4 text-sm text-ink placeholder:text-muted-dark outline-none transition focus:border-magenta-bright focus:ring-2 focus:ring-magenta/15';

export function QuestionBalance({ balance, onAdd }: { balance: number; onAdd: () => void }) {
  const width = `${Math.min(100, Math.max(8, balance * 20))}%`;
  return <div className="rounded-2xl border border-line bg-panel p-4">
    <div className="mb-3 flex items-center justify-between gap-3"><div><p className="text-xs text-muted">QUESTIONS LEFT</p><p className="mt-1 text-xl font-semibold text-ink">{balance}</p></div><Button onClick={onAdd} variant="secondary" className="min-h-10 px-4 text-xs">＋ Add questions</Button></div>
    <div className="h-1.5 overflow-hidden rounded-full bg-void"><div className="h-full rounded-full bg-gradient-to-r from-magenta-dark to-magenta-bright transition-[width] duration-500" style={{ width }} /></div>
  </div>;
}

export function FactPanel({ facts, className = '' }: { facts: string[]; className?: string }) {
  return <section id="answer-facts" className={`scroll-mt-24 rounded-2xl border border-magenta/25 bg-[#160d17] p-5 ${className}`} aria-label="Facts behind this answer">
    <div className="flex items-start gap-3"><span className="grid size-9 shrink-0 place-items-center rounded-xl bg-magenta-wash text-magenta-bright" aria-hidden="true">✧</span><div><Eyebrow>Facts behind this answer</Eyebrow><p className="mt-1 text-xs leading-5 text-muted">Verified chart details used to ground this reading.</p></div></div>
    {facts.length ? <ul className="mt-4 space-y-2">{facts.map((fact, index) => {
      const separator = fact.indexOf(':');
      const id = separator > -1 ? fact.slice(0, separator).trim() : `F${String(index + 1).padStart(3, '0')}`;
      const text = separator > -1 ? fact.slice(separator + 1).trim() : fact;
      return <li key={`${id}-${index}`} className="flex items-start gap-3 rounded-xl border border-line-soft bg-void/60 px-3 py-3 text-sm leading-6"><span className="mt-0.5 shrink-0 rounded-md bg-[#21121e] px-2 py-0.5 font-mono text-[11px] font-bold text-[#f38ac4]">{id}</span><span className="text-ink-soft">{text}</span></li>;
    })}</ul> : <p className="mt-4 rounded-xl border border-dashed border-line px-4 py-5 text-sm text-muted">Facts appear here with the completed reading.</p>}
  </section>;
}

export function EmptyState({ icon = '✦', title, children }: { icon?: string; title: string; children: ReactNode }) {
  return <div className="rounded-2xl border border-dashed border-line bg-panel/60 px-6 py-10 text-center"><span className="mx-auto grid size-12 place-items-center rounded-2xl bg-magenta-wash text-xl text-magenta-bright">{icon}</span><h3 className="mt-4 font-display text-xl text-ink">{title}</h3><p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-muted">{children}</p></div>;
}

export function RatingButtons({ rating, onRate, busy = false }: { rating: number | null; onRate: (value: number) => void; busy?: boolean }) {
  return <div className="flex items-center gap-2" aria-label="Rate this answer">
    <span className="mr-1 text-xs text-muted">Was this helpful?</span>
    <button disabled={busy} aria-label="Helpful" aria-pressed={rating === 1} onClick={() => onRate(1)} className={`grid size-9 place-items-center rounded-full border transition ${rating === 1 ? 'border-success/60 bg-success/10 text-success' : 'border-line text-muted hover:border-success/50 hover:text-success'}`}>↑</button>
    <button disabled={busy} aria-label="Not helpful" aria-pressed={rating === -1} onClick={() => onRate(-1)} className={`grid size-9 place-items-center rounded-full border transition ${rating === -1 ? 'border-danger/60 bg-danger/10 text-danger' : 'border-line text-muted hover:border-danger/50 hover:text-danger'}`}>↓</button>
  </div>;
}

export function ListenButton({ text, language = 'English', className = '' }: { text: string; language?: string; className?: string }) {
  const [speaking, setSpeaking] = useState(false);
  function toggleSpeech() {
    if (typeof window === 'undefined' || !('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') return;
    if (speaking && window.speechSynthesis.speaking) {
      window.speechSynthesis.cancel();
      window.dispatchEvent(new Event('melooha:speech-stop'));
      return;
    }
    const chunks = splitSpeechText(cleanSpeechText(text));
    if (!chunks.length) return;
    window.speechSynthesis.cancel();
    window.dispatchEvent(new Event('melooha:speech-stop'));
    const lang = speechLangFor(language);
    const voice = window.speechSynthesis.getVoices().find(item => item.lang.toLowerCase().startsWith(lang.slice(0, 2)));
    chunks.forEach((chunk, index) => {
      const utterance = new SpeechSynthesisUtterance(chunk);
      utterance.lang = lang;
      if (voice) utterance.voice = voice;
      if (index === chunks.length - 1) {
        utterance.onend = () => setSpeaking(false);
        utterance.onerror = () => setSpeaking(false);
      }
      window.speechSynthesis.speak(utterance);
    });
    setSpeaking(true);
  }
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const stop = () => setSpeaking(false);
    window.addEventListener('melooha:speech-stop', stop);
    return () => window.removeEventListener('melooha:speech-stop', stop);
  }, []);
  return <button type="button" onClick={toggleSpeech} disabled={!cleanSpeechText(text)} aria-label={speaking ? 'Stop listening' : 'Listen'} className={`inline-flex min-h-9 items-center gap-1.5 rounded-full border border-line bg-panel px-3 py-1.5 text-[11px] font-medium text-ink-soft hover:border-magenta/40 hover:text-white disabled:opacity-50 ${className}`}><span aria-hidden="true">{speaking ? '◼' : '🔊'}</span>{speaking ? 'Stop' : 'Listen'}</button>;
}

export function ReadingAnswer({ text, facts, hideCitationIds = true }: { text: string; facts: string[]; hideCitationIds?: boolean }) {
  const [openTerm, setOpenTerm] = useState<string | null>(null);
  const meanings = new Map(facts.flatMap(raw => {
    const match = raw.match(/^\s*(M\d{3})\s*:\s*(.*)$/i);
    return match ? [[match[1].toUpperCase(), match[2]] as const] : [];
  }));
  const marker = /(\[\[[^\]|]+\|M\d{3}\]\]|\[[FM]\d{3}\])/gi;
  return <p className="whitespace-pre-wrap text-[15px] leading-8 text-ink-soft">{text.split(marker).map((part, index) => {
    const term = part.match(/^\[\[([^\]|]+)\|(M\d{3})\]\]$/i);
    if (term) {
      const [, label, idRaw] = term; const id = idRaw.toUpperCase(); const meaning = meanings.get(id);
      if (!meaning) return label;
      const isOpen = openTerm === `${id}-${index}`;
      return <span key={`${id}-${index}`} className="group relative inline-block"><button type="button" aria-expanded={isOpen} aria-label={`${label}: show meaning`} title={meaning} onClick={event => { event.stopPropagation(); setOpenTerm(isOpen ? null : `${id}-${index}`); }} className="cursor-help border-b border-dotted border-[#e989bb] font-medium text-[#f4a8d0] underline decoration-dotted underline-offset-4">{label}</button><span role="tooltip" className={`${isOpen ? 'block' : 'hidden'} absolute bottom-full left-1/2 z-40 mb-2 w-64 -translate-x-1/2 rounded-xl border border-magenta/35 bg-[#1c1320] px-3 py-2 text-left text-xs leading-5 text-ink shadow-xl group-hover:block group-focus-within:block`}>{meaning}{!hideCitationIds && <span className="mt-1 block font-mono text-[10px] text-[#e989bb]">{id}</span>}</span></span>;
    }
    const citation = part.match(/^\[([FM]\d{3})\]$/i);
    if (citation) return null;
    return <span key={index}>{part}</span>;
  })}</p>;
}
