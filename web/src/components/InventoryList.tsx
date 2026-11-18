import { useAppState } from '../hooks';

function Cover({ src, label }: { src?: string; label: string }) {
  if (src) {
    return <img className="cover" src={src} alt="" loading="lazy" />;
  }
  return <div className="cover cover-fallback" aria-hidden>{label.slice(0, 1).toUpperCase() || '?'}</div>;
}

export function InventoryList() {
  const books = useAppState((s) => s.books);
  const items = useAppState((s) => s.items);

  if (books.length === 0 && items.length === 0) {
    return <div className="empty">Point at a shelf — finds land here.</div>;
  }

  const cards = [
    ...[...books].reverse().map((b) => ({
      key: b.id,
      kind: 'book' as const,
      title: b.title || '(unreadable spine)',
      sub: [b.author, b.price_label].filter(Boolean).join(' · '),
      status: b.status,
      image: b.image_url,
      processing: b.processing,
      price: b.price_label,
    })),
    ...[...items].reverse().map((i) => ({
      key: i.id,
      kind: 'item' as const,
      title: i.description || i.category,
      sub: [i.category, i.brand_model, i.price_label].filter(Boolean).join(' · '),
      status: i.status,
      image: i.image_url,
      processing: i.processing,
      price: i.price_label,
    })),
  ].slice(0, 24);

  return (
    <div className="rail">
      {cards.map((c) => (
        <article key={c.key} className={`card ${c.processing ? 'is-processing' : ''} ${c.status}`}>
          <Cover src={c.image} label={c.title} />
          <div className="card-body">
            <div className="card-title">{c.title}</div>
            {c.sub && <div className="card-sub">{c.sub}</div>}
            <div className="card-meta">
              <span className={`pill ${c.status}`}>{c.processing ? 'finding…' : c.status.replace('_', ' ')}</span>
              {c.price && !c.processing && <span className="price">{c.price}</span>}
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}
