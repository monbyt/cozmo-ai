// Camera capture: start getUserMedia stream, extract JPEG keyframes at a cadence.

export type FrameCallback = (jpg: Blob, w: number, h: number) => void;

export class CameraCapture {
  private stream: MediaStream | null = null;
  private video: HTMLVideoElement;
  private canvas: HTMLCanvasElement;
  private timer: number | null = null;

  constructor(video: HTMLVideoElement) {
    this.video = video;
    this.canvas = document.createElement('canvas');
  }

  async start(): Promise<void> {
    if (this.stream) return;
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
      audio: false,
    });
    this.stream = stream;
    this.video.srcObject = stream;
    this.video.setAttribute('playsinline', 'true');
    this.video.muted = true;
    try {
      await this.video.play();
    } catch (e: any) {
      // Common in dev when StrictMode double-mounts: play() gets aborted when the stream is torn down.
      // Safe to ignore — sampling only runs if the stream is still attached.
      if (e?.name !== 'AbortError') throw e;
    }
  }

  stop(): void {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
  }

  startSampling(cadenceMs: number, cb: FrameCallback): void {
    this.stopSampling();
    this.timer = window.setInterval(async () => {
      const blob = await this.grab();
      if (blob) cb(blob, this.canvas.width, this.canvas.height);
    }, cadenceMs);
  }

  stopSampling(): void {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
  }

  async grab(): Promise<Blob | null> {
    if (!this.video.videoWidth) return null;
    this.canvas.width = this.video.videoWidth;
    this.canvas.height = this.video.videoHeight;
    const ctx = this.canvas.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(this.video, 0, 0);
    return await new Promise<Blob | null>((resolve) =>
      this.canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.85),
    );
  }

  /** Rough pinhole intrinsics: horizontal FOV defaults to 65° for a rear phone camera. */
  estimateIntrinsics(hFovDeg = 65): { fx: number; fy: number; cx: number; cy: number; width: number; height: number } | null {
    if (!this.canvas.width) return null;
    const w = this.canvas.width;
    const h = this.canvas.height;
    const fx = (w / 2) / Math.tan((hFovDeg / 2) * Math.PI / 180);
    const fy = fx;
    return { fx, fy, cx: w / 2, cy: h / 2, width: w, height: h };
  }
}
