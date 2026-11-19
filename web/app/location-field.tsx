'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Field, inputClass } from './ui';

export type PlaceSuggestion = {
  label: string;
  name: string;
  latitude: number;
  longitude: number;
  admin1?: string | null;
  country?: string | null;
};

export function LocationField({
  value,
  onChange,
  onSelect,
}: {
  value: string;
  onChange: (value: string) => void;
  onSelect: (place: PlaceSuggestion) => void;
}) {
  const listId = useId();
  const wrapperRef = useRef<HTMLDivElement>(null);
  const selectedValueRef = useRef('');
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const query = value.trim();
    if (selectedValueRef.current === query) return;
    if (query.length < 2) {
      setSuggestions([]);
      setOpen(false);
      setLoading(false);
      setFailed(false);
      return;
    }

    const controller = new AbortController();
    setLoading(true);
    setFailed(false);
    const timer = window.setTimeout(() => {
      fetch(`/api/locations/suggest?q=${encodeURIComponent(query)}`, {
        credentials: 'same-origin',
        signal: controller.signal,
      }).then(async response => {
        if (!response.ok) throw new Error('Suggestions are unavailable');
        return response.json() as Promise<PlaceSuggestion[]>;
      }).then(found => {
        setSuggestions(found);
        setOpen(document.activeElement === wrapperRef.current?.querySelector('input'));
      }).catch(error => {
        if (error instanceof Error && error.name === 'AbortError') return;
        setSuggestions([]);
        setFailed(true);
        setOpen(document.activeElement === wrapperRef.current?.querySelector('input'));
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 250);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [value]);

  useEffect(() => {
    function dismiss(event: MouseEvent | TouchEvent) {
      if (event.target instanceof Node && !wrapperRef.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener('mousedown', dismiss);
    document.addEventListener('touchstart', dismiss);
    return () => {
      document.removeEventListener('mousedown', dismiss);
      document.removeEventListener('touchstart', dismiss);
    };
  }, []);

  return <div ref={wrapperRef} className="relative">
    <Field label="Birth place" hint="Start typing a city or place, then choose a suggestion. You can also enter it manually.">
      <input
        required
        className={inputClass}
        value={value}
        onFocus={() => { if (value.trim().length >= 2) setOpen(true); }}
        onChange={event => { selectedValueRef.current = ''; onChange(event.target.value); setOpen(true); }}
        onKeyDown={event => {
          if (event.key === 'Escape') setOpen(false);
          if (event.key === 'ArrowDown' && suggestions.length) {
            event.preventDefault();
            wrapperRef.current?.querySelector<HTMLButtonElement>('[role="option"]')?.focus();
          }
        }}
        placeholder="Start typing a place…"
        autoComplete="off"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listId}
        aria-busy={loading}
      />
    </Field>
    {open && (loading || failed || suggestions.length > 0 || value.trim().length >= 2) && <div className="absolute inset-x-0 top-full z-30 mt-1 overflow-hidden rounded-xl border border-line bg-[#151119] shadow-xl">
      {loading && <p role="status" className="px-4 py-3 text-xs text-muted">Searching places…</p>}
      {!loading && failed && <p role="status" className="px-4 py-3 text-xs text-muted">Suggestions are unavailable right now. You can still enter the place manually.</p>}
      {!loading && !failed && suggestions.length === 0 && <p role="status" className="px-4 py-3 text-xs text-muted">No matching places found. You can still enter the place manually.</p>}
      {!loading && suggestions.length > 0 && <ul id={listId} role="listbox" aria-label="Matching birth places" className="max-h-56 overflow-y-auto py-1">
        {suggestions.map((place, index) => <li key={`${place.label}-${place.latitude}-${index}`}>
          <button type="button" role="option" aria-selected="false" onClick={() => { selectedValueRef.current = place.label.trim(); onChange(place.label); onSelect(place); setSuggestions([]); setOpen(false); }} onKeyDown={event => { if (event.key === 'Escape') { setOpen(false); wrapperRef.current?.querySelector('input')?.focus(); } }} className="min-h-12 w-full px-4 py-2 text-left text-sm text-ink-soft hover:bg-magenta/15 focus:bg-magenta/15 focus:outline-none">
            <span className="block font-medium text-ink">{place.name}</span>
            {place.label !== place.name && <span className="mt-0.5 block text-xs text-muted">{place.label.slice(place.name.length).replace(/^,\s*/, '')}</span>}
          </button>
        </li>)}
      </ul>}
    </div>}
  </div>;
}
