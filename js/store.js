/**
 * État applicatif + persistance locale (localStorage).
 * En production, ces données vivent côté back-end ; ce store sert de cache et de mode démo.
 */
import { CONFIG } from "./config.js";

const KEY = "tickmark.v1";
let state = { sessions: {}, outbox: [] };

try {
  const raw = localStorage.getItem(KEY);
  if (raw) state = { sessions: {}, outbox: [], ...JSON.parse(raw) };
} catch { /* navigation privée / stockage indisponible : on reste en mémoire */ }

const listeners = new Set();
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }

export function persist() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* quota / privé */ }
  listeners.forEach((fn) => fn());
}

export const userName = () => `${CONFIG.USER.firstName} ${CONFIG.USER.lastName}`;

export function uid(prefix) {
  const r = crypto.getRandomValues(new Uint32Array(2));
  return `${prefix}_${r[0].toString(36)}${r[1].toString(36)}`.slice(0, 16);
}

export function getSession(id) { return state.sessions[id] || null; }
export function sessionsFor(clientId) {
  return Object.values(state.sessions).filter((s) => s.clientId === clientId).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}
export function allSessions() { return Object.values(state.sessions); }

export function createSession(data) {
  const s = { id: uid("pt"), createdAt: new Date().toISOString(), createdBy: userName(), status: "analysing", audit: [], ...data };
  state.sessions[s.id] = s;
  log(s, "Pointage créé", `${data.files.before.name} ↔ ${data.files.after.name}`);
  return s;
}

export function log(session, action, detail = "", by = userName()) {
  session.audit.push({ at: new Date().toISOString(), by, action, detail });
  persist();
}

export function deleteSession(id) { delete state.sessions[id]; state.outbox = state.outbox.filter((r) => r.sessionId !== id); persist(); }

export function addReport(report) { state.outbox.unshift(report); persist(); }
export function reportsFor(clientId) { return state.outbox.filter((r) => !clientId || r.clientId === clientId); }
export function getReport(id) { return state.outbox.find((r) => r.id === id) || null; }

export function resetAll() { state = { sessions: {}, outbox: [] }; persist(); }
