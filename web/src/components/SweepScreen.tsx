import { useEffect, useRef, useState } from 'react';
import { useAppState } from '../hooks';
import { setState, getState, mergeById } from '../state';
import { LiveClient, type LiveEvent } from '../services/liveClient';
import { InventoryList } from './InventoryList';

type LoadStep = 'camera' | 'audio' | 'live' | 'ready';

const LOAD_COPY: Record<LoadStep, string> = {
  camera: 'Opening camera…',
  audio: 'Unlocking mic & speakers…',
  live: 'Connecting live agent…',
  ready: 'Ready — start sweeping',
};

export function SweepScreen() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const liveRef = useRef<LiveClient | null>(null);
  const endedRef = useRef(false);
  const [starting, setStarting] = useState(true);
  const [loadStep, setLoadStep] = useState<LoadStep>('camera');
  const [error, setError] = useState<string | null>(null);
  const [agentLine, setAgentLine] = useState('');
  const [userLine, setUserLine] = useState('');
  const agentBuf = useRef('');
  const userBuf = useRef('');
  const revisitTimer = useRef<number | null>(null);

  const books = useAppState((s) => s.books);
  const items = useAppState((s) => s.items);
  const revisitHint = useAppState((s) => s.revisitHint);

  useEffect(() => {
    void bootstrap();
    return () => { void teardown(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function bootstrap() {
    try {
      const { country, currency } = getState();
      setLoadStep('camera');
      const camStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      const v = videoRef.current!;
      v.srcObject = camStream;
      v.muted = true;
      v.setAttribute('playsinline', 'true');
      try { await v.play(); } catch (e: any) { if (e?.name !== 'AbortError') throw e; }

      setLoadStep('audio');
      const live = new LiveClient();
      liveRef.current = live;
      await live.primeAudio();

      setLoadStep('live');
      await live.connect({ country, currency, onEvent });
      await live.startMic();
      live.startCamera(v, 1200);
      setLoadStep('ready');
      // Brief beat so the user sees "Ready" before the overlay lifts.
      await new Promise((r) => setTimeout(r, 450));
      setStarting(false);
    } catch (e: any) {
      console.error(e);
      setError(e?.message ?? 'Could not start sweep');
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
      case 'audio':
        liveRef.current?.playPcmChunk(e.data);
        break;
      case 'interrupted':
        liveRef.current?.stopPlayback();
        break;
      case 'transcript': {
        if (e.speaker === 'User') {
          userBuf.current += e.text;
          setUserLine(userBuf.current);
          if (e.final) { userBuf.current = ''; setUserLine(''); }
        } else {
          agentBuf.current += e.text;
          // Keep caption short — last ~90 chars so it doesn't eat the camera.
          const clipped = agentBuf.current.length > 90
            ? '…' + agentBuf.current.slice(-90)
            : agentBuf.current;
          setAgentLine(clipped);
          setState({ agentUtterance: e.text });
          if (e.final) { agentBuf.current = ''; setAgentLine(''); }
        }
        break;
      }
      case 'inventory_update': {
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
        if (e.phase === 'done') {
          setState((s) => ({ captureNotes: [...s.captureNotes.slice(-20), `tool:${e.name}`] }));
        }
        break;
      case 'packet_ready': {
        if (!endedRef.current) {
          setError('Live session dropped unexpectedly. Go back and start again.');
          break;
        }
        const origin = window.location.origin;
        setState({
          packetJsonUrl: `${origin}${e.json_url}`,
          packetHtmlUrl: `${origin}${e.html_url}`,
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
    if (endedRef.current) return;
    endedRef.current = true;
    setStarting(true);
    setLoadStep('live');
    // Overlay while background pricing drains + packet builds.
    await liveRef.current?.close();
  }

  async function teardown() {
    endedRef.current = true;
    if (revisitTimer.current) clearTimeout(revisitTimer.current);
    try {
      const v = videoRef.current;
      const ms = v?.srcObject as MediaStream | null;
      ms?.getTracks().forEach((t) => t.stop());
      if (v) v.srcObject = null;
    } catch {}
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

  return (
    <div className="screen sweep">
      <video ref={videoRef} className="camera" autoPlay playsInline muted />

      {starting && (
        <div className="boot">
          <div className="boot-card">
            <div className="boot-spinner" />
            <div className="boot-title">{LOAD_COPY[loadStep]}</div>
            <ol className="boot-steps">
              {(['camera', 'audio', 'live', 'ready'] as LoadStep[]).map((s) => (
                <li key={s} className={s === loadStep ? 'on' : ''}>{LOAD_COPY[s]}</li>
              ))}
            </ol>
          </div>
        </div>
      )}

      <div className="badges">
        <span className="badge">{books.length} books</span>
        <span className="badge good">{books.filter((b) => b.status === 'identified').length} ID</span>
        {finding > 0 && <span className="badge">⟳ {finding}</span>}
        {appraise > 0 && <span className="badge warn">{appraise} look again</span>}
        <button className="end-btn" onClick={onEnd}>End</button>
      </div>

      {revisitHint && <div className="revisit">{revisitHint}</div>}

      {(agentLine || userLine) && (
        <div className="caption">
          {userLine && <div className="caption-user">you · {userLine}</div>}
          {agentLine && <div className="caption-agent">{agentLine}</div>}
        </div>
      )}

      <div className="dock">
        <div className="dock-label">Live finds</div>
        <InventoryList />
      </div>
    </div>
  );
}
