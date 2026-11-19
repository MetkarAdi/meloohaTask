const RECORDER_MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
  'audio/ogg',
];

export function selectRecorderMimeType(isTypeSupported, candidates = RECORDER_MIME_CANDIDATES) {
  if (typeof isTypeSupported !== 'function') return '';
  return candidates.find(type => {
    try { return isTypeSupported(type); } catch { return false; }
  }) || '';
}

export function capTranscript(text, limit = 250) {
  const cleaned = String(text || '').replace(/\0/g, '').replace(/\s+/g, ' ').trim();
  return { text: cleaned.slice(0, limit), truncated: cleaned.length > limit };
}

export function cleanSpeechText(text) {
  return String(text || '')
    .replace(/\[\[([^\]|]+)\|M\d{3}\]\]/gi, '$1')
    .replace(/\[[FM]\d{3}\]/gi, '')
    .replace(/[`*_#>~]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function splitSpeechText(text, maxLength = 220) {
  const clean = cleanSpeechText(text);
  if (!clean) return [];
  const sentences = clean.match(/[^.!?।]+[.!?।]?/g) || [clean];
  const chunks = [];
  let current = '';
  for (const sentence of sentences.map(value => value.trim()).filter(Boolean)) {
    const pieces = sentence.length <= maxLength ? [sentence] : sentence.split(/\s+/);
    for (const piece of pieces) {
      if (piece.length > maxLength) {
        if (current) chunks.push(current);
        current = '';
        for (let index = 0; index < piece.length; index += maxLength) chunks.push(piece.slice(index, index + maxLength));
      } else if (!current) current = piece;
      else if (`${current} ${piece}`.length <= maxLength) current += ` ${piece}`;
      else { chunks.push(current); current = piece; }
    }
  }
  if (current) chunks.push(current);
  return chunks;
}

export function speechLangFor(language) {
  return String(language).toLowerCase().startsWith('hi') ? 'hi-IN' : 'en-IN';
}
