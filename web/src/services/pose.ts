// Pose integration from DeviceOrientation + step detection from DeviceMotion.
// Used for the user-assisted room calibration.

export type OrientationFrame = { alpha: number; beta: number; gamma: number };

export class PoseTracker {
  private handlerO: ((e: DeviceOrientationEvent) => void) | null = null;
  private handlerM: ((e: DeviceMotionEvent) => void) | null = null;
  private latest: OrientationFrame = { alpha: 0, beta: 0, gamma: 0 };
  private steps = 0;
  private lastStepT = 0;
  private lastMag = 0;

  /** Ask iOS Safari 13+ for permission. Must be called from a user gesture. */
  async requestPermission(): Promise<boolean> {
    try {
      const anyDO = DeviceOrientationEvent as any;
      const anyDM = DeviceMotionEvent as any;
      if (typeof anyDO?.requestPermission === 'function') {
        const okO = await anyDO.requestPermission();
        const okM = typeof anyDM?.requestPermission === 'function'
          ? await anyDM.requestPermission() : 'granted';
        return okO === 'granted' && okM === 'granted';
      }
      return true; // Android Chrome: no permission needed
    } catch { return false; }
  }

  start(): void {
    this.handlerO = (e) => {
      this.latest = { alpha: e.alpha ?? 0, beta: e.beta ?? 0, gamma: e.gamma ?? 0 };
    };
    window.addEventListener('deviceorientation', this.handlerO);

    this.handlerM = (e) => {
      const g = e.accelerationIncludingGravity;
      if (!g) return;
      // Earth-gravity-cancelled step detection: magnitude peaks above ~12 m/s^2 with 300ms refractory
      const mag = Math.hypot(g.x ?? 0, g.y ?? 0, g.z ?? 0);
      const now = performance.now();
      if (mag - this.lastMag > 3.5 && now - this.lastStepT > 320) {
        this.steps += 1;
        this.lastStepT = now;
      }
      this.lastMag = mag;
    };
    window.addEventListener('devicemotion', this.handlerM);
  }

  stop(): void {
    if (this.handlerO) window.removeEventListener('deviceorientation', this.handlerO);
    if (this.handlerM) window.removeEventListener('devicemotion', this.handlerM);
    this.handlerO = null;
    this.handlerM = null;
  }

  snapshot(): OrientationFrame { return this.latest; }
  stepCount(): number { return this.steps; }
  resetSteps(): void { this.steps = 0; }
}

/** stride (m) ≈ 0.415 × height(m) (Pheasant & Haslegrave anthropometric rule). */
export function strideFromHeight(heightCm: number): number {
  return (heightCm / 100) * 0.415;
}
