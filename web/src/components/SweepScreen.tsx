import { useEffect, useRef, useState } from 'react';
import { useAppState } from '../hooks';
import { setState, getState, mergeById, httpOrigin } from '../state';
import { LiveClient, type LiveEvent } from '../services/liveClient';
import { playLogChime } from '../services/chime';
import { InventoryList } from './InventoryList';

type LoadStep = 'camera' | 'audio' | 'live' | 'ready';
type SweepPhase = 'connecting' | 'intro' | 'tracking' | 'ending';

const LOAD_COPY: Record<LoadStep, string> = {
  camera: 'Opening camera…',
  audio: 'Unlocking mic & speakers…',
  live: 'Connecting live agent…',
  ready: 'Ready — start sweeping',
};

export function SweepScreen() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const liveRef = useRef<LiveClient | null>(null);
  /** Only true after the user taps End — ignores premature packet_ready / sync. */
  const userEndedRef = useRef(false);
  const knownIdsRef = useRef(new Set<string>());
  const cameraStartedRef = useRef(false);
  const trackingArmedRef = useRef(false);
  const introTurnDoneRef = useRef(false);
  const [starting, setStarting] = useState(true);
  const [loadStep, setLoadStep] = useState<LoadStep>('camera');
  const [phase, setPhase] = useState<SweepPhase>('connecting');
  const [error, setError] = useState<string | null>(null);
  const [micLevel, setMicLevel] = useState(0);
  const revisitTimer = useRef<number | null>(null);

  const books = useAppState((s) => s.books);
  const items = useAppState((s) => s.items);
  const revisitHint = useAppState((s) => s.revisitHint);

  useEffect(() => {
    void bootstrap();
    return () => { void teardown(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function beginTrackingCamera() {
    if (cameraStartedRef.current) return;
    const v = videoRef.current;
    const live = liveRef.current;
    if (!v || !live) return;
    cameraStartedRef.current = true;
    live.startCamera(v, 1200);
  }

  /** Wait for intro *voice* to finish playing (≥4.5s audio), then unlock. */
  async function armTrackingAfterVoice(reason: string) {
    if (trackingArmedRef.current) return;
    trackingArmedRef.current = true;
    console.log('[intro] arming after', reason);
    const live = liveRef.current;
    if (live) {
      await live.waitUntilQuiet({ minPlayedSec: 4.0, timeoutMs: 40_000 });
      console.log('[intro] voice drained', {
        queued: live.agentAudioQueuedSec(),
        micPackets: live.micPacketsSent(),
      });
      live.confirmTrackingReady();
    }
    setPhase('tracking');
    beginTrackingCamera();
  }

  async function bootstrap() {
    try {
      const { country, currency } = getState();
      setLoadStep('camera');
      setPhase('connecting');
      // One getUserMedia for cam+mic — avoids iOS "no AVAudioSessionCapture device"
      // when audio is requested in a second call after video.
      const media = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      const camStream = new MediaStream(media.getVideoTracks());
      const micStream = new MediaStream(media.getAudioTracks());
      const v = videoRef.current!;
      v.srcObject = camStream;
      v.muted = true;
      v.setAttribute('playsinline', 'true');
      try { await v.play(); } catch (e: any) { if (e?.name !== 'AbortError') throw e; }

      setLoadStep('audio');
      const live = new LiveClient();
      liveRef.current = live;
      live.onMicLevel = (rms) => {
        // Smooth a bit for the meter
        setMicLevel((prev) => prev * 0.6 + Math.min(1, rms * 8) * 0.4);
      };
      await live.primeAudio();

      setLoadStep('live');
      await live.connect({ country, currency, onEvent });
      await live.attachMic(micStream);
      // Preview only during intro — uplink starts after voice finishes + tracking_ready.
      setLoadStep('ready');
      setPhase('intro');
      await new Promise((r) => setTimeout(r, 350));
      setStarting(false);
    } catch (e: any) {
      console.error(e);
      const msg = String(e?.message ?? e ?? '');
      if (/AVAudioSession|NotFoundError|NotAllowedError|Permission/i.test(msg)) {
        setError(
          'Camera/mic permission failed. On iPhone: Settings → Safari → Camera & Microphone → Allow, then reload.',
        );
      } else {
        setError(msg || 'Could not start sweep');
      }
      setStarting(false);
    }
  }

  function onEvent(e: LiveEvent) {
    if (e.type !== 'audio' && e.type !== 'transcript') console.log('[ws]', e.type, e);
    switch (e.type) {
      case 'session':
        setState({ sweepId: e.sweep_id });
        break;
      case 'ready':
        setLoadStep('ready');
        break;
      case 'phase':
        if (e.phase === 'intro') {
          setPhase('intro');
        } else if (e.phase === 'intro_done') {
          introTurnDoneRef.current = true;
          void armTrackingAfterVoice('intro_done');
        } else if (e.phase === 'tracking') {
          setPhase('tracking');
          beginTrackingCamera();
        }
        break;
      case 'agent_generation_complete':
      case 'agent_turn_complete':
        if (!trackingArmedRef.current) {
          introTurnDoneRef.current = true;
          void armTrackingAfterVoice(e.type);
        }
        break;
      case 'audio':
        liveRef.current?.playPcmChunk(e.data);
        break;
      case 'interrupted':
        // Do NOT cut agent mid-sentence on spurious interrupts.
        break;
      case 'transcript':
        // Captions removed — Gemini transcript chunks were garbled on screen.
        break;
      case 'inventory_update': {
        const incoming = [...(e.new_books || []), ...(e.new_items || [])];
        let isNew = false;
        for (const row of incoming) {
          const id = row?.id as string | undefined;
          if (!id) continue;
          if (!knownIdsRef.current.has(id)) {
            knownIdsRef.current.add(id);
            isNew = true;
          }
        }
        if (isNew) void playLogChime();
        setState((s) => ({
          books: mergeById(s.books, e.new_books || []),
          items: mergeById(s.items, e.new_items || []),
        }));
        break;
      }
      case 'revisit': {
        setState({ revisitHint: e.hint || 'Look back at that one.' });
        if (revisitTimer.current) clearTimeout(revisitTimer.current);
        revisitTimer.current = window.setTimeout(() => setState({ revisitHint: '' }), 5000);
        break;
      }
      case 'tool':
        if (e.name === 'start_tracking' && (e.phase === 'done' || e.phase === 'running')) {
          introTurnDoneRef.current = true;
          void armTrackingAfterVoice('start_tracking');
        }
        if (e.phase === 'done') {
          setState((s) => ({ captureNotes: [...s.captureNotes.slice(-20), `tool:${e.name}`] }));
        }
        break;
      case 'packet_ready': {
        // Never auto-complete — only leave the sweep after the user taps End.
        if (!userEndedRef.current) break;
        liveRef.current?.stopCamera();
        // Let the one-shot summary finish, then mute further agent loops.
        window.setTimeout(() => liveRef.current?.muteAgent(), 18_000);
        const origin = httpOrigin();
        setState({
          packetJsonUrl: `${origin}${e.json_url}`,
          packetHtmlUrl: `${origin}${e.html_url}`,
          summary: (e as any).summary ?? null,
          screen: 'packet',
        });
        break;
      }
      case 'error':
        setError(e.message);
        break;
    }
  }

  async function onEnd() {
    if (userEndedRef.current) return;
    userEndedRef.current = true;
    setPhase('ending');
    setStarting(true);
    setLoadStep('ready');
    // Stop camera immediately; backend finalizes + one summary.
    liveRef.current?.stopCamera();
    liveRef.current?.endSweep();
    // Hard stop the Live session after summary window — kills repeat loops.
    window.setTimeout(() => {
      liveRef.current?.muteAgent();
      void liveRef.current?.close();
    }, 25_000);
  }

  async function teardown() {
    if (revisitTimer.current) clearTimeout(revisitTimer.current);
    try {
      const v = videoRef.current;
      const ms = v?.srcObject as MediaStream | null;
      ms?.getTracks().forEach((t) => t.stop());
      if (v) v.srcObject = null;
    } catch {}
    // Don't mark userEnded — unmount/reconnect must not finalize the sweep.
    await liveRef.current?.close().catch(() => {});
  }

  if (error) {
    return (
      <div className="screen pad">
        <h2>Couldn't start sweep</h2>
        <p style={{ color: 'var(--muted)' }}>{error}</p>
        <button className="start-btn" onClick={() => setState({ screen: 'home' })}>Back</button>
      </div>
    );
  }

  const appraise = books.filter((b) => b.status === 'needs_appraisal').length
    + items.filter((i) => i.status === 'needs_appraisal').length;
  const finding = books.filter((b) => b.processing).length + items.filter((i) => i.processing).length;
  const tracking = phase === 'tracking';

  return (
    <div className={`screen sweep ${tracking ? 'is-tracking' : phase === 'intro' ? 'is-intro' : ''}`}>
      <video ref={videoRef} className="camera" autoPlay playsInline muted />

      {starting && (
        <div className="boot">
          <div className="boot-card">
            <div className="boot-spinner" />
            <div className="boot-title">
              {phase === 'ending' ? 'Building claim packet…' : LOAD_COPY[loadStep]}
            </div>
            {phase !== 'ending' && (
              <ol className="boot-steps">
                {(['camera', 'audio', 'live', 'ready'] as LoadStep[]).map((s) => (
                  <li key={s} className={s === loadStep ? 'on' : ''}>{LOAD_COPY[s]}</li>
                ))}
              </ol>
            )}
          </div>
        </div>
      )}

      {!starting && phase === 'intro' && (
        <div className="phase-banner intro">
          <div className="phase-dot" />
          <div>
            <div className="phase-title">Intro</div>
            <div className="phase-sub">Listen — tracking starts when Cozmo finishes speaking</div>
          </div>
        </div>
      )}

      {!starting && tracking && (
        <div className="phase-banner tracking">
          <div className="phase-dot pulse" />
          <div>
            <div className="phase-title">Tracking</div>
            <div className="phase-sub">Walk shelves · books, items & room</div>
          </div>
        </div>
      )}

      <div className="badges">
        <span className={`badge mic ${micLevel > 0.12 ? 'hot' : ''}`} title="Mic level">
          <span className="mic-bar" style={{ transform: `scaleY(${Math.max(0.08, micLevel)})` }} />
          Mic
        </span>
        {tracking && <span className="badge live">● Live</span>}
        <span className="badge">{books.length} books</span>
        <span className="badge good">{books.filter((b) => b.status === 'identified').length} ID</span>
        {finding > 0 && <span className="badge">⟳ {finding}</span>}
        {appraise > 0 && <span className="badge warn">{appraise} look again</span>}
        <button className="end-btn" onClick={onEnd}>End</button>
      </div>

      {revisitHint && <div className="revisit">{revisitHint}</div>}

      <div className={`dock ${tracking ? 'dock-on' : 'dock-dim'}`}>
        <div className="dock-label">{tracking ? 'Live finds' : 'Finds unlock after intro'}</div>
        <InventoryList />
      </div>
    </div>
  );
}
