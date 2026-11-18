import { useAppState } from '../hooks';
import { setState } from '../state';
import { unlockSharedAudio } from '../services/liveClient';

const COUNTRIES: Record<string, string> = {
  US: 'USD', GB: 'GBP', DE: 'EUR', FR: 'EUR', ES: 'EUR', IT: 'EUR', NL: 'EUR',
  CA: 'CAD', AU: 'AUD', TR: 'TRY', IN: 'INR', JP: 'JPY',
};

export function HomeScreen() {
  const country = useAppState((s) => s.country);
  const currency = useAppState((s) => s.currency);
  const backendUrl = useAppState((s) => s.backendUrl);
  const heightCm = useAppState((s) => s.heightCm);

  return (
    <div className="screen home">
      <h1>Contents Claim Sweep</h1>
      <p>
        One continuous camera sweep. Point the phone at every shelf, wall, and floor patch once.
        The agent will tell you when to slow down or step closer.
      </p>

      <div className="row">
        <label htmlFor="country">Country</label>
        <select id="country" value={country}
          onChange={(e) => setState({ country: e.target.value, currency: COUNTRIES[e.target.value] })}>
          {Object.keys(COUNTRIES).map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div className="row">
        <label>Currency</label>
        <input value={currency} readOnly />
      </div>
      <div className="row">
        <label htmlFor="height">Your height (cm)</label>
        <input id="height" type="number" inputMode="numeric" value={heightCm}
          onChange={(e) => setState({ heightCm: Math.max(100, Math.min(220, Number(e.target.value) || 175)) })} />
      </div>
      <div className="row">
        <label htmlFor="backend">Backend URL</label>
        <input id="backend" value={backendUrl} placeholder="(same origin)"
          onChange={(e) => setState({ backendUrl: e.target.value.trim() })} />
      </div>

      <div className="spacer" />

      <button className="start-btn" onClick={() => {
        // Unlock once under the user gesture and keep that AudioContext for Sweep playback.
        void unlockSharedAudio();
        setState({ screen: 'sweep' });
      }}>
        Start sweep
      </button>
      <div className="hint">
        Uses Gemini Live over WebSocket. Requires your Gemini account to have billing enabled for gemini-3.8-live.
      </div>
    </div>
  );
}
