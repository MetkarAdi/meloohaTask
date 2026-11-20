'use client';

import { useMemo, useState } from 'react';
import { houseLabels, parseChartFacts, renderChartDiagramSvg } from './chart-diagram-data.mjs';
import { createShareSvg, svgToPng } from './share-chart.mjs';
import english from './translations/en.json';
import hindi from './translations/hi.json';

type ChartDiagramProps = {
  facts: string[];
  highlightHouses?: number[];
  size?: 'small' | 'large';
  language?: string;
  showLabels?: boolean;
  layout?: 'north' | 'south';
  className?: string;
  onExpand?: () => void;
  onFactSelect?: (fact: string) => void;
};

export function ChartDiagram({ facts, highlightHouses = [], size = 'large', language = 'English', showLabels = true, layout = 'north', className = '', onExpand, onFactSelect }: ChartDiagramProps) {
  const svg = useMemo(() => renderChartDiagramSvg(facts, { highlightHouses, size, language, showLabels, layout }), [facts, highlightHouses, size, language, showLabels, layout]);
  const parsed = useMemo(() => parseChartFacts(facts), [facts]);
  const [selected, setSelected] = useState('');
  const select = (event: React.MouseEvent<HTMLDivElement> | React.KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as Element;
    const planet = target.closest<SVGGElement>('[data-planet]');
    const house = target.closest<SVGGElement>('[data-house]');
    if (planet) {
      event.stopPropagation();
      const name = planet.dataset.planet || '';
      const placement = parsed.planets.find(item => item.name === name);
      const fact = facts.find(value => new RegExp(`^\\s*F\\d{3}\\s*:\\s*${name} in house`, 'i').test(value));
      const translated = (language === 'Hindi' ? hindi : english).planets[name as keyof typeof english.planets];
      const meaning = `${name} · ${language === 'Hindi' ? 'भाव' : 'house'} ${placement?.house ?? ''} (${placement?.sign ?? ''})\n${translated || ''}`;
      const content = [fact, meaning].filter(Boolean).join('\n');
      onFactSelect?.(content);
      if (!onFactSelect) setSelected(content || name);
      return;
    }
    if (house) {
      event.stopPropagation();
      const number = Number(house.dataset.house);
      const name = (houseLabels[language] || houseLabels.English)[number - 1];
      const fact = facts.find(value => new RegExp(`^\\s*F\\d{3}\\s*:\\s*(?:Sign on house ${number}|Ruler of house ${number})`, 'i').test(value));
      const translations = language === 'Hindi' ? hindi : english;
      const meaning = `${language === 'Hindi' ? 'भाव' : 'House'} ${number} · ${name}\n${translations.houseMeanings[number - 1]}`;
      const content = [fact, meaning].filter(Boolean).join('\n');
      onFactSelect?.(content);
      if (!onFactSelect) setSelected(content);
    }
  };
  return <div className={`relative min-w-0 max-w-full ${className}`} onClick={select} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') select(event); }}>
    <div role={onExpand ? 'button' : undefined} tabIndex={onExpand ? 0 : undefined} onClick={event => { if ((event.target as Element).closest('[data-house], [data-planet]')) return; onExpand?.(); }} aria-label={`Open chart diagram. Lagna ${parsed.lagna || 'unknown'}`} className="block h-full w-full max-w-full overflow-hidden rounded-xl" style={{ aspectRatio: '1 / 1' }} dangerouslySetInnerHTML={{ __html: svg }}/>
    {selected && <div role="dialog" aria-label="Chart meaning" className="absolute inset-x-2 bottom-2 z-10 rounded-xl border border-line bg-[#100d13] p-3 text-xs leading-5 text-ink-soft shadow-xl"><button type="button" onClick={() => setSelected('')} aria-label="Close meaning" className="float-right ml-2 text-muted">×</button>{selected}</div>}
  </div>;
}

export function ShareChartButton({ facts, firstName, includeBirthDetails = false, birthDetails, language = 'English', className = '' }: { facts: string[]; firstName: string; includeBirthDetails?: boolean; birthDetails?: string[]; language?: string; className?: string }) {
  const [includeDetails, setIncludeDetails] = useState(includeBirthDetails);
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState('');
  async function share() {
    setSharing(true); setError('');
    try {
      const diagram = renderChartDiagramSvg(facts, { size: 'large', language, showLabels: true });
      const chart = createShareSvg(diagram, { firstName, facts, includeBirthDetails: includeDetails, birthDetails });
      const blob = await svgToPng(chart);
      const file = new File([blob], 'melooha-chart.png', { type: 'image/png' });
      if (navigator.share && navigator.canShare?.({ files: [file] })) await navigator.share({ files: [file], title: 'My Melooha chart' });
      else { const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'melooha-chart.png'; anchor.click(); URL.revokeObjectURL(url); }
      void fetch('/api/events', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event: 'chart_image_shared' }) }).catch(() => {});
    } catch { setError('The chart image could not be created. Please try again.'); }
    finally { setSharing(false); }
  }
  return <div className={className}><label className="mb-2 flex items-center gap-2 text-xs text-muted"><input type="checkbox" checked={includeDetails} onChange={event => setIncludeDetails(event.target.checked)} className="accent-[#c71c76]"/>Include birth details</label><button type="button" onClick={() => void share()} disabled={sharing} className="min-h-10 rounded-full bg-magenta px-4 text-xs font-semibold text-white disabled:opacity-60">{sharing ? 'Preparing chart…' : 'Share chart'}</button>{error && <p role="alert" className="mt-2 text-xs text-danger">{error}</p>}</div>;
}
