// WebSocket client for /ws/sweep + REST helpers.

type OnMessage = (msg: any) => void;

export class BackendClient {
  readonly baseUrl: string;
  private ws: WebSocket | null = null;
  private onMessage: OnMessage | null = null;

  constructor(baseUrl: string) { this.baseUrl = baseUrl.replace(/\/$/, ''); }

  get wsUrl(): string {
    // Same-origin by default (baseUrl === '') — Vite proxies /ws/sweep to the backend.
    const origin = this.baseUrl || window.location.origin;
    const u = new URL(origin);
    const scheme = u.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${scheme}//${u.host}/ws/sweep`;
  }

  async connectAndStart(opts: {
    country: string; currency: string; device: string;
    onMessage: OnMessage;
  }): Promise<string> {
    this.onMessage = opts.onMessage;
    this.ws = new WebSocket(this.wsUrl);
    return await new Promise<string>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('timeout connecting to backend')), 10000);
      this.ws!.onopen = () => {
        this.ws!.send(JSON.stringify({ type: 'start',
          country: opts.country, currency: opts.currency, device: opts.device }));
      };
      this.ws!.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === 'started') { clearTimeout(timeout); resolve(msg.sweep_id); }
          this.onMessage?.(msg);
        } catch {}
      };
      this.ws!.onerror = (e) => { clearTimeout(timeout); reject(e); };
    });
  }

  sendFrameMeta(meta: {
    frameId: string; ts: string; shelfHint?: string;
    intrinsics?: { fx: number; fy: number; cx: number; cy: number; width: number; height: number };
    orientation?: { alpha: number; beta: number; gamma: number };
  }): void {
    this.ws?.send(JSON.stringify({
      type: 'frame_meta',
      frame_id: meta.frameId, ts: meta.ts,
      shelf_hint: meta.shelfHint ?? '',
      intrinsics: meta.intrinsics,
      orientation: meta.orientation,
    }));
  }

  sendFrameBytes(bytes: ArrayBuffer | Uint8Array | Blob): void {
    this.ws?.send(bytes as any);
  }

  sendPlane(p: { kind: 'floor' | 'wall' | 'ceiling' | 'other'; area_m2: number; width_m?: number; height_m?: number }): void {
    this.ws?.send(JSON.stringify({ type: 'plane', ...p }));
  }

  async endAndClose(): Promise<void> {
    this.ws?.send(JSON.stringify({ type: 'end' }));
    await new Promise((r) => setTimeout(r, 1500));
    this.ws?.close();
  }

  // --- REST ---

  async agentTurn(body: {
    sweep_id: string; user_text: string;
    capture_notes: string[]; books_so_far: number; items_so_far: number;
  }): Promise<{ reply: string }> {
    const r = await fetch(`${this.baseUrl}/agent/turn`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    return r.json();
  }

  async stt(blob: Blob): Promise<{ text: string }> {
    const form = new FormData();
    form.append('audio', blob, 'speech.webm');
    const r = await fetch(`${this.baseUrl}/stt`, { method: 'POST', body: form });
    return r.json();
  }

  async reprice(sweepId: string, country: string): Promise<any> {
    const r = await fetch(`${this.baseUrl}/sweeps/${sweepId}/reprice?country=${country}`, { method: 'POST' });
    return r.json();
  }
}
