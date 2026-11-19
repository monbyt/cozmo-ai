/** Soft two-note log chime — same idea as the Flutter app (replaces spoken "got it"). */

let ctx: AudioContext | null = null;

async function getCtx(): Promise<AudioContext> {
  const AC = window.AudioContext || (window as any).webkitAudioContext;
  if (!ctx || ctx.state === 'closed') ctx = new AC();
  if (ctx.state === 'suspended') await ctx.resume();
  return ctx;
}

function tone(
  audioCtx: AudioContext,
  freq: number,
  start: number,
  dur: number,
  gain = 0.18,
): void {
  const osc = audioCtx.createOscillator();
  const g = audioCtx.createGain();
  osc.type = 'sine';
  osc.frequency.value = freq;
  g.gain.setValueAtTime(0.0001, start);
  g.gain.exponentialRampToValueAtTime(gain, start + 0.015);
  g.gain.exponentialRampToValueAtTime(0.0001, start + dur);
  osc.connect(g);
  g.connect(audioCtx.destination);
  osc.start(start);
  osc.stop(start + dur + 0.02);
}

let lastChime = 0;

/** Play A5 → C#6 confirmation ding. Debounced so enrich updates don't double-ding. */
export async function playLogChime(): Promise<void> {
  const now = performance.now();
  if (now - lastChime < 350) return;
  lastChime = now;
  try {
    const audioCtx = await getCtx();
    const t = audioCtx.currentTime + 0.01;
    tone(audioCtx, 880, t, 0.09);
    tone(audioCtx, 1108.73, t + 0.12, 0.09);
  } catch {
    /* ignore — autoplay / audio lock */
  }
}
