import type { NewsItem } from '../types';

export function NewsList({ news }: { news: NewsItem[] }) {
  if (!news.length) return <p className="muted">No recent headlines found.</p>;
  return (
    <div>
      {news.map((n, i) => (
        <div className="news-item" key={`${n.url}-${i}`}>
          <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a>
          <div className="meta">{[n.source, n.published_at].filter(Boolean).join(' · ')}</div>
        </div>
      ))}
    </div>
  );
}
