// Thin fetch wrapper. Token lives in sessionStorage (cleared when the tab closes). See docs/SECURITY.md for the XSS trade-off.
const KEY = "sla_token";
export const session = {
  get token() { return sessionStorage.getItem(KEY); },
  set token(v) { v ? sessionStorage.setItem(KEY, v) : sessionStorage.removeItem(KEY); },
  user: null,
};

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.error?.message || `Request failed (${status})`);
    this.status = status; this.code = body?.error?.code; this.details = body?.error?.details; this.requestId = body?.error?.request_id;
  }
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

export async function api(path, { method = "GET", body, form, raw } = {}) {
  const headers = {};
  if (session.token) headers.Authorization = `Bearer ${session.token}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const res = await fetch(`/api/v1${path}`, { method, headers, body: payload });
  if (raw && res.ok) return res;
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON error */ }
  if (res.status === 401 && path !== "/auth/login") onUnauthorized();
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const qs = (params) => {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") p.set(k, v); });
  const s = p.toString();
  return s ? `?${s}` : "";
};
