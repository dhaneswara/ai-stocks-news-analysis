import { type ReactNode } from 'react';

// A deliberately small Markdown renderer for the assistant's chat answers — ATX headings,
// unordered lists, paragraphs, and inline **bold**, `code`, and [links](url). Not a full
// CommonMark parser; kept minimal to avoid a heavy dependency.
const INLINE_RE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;

function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  INLINE_RE.lastIndex = 0;
  while ((m = INLINE_RE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith('**')) {
      out.push(<strong key={key++}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith('`')) {
      out.push(<code key={key++}>{tok.slice(1, -1)}</code>);
    } else {
      const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(tok)!;
      out.push(
        <a key={key++} href={mm[2]} target="_blank" rel="noreferrer">{mm[1]}</a>,
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let para: string[] = [];
  let key = 0;

  const flushPara = () => {
    if (para.length) {
      blocks.push(<p key={key++}>{renderInline(para.join(' '))}</p>);
      para = [];
    }
  };
  const flushList = () => {
    if (list.length) {
      blocks.push(
        <ul key={key++}>{list.map((li, i) => <li key={i}>{renderInline(li)}</li>)}</ul>,
      );
      list = [];
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    const li = /^[-*]\s+(.*)$/.exec(line);
    if (h) {
      flushPara();
      flushList();
      const level = h[1].length;
      if (level === 1) blocks.push(<h3 key={key++}>{renderInline(h[2])}</h3>);
      else if (level === 2) blocks.push(<h4 key={key++}>{renderInline(h[2])}</h4>);
      else blocks.push(<h5 key={key++}>{renderInline(h[2])}</h5>);
    } else if (li) {
      flushPara();
      list.push(li[1]);
    } else if (line.trim() === '') {
      flushPara();
      flushList();
    } else {
      flushList();
      para.push(line);
    }
  }
  flushPara();
  flushList();
  return <div className="md">{blocks}</div>;
}
