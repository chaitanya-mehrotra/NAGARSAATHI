const env = import.meta.env || {};
export const base = (env.VITE_API_BASE_URL || (env.DEV ? 'http://127.0.0.1:8002' : '/api')).replace(/\/$/, '');
const TOKEN = 'nagarsaathi_token';
const USER = 'nagarsaathi_user';
export const SESSION_EVENT = 'nagarsaathi-session';
let revision = 0;
export function getStoredToken() { return localStorage.getItem(TOKEN) || ''; }
export function clearSession() {
  revision++;
  localStorage.removeItem(TOKEN);
  localStorage.removeItem(USER);
  window.dispatchEvent(new Event(SESSION_EVENT));
}
export function setSession(token) {
  revision++;
  localStorage.removeItem(USER); // Never trust a cached role.
  localStorage.setItem(TOKEN, token);
  window.dispatchEvent(new Event(SESSION_EVENT));
}
export function observeSessions(listener) {
  const storage = event => { if (!event.key || [TOKEN, USER].includes(event.key)) { revision++; listener(); } };
  window.addEventListener('storage', storage);
  window.addEventListener(SESSION_EVENT, listener);
  return () => { window.removeEventListener('storage', storage); window.removeEventListener(SESSION_EVENT, listener); };
}
export async function request(path, options = {}) {
  const token = getStoredToken(), version = revision;
  const response = await fetch(base + path, {
    ...options, headers: { ...options.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (version !== revision || token !== getStoredToken()) throw new DOMException('Session changed', 'AbortError');
  if (response.status === 401 && token) { clearSession(); throw new Error('Your session has expired. Please sign in again.'); }
  if (response.status === 204 && response.ok) return null;
  let data;
  try { data = await response.json(); } catch { throw new Error('The service returned an unreadable response. Please retry.'); }
  if (version !== revision || token !== getStoredToken()) throw new DOMException('Session changed', 'AbortError');
  if (!response.ok) {
    const message = data.error?.message || data.detail;
    throw new Error(typeof message === 'string' ? message : `Request failed (${response.status}). Please retry.`);
  }
  return data;
}
export const identity = signal => request('/auth/me', { signal });
export async function login(email, password, signal) {
  const result = await request('/auth/login', { method: 'POST', signal,
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
  if (!result.access_token) throw new Error('The sign-in response did not contain a session.');
  setSession(result.access_token);
}
export const register = (name, email, password, signal) => request('/auth/register', {
  method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, email, password }),
});
export async function logout() {
  const token = getStoredToken();
  clearSession(); // Clear the screen immediately, including while the network is offline.
  if (token) await fetch(base + '/auth/logout', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
}
export const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
export const submit = (form, key, signal) => {
  const body = new FormData();
  body.append('image', form.file);
  for (const field of ['description', 'latitude', 'longitude', 'issue_type']) body.append(field, String(form[field]));
  return request('/reports', { method: 'POST', body, signal, headers: { 'Idempotency-Key': key } });
};
export async function photoBlob(path, signal) {
  // Only authenticated API paths, never tokens in URLs, arbitrary origins or signed links.
  if (!/^\/(reports|issues)\/[a-zA-Z0-9-]+(?:\/repairs\/[0-9]+)?\/photo$/.test(path)) throw new Error('Invalid photo path');
  const token = getStoredToken(), version = revision;
  const response = await fetch(base + path, { signal, headers: { Authorization: `Bearer ${token}` } });
  if (version !== revision || token !== getStoredToken()) throw new DOMException('Session changed', 'AbortError');
  if (response.status === 401) { clearSession(); throw new Error('Please sign in again.'); }
  if (!response.ok) throw new Error('Photo unavailable. Please retry.');
  const blob = await response.blob();
  if (!blob.type.startsWith('image/')) throw new Error('Photo response is not an image.');
  return blob;
}
