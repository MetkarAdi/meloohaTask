export function canStartSheetDrag(origin) {
  return origin === 'handle' || origin === 'header';
}

export function shouldCloseSheetDrag({ origin, startY, endY, startedAt, endedAt, threshold = 80 }) {
  if (!canStartSheetDrag(origin)) return false;
  const distance = endY - startY;
  if (distance >= threshold) return true;
  const elapsed = Math.max(1, endedAt - startedAt);
  return distance >= 24 && elapsed <= 180 && distance / elapsed >= 0.6;
}
