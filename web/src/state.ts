// Tiny global store. React useSyncExternalStore-compatible.

export type BookEntry = {
  id: string;
  title: string;
  author: string;
  status: 'logging' | 'identified' | 'unidentified' | 'needs_appraisal';
  id_confidence: number;
  spine_height_cm: number;
  spine_thickness_cm: number;
  scale_method: string;
  image_url?: string;
  price_label?: string;
  currency?: string;
  processing?: boolean;
};
export type ItemEntry = {
  id: string;
  category: string;
  description: string;
  brand_model: string;
  status: 'logging' | 'priced' | 'range' | 'needs_appraisal';
  appraisal_reason: string;
  image_url?: string;
  price_label?: string;
  processing?: boolean;
};

export type Screen = 'home' | 'sweep' | 'packet';

export type State = {
  screen: Screen;
  country: string;
  currency: string;
  sweepId: string | null;
  books: BookEntry[];
  items: ItemEntry[];
  captureNotes: string[];
  agentUtterance: string;
  revisitHint: string;
  packetJsonUrl: string | null;
  packetHtmlUrl: string | null;
  summary: Record<string, unknown> | null;
};

const listeners = new Set<() => void>();
let state: State = {
  screen: 'home',
  country: 'US',
  currency: 'USD',
  sweepId: null,
  books: [],
  items: [],
  captureNotes: [],
  agentUtterance: '',
  revisitHint: '',
  packetJsonUrl: null,
  packetHtmlUrl: null,
  summary: null,
};

export function getState(): State { return state; }
export function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
export function setState(patch: Partial<State> | ((s: State) => Partial<State>)): void {
  const p = typeof patch === 'function' ? patch(state) : patch;
  state = { ...state, ...p };
  for (const cb of listeners) cb();
}

export function mergeById<T extends { id: string }>(existing: T[], incoming: T[]): T[] {
  if (!incoming?.length) return existing;
  const map = new Map(existing.map((x) => [x.id, x]));
  for (const row of incoming) {
    map.set(row.id, { ...(map.get(row.id) as T | undefined), ...row });
  }
  const order = existing.map((x) => x.id);
  for (const row of incoming) {
    if (!order.includes(row.id)) order.push(row.id);
  }
  return order.map((id) => map.get(id)!).filter(Boolean);
}

/** Backend base for API + WS. Empty = same origin (Fly serves web + API together). */
export function apiBase(): string {
  const fromEnv = (import.meta as any).env?.VITE_BACKEND_URL as string | undefined;
  if (fromEnv && fromEnv.trim()) return fromEnv.trim().replace(/\/$/, '');
  return '';
}

export function wsBase(): string {
  const base = apiBase();
  if (base) return base.replace(/^http/, 'ws');
  return window.location.origin.replace(/^http/, 'ws');
}

export function httpOrigin(): string {
  return apiBase() || window.location.origin;
}
