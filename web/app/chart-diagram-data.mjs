const planets = [
  ['Sun', 'Su'], ['Moon', 'Mo'], ['Mars', 'Ma'], ['Mercury', 'Me'],
  ['Jupiter', 'Ju'], ['Venus', 'Ve'], ['Saturn', 'Sa'], ['Rahu', 'Ra'], ['Ketu', 'Ke'],
];
const signs = 'Aries Taurus Gemini Cancer Leo Virgo Libra Scorpio Sagittarius Capricorn Aquarius Pisces'.split(' ');
export const houseLabels = { English: english.houses, Hindi: hindi.houses };
const escapeXml = value => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[char]);

export function parseChartFacts(facts = []) {
  let lagna = '';
  const placements = [];
  for (const raw of facts) {
    const text = String(raw).replace(/^\s*[FＭM]\d{3}\s*:\s*/i, '').trim();
    const asc = text.match(/^Lagna is (\w+)/i);
    if (asc) lagna = signs.find(sign => sign.toLowerCase() === asc[1].toLowerCase()) || asc[1];
    const match = text.match(/^(Sun|Moon|Mars|Mercury|Jupiter|Venus|Saturn|Rahu|Ketu) in house (\d{1,2}) \((Aries|Taurus|Gemini|Cancer|Leo|Virgo|Libra|Scorpio|Sagittarius|Capricorn|Aquarius|Pisces)\)(?:,?\s*(retrograde|direct))?/i);
    if (match) placements.push({ name: planets.find(([name]) => name.toLowerCase() === match[1].toLowerCase())[0], code: planets.find(([name]) => name.toLowerCase() === match[1].toLowerCase())[1], house: Number(match[2]), sign: match[3], retrograde: match[4]?.toLowerCase() === 'retrograde' });
  }
  return { lagna, planets: placements };
}

function houseGeometry(layout) {
  if (layout === 'south') {
    const cells = [[0,0],[1,0],[2,0],[3,0],[3,1],[3,2],[3,3],[2,3],[1,3],[0,3],[0,2],[0,1]];
    return cells.map(([x,y], house) => ({ house: house + 1, points: `${x*100},${y*100} ${(x+1)*100},${y*100} ${(x+1)*100},${(y+1)*100} ${x*100},${(y+1)*100}`, cx: x*100+50, cy:y*100+50 }));
  }
  const coords = [
    [200,82], [100,40], [42,100], [100,200], [42,300], [100,360],
    [200,318], [300,360], [358,300], [300,200], [358,100], [300,40],
  ];
  const polys = [
    '200,0 300,100 200,200 100,100',
    '0,0 200,0 100,100', '0,0 100,100 0,200',
    '0,200 100,100 200,200 100,300',
    '0,200 100,300 0,400', '0,400 100,300 200,400',
    '100,300 200,200 300,300 200,400',
    '200,400 300,300 400,400', '300,300 400,200 400,400',
    '200,200 300,100 400,200 300,300',
    '300,100 400,0 400,200', '200,0 400,0 300,100',
  ];
  return polys.map((points, index) => ({ house:index+1, points, cx:coords[index][0], cy:coords[index][1] }));
}

export function renderChartDiagramSvg(facts, { highlightHouses = [], size = 'large', language = 'English', showLabels = true, layout = 'north' } = {}) {
  const { lagna, planets: placements } = parseChartFacts(facts);
  const labels = houseLabels[language] || houseLabels.English;
  const grouped = new Map(Array.from({length:12}, (_,i) => [i+1, []]));
  for (const placement of placements) if (grouped.has(placement.house)) grouped.get(placement.house).push(placement);
  const descriptions = [`Lagna ${lagna || 'unknown'}`, ...placements.map(item => `${item.name} in house ${item.house}, ${item.sign}${item.retrograde ? ', retrograde' : ''}`)].join('. ') + '.';
  const houses = houseGeometry(layout);
  const strokes = layout === 'south'
    ? '<path d="M100 0V100 M200 0V100 M300 0V100 M0 100H100 M300 100H400 M0 200H100 M300 200H400 M100 300V400 M200 300V400 M300 300V400"/>'
    : '<path d="M200 0L400 200L200 400L0 200Z M0 0L200 200L400 0 M400 400L200 200L0 400"/>';
  const polygons = houses.map(({house,points,cx,cy}) => {
    const active = highlightHouses.includes(house);
    const members = grouped.get(house) || [];
    const visible = members.slice(0, 4);
    const markerStart = cy + (showLabels ? 12 : -2);
    const markers = visible.map((planet, index) => {
      const col = index % 2, row = Math.floor(index / 2);
      const x = cx + (col ? 17 : -17), y = markerStart + row * 19;
      return `<g data-planet="${planet.name}" data-house="${house}" role="button" tabindex="0" aria-label="${escapeXml(planet.name)} in house ${house}, ${escapeXml(planet.sign)}"><rect class="marker-pill" x="${x-15}" y="${y-9}" width="30" height="16" rx="7"/><text x="${x}" y="${y+3}" text-anchor="middle" class="marker">${planet.code}${planet.retrograde ? '<tspan class="retro">℞</tspan>' : ''}</text></g>`;
    }).join('');
    const more = members.length > visible.length ? `<text x="${cx}" y="${markerStart+38}" text-anchor="middle" class="extra">+${members.length-visible.length}</text>` : '';
    return { background: `<polygon data-house="${house}" points="${points}" fill="${active ? '#552544' : '#17121b'}" stroke="${active ? '#e98cbd' : 'none'}" stroke-width="2"/>`, content: `<g data-house="${house}" role="button" tabindex="0" aria-label="House ${house}: ${escapeXml(labels[house-1])}"><text x="${cx}" y="${cy-25}" text-anchor="middle" class="house">${house}</text>${showLabels ? `<text x="${cx}" y="${cy-13}" text-anchor="middle" class="area">${escapeXml(labels[house-1])}</text>` : ''}</g>${markers}${more}` };
  });
  const houseBackgrounds = polygons.map(item => item.background).join('');
  const houseContents = polygons.map(item => item.content).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 400 400" preserveAspectRatio="xMidYMid meet" role="img" aria-labelledby="chart-title chart-desc" data-layout="${layout}" data-size="${size}"><title id="chart-title">Vedic birth chart · Lagna ${escapeXml(lagna || 'unknown')}</title><desc id="chart-desc">${escapeXml(descriptions)}</desc><style>svg{display:block;width:100%;height:100%;max-width:100%;background:#100c13;font-family:Arial,sans-serif}.frame,.lines{fill:none;stroke:#9f7595;stroke-width:2}.house{fill:#e8c5db;font-size:13px;font-weight:700}.area{fill:#aa8eaa;font-size:9px}.marker-pill{fill:#302032;stroke:#c88eb5;stroke-width:1;filter:drop-shadow(0 1px 2px #d39abc88)}.marker{fill:#fff0fa;font-size:10px;font-weight:bold}.retro{fill:#f1a6cf;font-size:8px}.extra{fill:#ed9bca;font-size:10px}</style>${houseBackgrounds}${strokes.replace('<path', '<path class="lines"')}<rect class="frame" x="1" y="1" width="398" height="398"/>${houseContents}</svg>`;
}

export function selectVisibleChartMessages(messages) {
  let lastShown = -Infinity;
  return messages.map((message, index) => {
    const eligible = message.role === 'assistant' && message.state === 'done' && (message.highlightedHouses?.length || 0) > 0;
    const firstReply = eligible && !messages.slice(0, index).some(previous => previous.role === 'assistant' && previous.state === 'done' && previous.questionId);
    const show = Boolean(eligible && (firstReply || index - lastShown >= 5));
    if (show) lastShown = index;
    return show;
  });
}
import english from './translations/en.json' with { type: 'json' };
import hindi from './translations/hi.json' with { type: 'json' };

