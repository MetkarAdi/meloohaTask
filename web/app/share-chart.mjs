import { parseChartFacts } from './chart-diagram-data.mjs';

const esc = text => String(text || '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[char]));
export function createShareSvg(diagramSvg, { firstName, facts, includeBirthDetails = false, birthDetails = [] } = {}) {
  const { lagna } = parseChartFacts(facts);
  const detailText = includeBirthDetails ? birthDetails.filter(Boolean).join(' · ') : '';
  const embedded = diagramSvg.replace(/^<svg[^>]*>/, '<svg x="90" y="220" width="900" height="900" viewBox="0 0 400 400">').replace('</svg>', '</svg>');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1350" viewBox="0 0 1080 1350"><rect width="1080" height="1350" fill="#160c18"/><text x="72" y="100" fill="#f7dfef" font-family="Georgia,serif" font-size="40">${esc(firstName)} · ${esc(lagna)} Lagna</text>${embedded}${detailText ? `<text x="72" y="1170" fill="#bdaabd" font-family="Arial,sans-serif" font-size="22">${esc(detailText)}</text>` : ''}<text x="540" y="1290" text-anchor="middle" fill="#f0a2ce" font-family="Georgia,serif" font-size="34">Meloohā</text></svg>`;
}
export async function svgToPng(svg, { width = 1080, height = 1350 } = {}) {
  const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  try {
    const image = new Image(); image.src = url;
    await image.decode();
    const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
    const context = canvas.getContext('2d'); if (!context) throw new Error('Canvas unavailable');
    context.drawImage(image, 0, 0, width, height);
    return await new Promise((resolve, reject) => canvas.toBlob(result => result ? resolve(result) : reject(new Error('PNG encoding failed')), 'image/png'));
  } finally { URL.revokeObjectURL(url); }
}
