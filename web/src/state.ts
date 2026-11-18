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
  backendUrl: string;
  country: string;
  currency: string;
  heightCm: number;
  // sweep
  sweepId: string | null;
  books: BookEntry[];
  items: ItemEntry[];
  captureNotes: string[];
  agentUtterance: string;
  revisitHint: string;
  // packet
  packetJsonUrl: string | null;
  packetHtmlUrl: string | null;
};

const listeners = new Set<() => void>();
let state: State = {
  screen: 'home',
  backendUrl: pickDefaultBackend(),
  country: 'US',
  currency: 'USD',
  heightCm: 175,
  sweepId: null,
  books: [],
  items: [],
  captureNotes: [],
  agentUtterance: '',
  revisitHint: '',
  packetJsonUrl: null,
  packetHtmlUrl: null,
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
  // Preserve discovery order; append brand-new ids at the end.
  const order = existing.map((x) => x.id);
  for (const row of incoming) {
    if (!order.includes(row.id)) order.push(row.id);
  }
  return order.map((id) => map.get(id)!).filter(Boolean);
}

export function pickDefaultBackend(): string {
  // Empty string = same-origin. Vite dev server proxies /ws, /agent, /stt, /sweeps to the backend,
  // so a single tunnel URL (Cloudflare / ngrok / vite-basic-ssl) serves both sides.
  return '';
}
