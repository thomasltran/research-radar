import React from 'react';

/* ── Markdown rendering ── */

export function MarkdownBlock(props: { content: string }) {
  return <div className="markdown-block">{renderMarkdownBlocks(props.content)}</div>;
}

export function MarkdownInlineBlock(props: { content: string }) {
  return <div className="markdown-inline-block">{renderMarkdownBlocks(props.content)}</div>;
}

export function MarkdownInline(props: { content: string }) {
  return <>{renderInlineMarkdown(props.content)}</>;
}

export function Section(props: { title: string; children: React.ReactNode }) {
  return (
    <section className="section">
      <h2>{props.title}</h2>
      <div className="section-body">
        {typeof props.children === 'string' ? <MarkdownInlineBlock content={props.children} /> : props.children}
      </div>
    </section>
  );
}

export function ListSection(props: { title: string; items: string[] }) {
  return props.items.length === 0 ? (
    <Section title={props.title}>No entries available.</Section>
  ) : (
    <section className="section">
      <h2>{props.title}</h2>
      <div className="section-body">
        <ul>
          {props.items.map((item, index) => <li key={`${item}-${index}`}><MarkdownInline content={item} /></li>)}
        </ul>
      </div>
    </section>
  );
}

export function RelationBlock(props: { related: Array<{ type: 'extends' | 'overlaps_with'; title: string; paper_id?: string | null }>; onOpenPaper: (id: string) => void }) {
  if (props.related.length === 0) {
    return <Section title="Related Papers">No explicit relationships available.</Section>;
  }
  return (
    <section className="section">
      <h2>Related Papers</h2>
      <div className="section-body">
        {props.related.map((item) => (
          <p key={`${item.type}-${item.title}`}>
            <strong>{item.type === 'extends' ? 'Extends' : 'Overlaps'}:</strong>{' '}
            {item.paper_id ? (
              <button className="inline-link" onClick={() => props.onOpenPaper(item.paper_id!)}>
                {item.title}
              </button>
            ) : item.title}
          </p>
        ))}
      </div>
    </section>
  );
}

/* ── Rendering Internals ── */

function renderMarkdownBlocks(content: string): React.ReactNode[] {
  const lines = content.replace(/\r\n/g, '\n').split('\n');
  const nodes: React.ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (line.startsWith('```')) {
      const language = line.slice(3).trim();
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith('```')) {
        codeLines.push(lines[index]);
        index += 1;
      }
      index += index < lines.length ? 1 : 0;
      nodes.push(
        <pre className="markdown-code" key={`code-${index}`}>
          {language && <span className="markdown-code-lang">{language}</span>}
          <code>{codeLines.join('\n')}</code>
        </pre>,
      );
      continue;
    }

    if (line.trim() === '$$' || line.trim().startsWith('$$')) {
      const mathLines: string[] = [];
      const firstMath = line.trim().replace(/^\$\$/, '').replace(/\$\$$/, '').trim();
      if (firstMath) mathLines.push(firstMath);
      index += 1;
      while (index < lines.length && !lines[index].trim().endsWith('$$')) {
        mathLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        mathLines.push(lines[index].trim().replace(/\$\$$/, '').trim());
        index += 1;
      }
      nodes.push(<div className="math-block" key={`math-${index}`}>{formatMath(mathLines.join(' '))}</div>);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = Math.min(heading[1].length, 4);
      const Tag = `h${level + 2}` as keyof JSX.IntrinsicElements;
      nodes.push(<Tag key={`heading-${index}`}>{renderInlineMarkdown(heading[2])}</Tag>);
      index += 1;
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*+]\s+/, ''));
        index += 1;
      }
      nodes.push(<ul key={`ul-${index}`}>{items.map((item, itemIndex) => <li key={`${item}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>)}</ul>);
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+[.)]\s+/, ''));
        index += 1;
      }
      nodes.push(<ol key={`ol-${index}`}>{items.map((item, itemIndex) => <li key={`${item}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>)}</ol>);
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quoteLines: string[] = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^\s*>\s?/, ''));
        index += 1;
      }
      nodes.push(<blockquote key={`quote-${index}`}>{renderInlineMarkdown(quoteLines.join(' '))}</blockquote>);
      continue;
    }

    const paragraph: string[] = [line.trim()];
    index += 1;
    while (
      index < lines.length
      && lines[index].trim()
      && !/^(#{1,6})\s+/.test(lines[index])
      && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[index])
      && !/^\s*>\s?/.test(lines[index])
      && !lines[index].startsWith('```')
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    nodes.push(<p key={`p-${index}`}>{renderInlineMarkdown(paragraph.join(' '))}</p>);
  }

  return nodes;
}

function renderInlineMarkdown(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const pattern = /(`[^`]+`|\$\$[^$]+\$\$|\$[^$\n]+\$|\\\([^)]+\\\)|\\\[[\s\S]+?\\\]|\*\*[^*]+\*\*|\*[^*]+\*|!\[[^\]]*]\([^)]+\)|\[[^\]]+]\([^)]+\)|\[\[[^\]]+]])/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const token = match[0];
    const key = `${token}-${match.index}`;

    if (token.startsWith('`')) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith('$$')) {
      nodes.push(<span className="math-inline" key={key}>{formatMath(token.slice(2, -2))}</span>);
    } else if (token.startsWith('$')) {
      nodes.push(<span className="math-inline" key={key}>{formatMath(token.slice(1, -1))}</span>);
    } else if (token.startsWith('\\(')) {
      nodes.push(<span className="math-inline" key={key}>{formatMath(token.slice(2, -2))}</span>);
    } else if (token.startsWith('\\[')) {
      nodes.push(<span className="math-inline" key={key}>{formatMath(token.slice(2, -2))}</span>);
    } else if (token.startsWith('**')) {
      nodes.push(<strong key={key}>{renderInlineMarkdown(token.slice(2, -2))}</strong>);
    } else if (token.startsWith('*')) {
      nodes.push(<em key={key}>{renderInlineMarkdown(token.slice(1, -1))}</em>);
    } else if (token.startsWith('![')) {
      const image = token.match(/^!\[([^\]]*)]\\(([^)]+)\\)$/);
      nodes.push(image ? <span className="markdown-image-alt" key={key}>{image[1] || image[2]}</span> : token);
    } else if (token.startsWith('[[')) {
      const label = token.slice(2, -2).split('|').pop() || token.slice(2, -2);
      nodes.push(<span className="wikilink" key={key}>{label}</span>);
    } else {
      const link = token.match(/^\[([^\]]+)]\(([^)]+)\)$/);
      nodes.push(link ? <a key={key} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a> : token);
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

function formatMath(value: string) {
  const replacements: Array<[RegExp, string]> = [
    [/\\alpha/g, 'α'], [/\\beta/g, 'β'], [/\\gamma/g, 'γ'], [/\\delta/g, 'δ'],
    [/\\epsilon/g, 'ε'], [/\\lambda/g, 'λ'], [/\\mu/g, 'μ'], [/\\pi/g, 'π'],
    [/\\sigma/g, 'σ'], [/\\theta/g, 'θ'], [/\\omega/g, 'ω'], [/\\Omega/g, 'Ω'],
    [/\\times/g, '×'], [/\\cdot/g, '·'], [/\\leq?/g, '≤'], [/\\geq?/g, '≥'],
    [/\\neq/g, '≠'], [/\\approx/g, '≈'], [/\\infty/g, '∞'], [/\\sum/g, '∑'],
    [/\\prod/g, '∏'], [/\\sqrt/g, '√'], [/\\rightarrow/g, '→'], [/\\to/g, '→'],
    [/\\left/g, ''], [/\\right/g, ''], [/\\,/g, ' '],
  ];
  let rendered = value.replace(/\\frac\{([^{}]+)\}\{([^{}]+)\}/g, '($1)/($2)');
  for (const [pattern, replacement] of replacements) {
    rendered = rendered.replace(pattern, replacement);
  }
  return rendered
    .replace(/\^(\{([^{}]+)\}|([A-Za-z0-9+\-=]+))/g, (_, __, braced, plain) => toSuperscript(braced || plain))
    .replace(/_(\{([^{}]+)\}|([A-Za-z0-9+\-=]+))/g, (_, __, braced, plain) => toSubscript(braced || plain))
    .replace(/[{}]/g, '')
    .trim();
}

function toSuperscript(value: string) {
  const map: Record<string, string> = { '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹', '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾', n: 'ⁿ', i: 'ⁱ' };
  return value.split('').map((char) => map[char] ?? char).join('');
}

function toSubscript(value: string) {
  const map: Record<string, string> = { '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄', '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉', '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎', a: 'ₐ', e: 'ₑ', h: 'ₕ', i: 'ᵢ', j: 'ⱼ', k: 'ₖ', l: 'ₗ', m: 'ₘ', n: 'ₙ', o: 'ₒ', p: 'ₚ', r: 'ᵣ', s: 'ₛ', t: 'ₜ', u: 'ᵤ', v: 'ᵥ', x: 'ₓ' };
  return value.split('').map((char) => map[char] ?? char).join('');
}
