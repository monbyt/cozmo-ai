import { useAppState } from '../hooks';
import { setState } from '../state';
import { unlockSharedAudio } from '../services/liveClient';

const COUNTRIES: Record<string, string> = {
  US: 'USD', GB: 'GBP', DE: 'EUR', FR: 'EUR', ES: 'EUR', IT: 'EUR', NL: 'EUR',
  CA: 'CAD', AU: 'AUD', TR: 'TRY', IN: 'INR', JP: 'JPY', AE: 'AED',
};

export function HomeScreen() {
  const country = useAppState((s) => s.country);

  return (
    <div className="screen home">
      <h1>Cozmo Claim</h1>
      <p>
        One continuous camera sweep of your library. Point at every shelf once —
        the agent logs books and items live. No app install.
      </p>

      <div className="row">
        <label htmlFor="country">Country / currency</label>
        <select
          id="country"
          value={country}
          onChange={(e) =>
            setState({ country: e.target.value, currency: COUNTRIES[e.target.value] })
          }
        >
          {Object.entries(COUNTRIES).map(([c, cur]) => (
            <option key={c} value={c}>
              {c} · {cur}
            </option>
          ))}
        </select>
      </div>

      <div className="spacer" />

      <button
        className="start-btn"
        onClick={() => {
          void unlockSharedAudio();
          setState({ screen: 'sweep' });
        }}
      >
        Start sweep
      </button>
      <div className="hint">
        Allow camera + mic when prompted. Use Safari or Chrome on your phone.
      </div>
    </div>
  );
}
