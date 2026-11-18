// Gemini Live client. Owns the full voice loop:
//   mic   → PCM16 16kHz → base64 → ws.send({type:"audio", data})
//   cam   → JPEG       → base64 → ws.send({type:"video", data})
//   ws.recv → {audio PCM24} → play, {transcript}, {inventory_update}, {tool}, {packet_ready}

export type LiveEvent =
  | { type: 'session'; sweep_id: string; model: string }
  | { type: 'ready' }
  | { type: 'transcript'; speaker: 'User' | 'Agent'; text: string; final: boolean }
  | { type: 'audio'; data: string; mime_type: string }
  | { type: 'tool'; name: string; phase: 'running' | 'done' | 'error'; args?: any; result?: any; id?: string }
  | { type: 'inventory_update'; new_books: any[]; new_items: any[]; notes: string[] }
  | { type: 'revisit'; kind: string; id: string; hint: string; shelf_hint?: string; title?: string; description?: string }
  | { type: 'packet_ready'; sweep_id: string; json_url: string; html_url: string }
  | { type: 'interrupted' }
  | { type: 'error'; message: string };

type OnEvent = (e: LiveEvent) => void;

/** Shared AudioContext unlocked on the Start gesture so Sweep can play without a second unlock. */
let sharedAudioCtx: AudioContext | null = null;

export async function unlockSharedAudio(): Promise<AudioContext> {
  const AC = window.AudioContext || (window as any).webkitAudioContext;
  if (!sharedAudioCtx || sharedAudioCtx.state === 'closed') {
    sharedAudioCtx = new AC();
  }
  if (sharedAudioCtx.state === 'suspended') {
    await sharedAudioCtx.resume();
  }
  return sharedAudioCtx;
}

function wsBase(): string {
  const origin = window.location.origin;
  return origin.replace(/^http/, 'ws');
}

function arrayBufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.byteLength; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

function pcm16ToBase64(pcm: Int16Array): string {
  // Slice to the exact view — TypedArray.buffer can be larger than the samples.
  return arrayBufferToBase64(pcm.buffer.slice(pcm.byteOffset, pcm.byteOffset + pcm.byteLength));
}

function resampleToPcm16(input: Float32Array, srcRate: number, dstRate: number): Int16Array {
  const ratio = srcRate / dstRate;
  const outLen = Math.floor(input.length / ratio);
  const out = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const idx = i * ratio;
    const b = Math.floor(idx);
    const a = Math.min(b + 1, input.length - 1);
    const t = idx - b;
    const s = Math.max(-1, Math.min(1, input[b] * (1 - t) + input[a] * t));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function decodeBase64Pcm16(base64: string): Int16Array {
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const even = bytes.byteLength & 1 ? bytes.byteLength - 1 : bytes.byteLength;
  return new Int16Array(bytes.buffer, bytes.byteOffset, even / 2);
}

/** Tiny lookahead so the first chunk of a turn doesn't underrun. */
const PLAYBACK_PREBUFFER_SEC = 0.04;

export class LiveClient {
  private ws: WebSocket | null = null;
  private audioCtx: AudioContext | null = null;
  private micStream: MediaStream | null = null;
  private micSource: MediaStreamAudioSourceNode | null = null;
  private micProcessor: ScriptProcessorNode | null = null;
  private playNext = 0;
  private activeSources = new Set<AudioBufferSourceNode>();
  private cameraTimer: number | null = null;
  private videoEl: HTMLVideoElement | null = null;
  private onEvent: OnEvent | null = null;
  audioChunksReceived = 0;

  async connect(opts: { country: string; currency: string; onEvent: OnEvent }): Promise<void> {
    this.onEvent = opts.onEvent;
    this.ws = new WebSocket(`${wsBase()}/ws/live`);
    await new Promise<void>((resolve, reject) => {
      this.ws!.onopen = () => resolve();
      this.ws!.onerror = (e) => reject(e);
    });
    this.ws.onmessage = (ev) => {
      try { this.onEvent?.(JSON.parse(ev.data)); } catch {}
    };
    this.ws.send(JSON.stringify({
      type: 'start', country: opts.country, currency: opts.currency,
      device: navigator.userAgent.slice(0, 80),
    }));
  }

  /** Prefer the gesture-unlocked shared context; fall back to a fresh one. */
  async primeAudio(): Promise<void> {
    this.audioCtx = await unlockSharedAudio();
  }

  async startMic(): Promise<void> {
    if (this.micStream) return;
    await this.primeAudio();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
    this.micStream = stream;
    const ctx = this.audioCtx!;
    this.micSource = ctx.createMediaStreamSource(stream);
    // 2048 ≈ 40ms at 48kHz — snappier barge-in than 4096.
    this.micProcessor = ctx.createScriptProcessor(2048, 1, 1);
    this.micProcessor.onaudioprocess = (ev) => {
      ev.outputBuffer.getChannelData(0).fill(0);  // mute monitoring
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      // Always uplink — Gemini Live decides interruptions via START_OF_ACTIVITY_INTERRUPTS.
      const pcm = resampleToPcm16(ev.inputBuffer.getChannelData(0), ctx.sampleRate, 16000);
      if (pcm.length === 0) return;
      this.ws.send(JSON.stringify({ type: 'audio', data: pcm16ToBase64(pcm) }));
    };
    this.micSource.connect(this.micProcessor);
    this.micProcessor.connect(ctx.destination);
  }

  stopMic(): void {
    this.micProcessor?.disconnect();
    this.micSource?.disconnect();
    this.micStream?.getTracks().forEach((t) => t.stop());
    this.micProcessor = null;
    this.micSource = null;
    this.micStream = null;
  }

  /** Pipe camera frames to Gemini Live on a cadence. The <video> element must already be playing a MediaStream. */
  startCamera(video: HTMLVideoElement, cadenceMs: number = 1200): void {
    this.videoEl = video;
    const canvas = document.createElement('canvas');
    const tick = async () => {
      if (!video.videoWidth) return;
      canvas.width = 640;
      canvas.height = Math.round(640 * (video.videoHeight / video.videoWidth));
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob: Blob | null = await new Promise((r) => canvas.toBlob((b) => r(b), 'image/jpeg', 0.7));
      if (!blob || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      const buf = await blob.arrayBuffer();
      this.ws.send(JSON.stringify({ type: 'video', data: arrayBufferToBase64(buf) }));
    };
    this.cameraTimer = window.setInterval(() => void tick(), cadenceMs);
  }

  stopCamera(): void {
    if (this.cameraTimer) { clearInterval(this.cameraTimer); this.cameraTimer = null; }
  }

  sendText(text: string): void {
    this.ws?.send(JSON.stringify({ type: 'text', text, id: crypto.randomUUID() }));
  }

  /**
   * Schedule one PCM-16 24kHz chunk. Synchronous relative to the WS handler so the
   * playhead advances before the next chunk arrives.
   */
  playPcmChunk(base64: string): void {
    const ctx = this.audioCtx;
    if (!ctx) return;
    if (ctx.state === 'suspended') void ctx.resume();

    this.audioChunksReceived += 1;
    const pcm = decodeBase64Pcm16(base64);
    if (pcm.length === 0) return;

    const buf = ctx.createBuffer(1, pcm.length, 24000);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;

    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);

    const now = ctx.currentTime;
    const queueEmpty = this.playNext <= now + 0.02;
    const startAt = queueEmpty
      ? now + PLAYBACK_PREBUFFER_SEC
      : Math.max(now, this.playNext);

    this.activeSources.add(src);
    src.onended = () => { this.activeSources.delete(src); };
    src.start(startAt);
    this.playNext = startAt + buf.duration;

    if (this.audioChunksReceived <= 3) {
      console.log(`[liveClient] scheduled PCM #${this.audioChunksReceived}, ctx.state=${ctx.state}, duration=${buf.duration.toFixed(3)}s`);
    }
  }

  /** Hard cut: stop every scheduled BufferSource and reset the playhead. */
  stopPlayback(): void {
    for (const src of this.activeSources) {
      try { src.stop(); } catch { /* already stopped */ }
    }
    this.activeSources.clear();
    this.playNext = this.audioCtx?.currentTime ?? 0;
  }

  async close(): Promise<void> {
    this.stopCamera();
    this.stopMic();
    this.stopPlayback();
    try { this.ws?.send(JSON.stringify({ type: 'close' })); } catch {}
    await new Promise((r) => setTimeout(r, 300));
    this.ws?.close();
    this.ws = null;
    this.audioCtx = null;
  }
}
