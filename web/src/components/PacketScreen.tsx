import { useAppState } from '../hooks';
import { setState } from '../state';

export function PacketScreen() {
  const sweepId = useAppState((s) => s.sweepId);
  const books = useAppState((s) => s.books);
  const items = useAppState((s) => s.items);
  const packetJsonUrl = useAppState((s) => s.packetJsonUrl);
  const packetHtmlUrl = useAppState((s) => s.packetHtmlUrl);
  const summary = useAppState((s) => s.summary);

  const identified = books.filter((b) => b.status === 'identified').length;
  const appraise = books.filter((b) => b.status === 'needs_appraisal').length
    + items.filter((i) => i.status === 'needs_appraisal').length;

  const speak = typeof summary?.speak === 'string' ? summary.speak : null;

  return (
    <div className="screen packet">
      <h1>Claim packet</h1>
      <div style={{ color: 'var(--muted)', fontSize: 13 }}>
        Sweep <code>{sweepId}</code>
      </div>
      {speak && (
        <p style={{ marginTop: 12, color: 'var(--fg)' }}>{speak}</p>
      )}
      <div className="grid">
        <div className="tile"><div className="k">Books</div><div className="v">{books.length}</div></div>
        <div className="tile"><div className="k">Identified</div><div className="v">{identified}</div></div>
        <div className="tile"><div className="k">Items</div><div className="v">{items.length}</div></div>
        <div className="tile"><div className="k">Needs appraisal</div><div className="v">{appraise}</div></div>
      </div>
      <div style={{ marginTop: 20 }}>
        <div style={{ color: 'var(--muted)', fontSize: 12, marginBottom: 4 }}>Full report (HTML)</div>
        {packetHtmlUrl && (
          <a href={packetHtmlUrl} target="_blank" rel="noreferrer">{packetHtmlUrl}</a>
        )}
      </div>
      <div style={{ marginTop: 16 }}>
        <div style={{ color: 'var(--muted)', fontSize: 12, marginBottom: 4 }}>Structured packet (JSON)</div>
        {packetJsonUrl && (
          <a href={packetJsonUrl} target="_blank" rel="noreferrer">{packetJsonUrl}</a>
        )}
      </div>
      <div className="spacer" />
      <div>
        <a
          className="secondary-btn"
          href={packetHtmlUrl ?? '#'}
          target="_blank"
          rel="noreferrer"
        >
          Open HTML report
        </a>
        <button
          className="secondary-btn"
          onClick={() =>
            setState({
              screen: 'home',
              sweepId: null,
              books: [],
              items: [],
              captureNotes: [],
              agentUtterance: '',
              packetJsonUrl: null,
              packetHtmlUrl: null,
              summary: null,
            })
          }
        >
          New sweep
        </button>
      </div>
    </div>
  );
}
