// Voice: push-to-talk STT via backend (Gemini audio) + Web Speech TTS (works on iOS Safari).

import { BackendClient } from './backendClient';

export class VoiceLoop {
  private rec: MediaRecorder | null = null;
  private chunks: BlobPart[] = [];
  private mediaStream: MediaStream | null = null;

  constructor(private client: BackendClient) {}

  async requestMic(): Promise<void> {
    if (this.mediaStream) return;
    this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  }

  async startRecording(): Promise<void> {
    if (!this.mediaStream) await this.requestMic();
    if (!this.mediaStream) throw new Error('no mic');
    const mime = this.pickMime();
    this.chunks = [];
    this.rec = new MediaRecorder(this.mediaStream, mime ? { mimeType: mime } : undefined);
    this.rec.ondataavailable = (e) => { if (e.data.size > 0) this.chunks.push(e.data); };
    this.rec.start();
  }

  async stopRecordingAndTranscribe(): Promise<string> {
    if (!this.rec) return '';
    const stopped = new Promise<void>((resolve) => { this.rec!.onstop = () => resolve(); });
    this.rec.stop();
    await stopped;
    const type = this.rec.mimeType || 'audio/webm';
    const blob = new Blob(this.chunks, { type });
    if (blob.size < 500) return '';
    try {
      const r = await this.client.stt(blob);
      return (r.text || '').trim();
    } catch {
      return '';
    }
  }

  private pickMime(): string | null {
    const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4;codecs=aac', 'audio/mp4'];
    for (const t of types) {
      try { if (MediaRecorder.isTypeSupported(t)) return t; } catch {}
    }
    return null;
  }

  speak(text: string): void {
    if (!text) return;
    try {
      const synth = window.speechSynthesis;
      synth.cancel();
      const u = new SpeechSynthesisUtterance(text);
      // Pick the best available voice on this device.
      const voices = synth.getVoices();
      const preferred = ['Samantha (Enhanced)', 'Samantha', 'Karen (Enhanced)', 'Google US English', 'Microsoft Jenny Online'];
      const match = voices.find((v) => preferred.some((p) => v.name.startsWith(p)))
        ?? voices.find((v) => v.lang?.startsWith('en') && v.localService === false)
        ?? voices.find((v) => v.lang?.startsWith('en'));
      if (match) u.voice = match;
      u.rate = 1.0; u.pitch = 1.0;
      synth.speak(u);
    } catch {/* iOS may require a user gesture before first speak */}
  }

  dispose(): void {
    this.rec?.stream.getTracks().forEach((t) => t.stop());
    this.mediaStream?.getTracks().forEach((t) => t.stop());
    this.mediaStream = null;
    this.rec = null;
  }
}
