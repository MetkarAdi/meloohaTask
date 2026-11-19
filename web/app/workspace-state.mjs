export const APP_ROUTES = ['home', 'chat', 'chart', 'history', 'profile'];

export function routeFromHash(hash) {
  const candidate = String(hash || '').replace(/^#/, '');
  return APP_ROUTES.includes(candidate) ? candidate : 'home';
}

export function isZeroBalance(balance) {
  return Number(balance) <= 0;
}

export function hasConversation(entries) {
  return Array.isArray(entries) && entries.length > 0;
}
