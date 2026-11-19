// Gemini Live client. Owns the full voice loop:
//   mic   → PCM16 16kHz continuous → ws.send({type:"audio", data})
//   cam   → JPEG                   → ws.send({type:"video", data})
//   ws.recv → {audio PCM24} → play, {transcript}, {inventory_update}, …

import { wsBase } from '../state';

export type LiveEvent =
  | { type: 'session'; sweep_id: string; model: string }
  | { type: 'ready' }
  | { type: 'phase'; phase: 'intro' | 'intro_done' | 'tracking' }
  | { type: 'agent_turn_complete' }
  | { type: 'agent_generation_complete' }
  | { type: 'transcript'; speaker: 'User' | 'Agent'; text: string; final: boolean }
  | { type: 'audio'; data: string; mime_type: string }
  | { type: 'tool'; name: string; phase: 'running' | 'done' | 'error'; args?: any; result?: any; id?: string }
  | { type: 'inventory_update'; new_books: any[]; new_items: any[]; notes: string[] }
  | { type: 'revisit'; kind: string; id: string; hint: string; shelf_hint?: string; title?: string; description?: string }
  | { type: 'packet_ready'; sweep_id: string; json_url: string; html_url: string; summary?: Record<string, unknown> }
  | { type: 'interrupted' }
  | { type: 'error'; message: string };

type OnEvent = (e: LiveEvent) => void;

/** Shared AudioContext unlocked on the Start gesture so Sweep can play without a second unlock. */
let sharedAudioCtx: AudioContext | null = null;
let workletReady: Promise<boolean> | null = null;

const MIC_WORKLET = `
class MicCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._acc = new Float32Array(0);
    this._ratio = sampleRate / 16000;
    this._pos = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch || ch.length === 0) return true;
    const merged = new Float32Array(this._acc.length + ch.length);
    merged.set(this._acc, 0);
    merged.set(ch, this._acc.length);
    this._acc = merged;

    const outLen = Math.floor((this._acc.length - this._pos) / this._ratio);
    // ~40ms @16k — Gemini VAD needs a continuous stream including silence.
    if (outLen < 640) return true;

    const pcm = new Int16Array(outLen);
    let sum = 0;
    for (let i = 0; i < outLen; i++) {
      const idx = this._pos + i * this._ratio;
      const b = Math.floor(idx);
      const a = Math.min(b + 1, this._acc.length - 1);
      const t = idx - b;
      let s = this._acc[b] * (1 - t) + this._acc[a] * t;
      s = Math.max(-1, Math.min(1, s * 2.8));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      const f = pcm[i] / 32768;
      sum += f * f;
    }
    this._pos += outLen * this._ratio;
    if (this._pos > 8000) {
      const keepFrom = Math.floor(this._pos);
      this._acc = this._acc.slice(keepFrom);
      this._pos -= keepFrom;
    }
    const rms = Math.sqrt(sum / outLen);
    this.port.postMessage({ pcm: pcm.buffer, rms }, [pcm.buffer]);
    return true;
  }
}
registerProcessor('mic-capture', MicCaptureProcessor);
`;

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

async function ensureMicWorklet(ctx: AudioContext): Promise<boolean> {
  if (workletReady) return workletReady;
  workletReady = (async () => {
    try {
      if (!ctx.audioWorklet) return false;
      const blob = new Blob([MIC_WORKLET], { type: 'application/javascript' });
      const url = URL.createObjectURL(blob);
      try {
        await ctx.audioWorklet.addModule(url);
      } finally {
        URL.revokeObjectURL(url);
      }
      return true;
    } catch (e) {
      console.warn('[mic] AudioWorklet unavailable', e);
      return false;
    }
  })();
  return workletReady;
}

function arrayBufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.byteLength; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

function pcm16ToBase64(pcm: Int16Array): string {
  const copy = pcm.buffer.slice(pcm.byteOffset, pcm.byteOffset + pcm.byteLength);
  return arrayBufferToBase64(copy as ArrayBuffer);
}

function resampleToPcm16(input: Float32Array, srcRate: number, dstRate: number, gain = 2.8): Int16Array {
  const ratio = srcRate / dstRate;
  const outLen = Math.floor(input.length / ratio);
  const out = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const idx = i * ratio;
    const b = Math.floor(idx);
    const a = Math.min(b + 1, input.length - 1);
    const t = idx - b;
    let s = (input[b] * (1 - t) + input[a] * t) * gain;
    s = Math.max(-1, Math.min(1, s));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function rmsFloat(input: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
  return Math.sqrt(sum / Math.max(1, input.length));
}

function decodeBase64Pcm16(base64: string): Int16Array {
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const even = bytes.byteLength & 1 ? bytes.byteLength - 1 : bytes.byteLength;
  return new Int16Array(bytes.buffer, bytes.byteOffset, even / 2);
}

/** Wait this long before starting playback so network jitter doesn't punch holes in words. */
const JITTER_START_SEC = 0.38;
/** After an underrun, re-buffer before speaking again. */
const JITTER_REBUFFER_SEC = 0.28;
const AGENT_SAMPLE_RATE = 24000;

export class LiveClient {
  private ws: WebSocket | null = null;
  private audioCtx: AudioContext | null = null;
  private micStream: MediaStream | null = null;
  private micSource: MediaStreamAudioSourceNode | null = null;
  private micProcessor: ScriptProcessorNode | null = null;
  private micWorklet: AudioWorkletNode | null = null;
  private micGain: GainNode | null = null;
  private playNext = 0;
  private activeSources = new Set<AudioBufferSourceNode>();
  /** Hold chunks until we have enough buffered — prevents "welcome….in….usd". */
  private pendingBuffers: AudioBuffer[] = [];
  private pendingSec = 0;
  private playbackStarted = false;
  private cameraTimer: number | null = null;
  private onEvent: OnEvent | null = null;
  private cameraEnabled = true;
  private acceptAgentAudio = true;
  private micEnabled = true;
  private totalQueuedSec = 0;
  private lastMicRms = 0;
  private micChunksSent = 0;
  audioChunksReceived = 0;
  onMicLevel: ((rms: number) => void) | null = null;

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

  async primeAudio(): Promise<void> {
    this.audioCtx = await unlockSharedAudio();
  }

  micLevel(): number {
    return this.lastMicRms;
  }

  micPacketsSent(): number {
    return this.micChunksSent;
  }

  /** Seconds of agent audio queued so far this session. */
  agentAudioQueuedSec(): number {
    return this.totalQueuedSec;
  }

  /** True while agent PCM is actively playing (or still queued). */
  isAgentSpeaking(): boolean {
    const ctx = this.audioCtx;
    if (!ctx) return false;
    return this.activeSources.size > 0 || this.playNext > ctx.currentTime + 0.1;
  }

  /**
   * Wait until the intro *voice* has actually been heard —
   * requires real queued audio, then a drained playback queue.
   */
  async waitUntilQuiet(opts?: {
    minPlayedSec?: number;
    timeoutMs?: number;
  }): Promise<void> {
    const minPlayedSec = opts?.minPlayedSec ?? 4.0;
    const timeoutMs = opts?.timeoutMs ?? 40_000;
    const start = Date.now();
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

    while (Date.now() - start < timeoutMs) {
      const queued = this.totalQueuedSec;
      const speaking = this.isAgentSpeaking();

      // Ideal: enough spoken audio and playback drained.
      if (queued >= minPlayedSec && !speaking) {
        await sleep(550);
        if (!this.isAgentSpeaking()) return;
      }

      // Soft path after several seconds: at least ~2s heard and now quiet.
      if (queued >= 2.0 && !speaking && Date.now() - start > 6_000) {
        await sleep(650);
        if (!this.isAgentSpeaking() && this.totalQueuedSec >= 2.0) return;
      }

      await sleep(80);
    }
  }

  private sendMicPcm(pcm: Int16Array, level: number): void {
    if (!this.micEnabled) return;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    if (pcm.length === 0) return;

    this.lastMicRms = level;
    this.onMicLevel?.(level);

    // Never wipe agent playback from mic energy — that punched holes in sentences.
    // Gemini uses NO_INTERRUPTION; let the spoken sentence finish.

    // CRITICAL: always send, including silence — Gemini auto-VAD needs a continuous stream.
    this.ws.send(JSON.stringify({ type: 'audio', data: pcm16ToBase64(pcm) }));
    this.micChunksSent += 1;
  }

  async attachMic(stream: MediaStream): Promise<void> {
    if (this.micStream) return;
    const tracks = stream.getAudioTracks();
    if (!tracks.length) {
      throw new Error('No microphone track — allow mic access and reload');
    }
    for (const t of tracks) {
      t.enabled = true;
      try {
        await t.applyConstraints({
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        } as MediaTrackConstraints);
      } catch { /* some browsers reject partial constraints */ }
    }

    await this.primeAudio();
    const ctx = this.audioCtx!;
    if (ctx.state === 'suspended') await ctx.resume();

    this.micStream = stream;
    this.micSource = ctx.createMediaStreamSource(stream);
    // Keep the graph alive without feeding mic into speakers (echo).
    this.micGain = ctx.createGain();
    this.micGain.gain.value = 0;

    const useWorklet = await ensureMicWorklet(ctx);
    if (useWorklet) {
      this.micWorklet = new AudioWorkletNode(ctx, 'mic-capture', {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        channelCount: 1,
      });
      this.micWorklet.port.onmessage = (ev) => {
        const { pcm, rms } = ev.data as { pcm: ArrayBuffer; rms: number };
        this.sendMicPcm(new Int16Array(pcm), rms);
      };
      this.micSource.connect(this.micWorklet);
      this.micWorklet.connect(this.micGain);
      this.micGain.connect(ctx.destination);
      console.log('[mic] AudioWorklet capture active', { rate: ctx.sampleRate, track: tracks[0].label });
    } else {
      this.micProcessor = ctx.createScriptProcessor(4096, 1, 1);
      this.micProcessor.onaudioprocess = (ev) => {
        if (ctx.state === 'suspended') void ctx.resume();
        const input = ev.inputBuffer.getChannelData(0);
        const level = rmsFloat(input);
        const pcm = resampleToPcm16(input, ctx.sampleRate, 16000, 2.8);
        this.sendMicPcm(pcm, level);
      };
      this.micSource.connect(this.micProcessor);
      this.micProcessor.connect(this.micGain);
      this.micGain.connect(ctx.destination);
      console.log('[mic] ScriptProcessor capture active', { rate: ctx.sampleRate, track: tracks[0].label });
    }

    // Keep AudioContext alive on iOS when tab is foregrounded.
    const resume = () => { if (ctx.state === 'suspended') void ctx.resume(); };
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('touchstart', resume, { passive: true });
  }

  async startMic(): Promise<void> {
    if (this.micStream) return;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
    await this.attachMic(stream);
  }

  stopMic(): void {
    this.micEnabled = false;
    try { this.micWorklet?.port.close(); } catch {}
    this.micWorklet?.disconnect();
    this.micProcessor?.disconnect();
    this.micSource?.disconnect();
    this.micGain?.disconnect();
    this.micStream?.getTracks().forEach((t) => t.stop());
    this.micWorklet = null;
    this.micProcessor = null;
    this.micSource = null;
    this.micGain = null;
    this.micStream = null;
  }

  startCamera(video: HTMLVideoElement, cadenceMs: number = 1200): void {
    this.cameraEnabled = true;
    const canvas = document.createElement('canvas');
    const tick = async () => {
      if (!this.cameraEnabled) return;
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
    this.cameraEnabled = false;
    if (this.cameraTimer) { clearInterval(this.cameraTimer); this.cameraTimer = null; }
  }

  sendText(text: string): void {
    this.ws?.send(JSON.stringify({ type: 'text', text, id: crypto.randomUUID() }));
  }

  /** Tell backend the intro voice finished playing — unlock tracking. */
  confirmTrackingReady(): void {
    this.ws?.send(JSON.stringify({ type: 'tracking_ready' }));
  }

  /** Finalize: stop camera immediately; backend speaks the summary once. */
  endSweep(): void {
    this.stopCamera();
    this.ws?.send(JSON.stringify({ type: 'end_sweep' }));
  }

  /** Stop accepting further agent audio (after packet / summary). */
  muteAgent(): void {
    this.acceptAgentAudio = false;
    this.stopPlayback();
  }

  playPcmChunk(base64: string): void {
    if (!this.acceptAgentAudio) return;
    const ctx = this.audioCtx;
    if (!ctx) return;
    if (ctx.state === 'suspended') void ctx.resume();

    this.audioChunksReceived += 1;
    const pcm = decodeBase64Pcm16(base64);
    if (pcm.length === 0) return;

    const buf = ctx.createBuffer(1, pcm.length, AGENT_SAMPLE_RATE);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;

    this.pendingBuffers.push(buf);
    this.pendingSec += buf.duration;
    this.totalQueuedSec += buf.duration;
    this.flushPendingPlayback();
  }

  /** Schedule buffered PCM on a continuous timeline — no gaps between words. */
  private flushPendingPlayback(): void {
    const ctx = this.audioCtx;
    if (!ctx || this.pendingBuffers.length === 0) return;

    const now = ctx.currentTime;
    const underrun = this.playNext <= now + 0.04;

    if (!this.playbackStarted) {
      if (this.pendingSec < JITTER_START_SEC) return;
      this.playbackStarted = true;
      this.playNext = now + 0.05;
    } else if (underrun) {
      // Network hiccup: don't resume with a tiny scrap — re-buffer first.
      if (this.pendingSec < JITTER_REBUFFER_SEC) return;
      this.playNext = now + 0.05;
    }

    while (this.pendingBuffers.length > 0) {
      const buf = this.pendingBuffers.shift()!;
      this.pendingSec = Math.max(0, this.pendingSec - buf.duration);

      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      const startAt = Math.max(ctx.currentTime + 0.01, this.playNext);
      this.activeSources.add(src);
      src.onended = () => {
        this.activeSources.delete(src);
        // If everything drained, next speech must re-fill the jitter buffer.
        if (this.activeSources.size === 0 && this.pendingBuffers.length === 0) {
          this.playbackStarted = false;
          this.playNext = 0;
        }
      };
      src.start(startAt);
      this.playNext = startAt + buf.duration;
    }
  }

  stopPlayback(): void {
    for (const src of this.activeSources) {
      try { src.stop(); } catch { /* already stopped */ }
    }
    this.activeSources.clear();
    this.pendingBuffers = [];
    this.pendingSec = 0;
    this.playbackStarted = false;
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
